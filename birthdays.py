"""
services/attendance.py — логіка відвідуваності.

Пріоритет #2 у бізнес-логіці.
- Нагадування тренеру перед заняттям
- Запит на позначення присутності/відсутності
- Алерт власнику якщо журнал не закрито
- Виявлення неактивних дітей (7/14/21 день)
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from app.models import (
    AttendanceRecord,
    AttendanceStatus,
    Group,
    Member,
    ReminderType,
)
from app.repositories.base import (
    IAttendanceRepository,
    IGroupRepository,
    IMemberRepository,
)
from app.services.notifications import NotificationService
from app.services.templates import TemplateService
from app import keyboards as kb

log = logging.getLogger(__name__)

# Порогові значення неактивності (дні)
INACTIVITY_THRESHOLDS = [7, 14, 21]


class AttendanceService:
    """
    Керує відвідуваністю: нагадування тренерам, виявлення неактивних, unclosed-алерти.
    """

    def __init__(
        self,
        attendance: IAttendanceRepository,
        groups: IGroupRepository,
        members: IMemberRepository,
        notifications: NotificationService,
        templates: TemplateService,
        owner_chat_id: int,
    ) -> None:
        self._attendance = attendance
        self._groups = groups
        self._members = members
        self._notifications = notifications
        self._templates = templates
        self._owner_chat_id = owner_chat_id
        self._lesson_prompt_sent: set[str] = set()

    # ── Нагадування тренерам ──────────────────────────────────────────────────

    def send_coach_reminders(self, lesson_date: Optional[date] = None) -> int:
        """
        Надсилає нагадування тренерам усіх активних груп про позначення відвідуваності.
        Повертає кількість надісланих повідомлень.
        """
        lesson_date = lesson_date or date.today()
        groups = self._groups.get_active()
        sent = 0

        for group in groups:
            if not group.coach_telegram_id:
                continue
            text = self._templates.render(
                "attendance_coach_reminder",
                group_name=group.name,
                lesson_date=lesson_date.strftime("%d.%m.%Y"),
            )
            ok = self._notifications.send(
                group.coach_telegram_id,
                text,
                reminder_type=ReminderType.ATTENDANCE,
                target_id=group.group_id,
            )
            if ok:
                sent += 1
                log.info("Нагадування тренеру групи '%s' надіслано", group.name)

        return sent

    def send_due_group_attendance_prompts(self, now: Optional[datetime] = None) -> int:
        """
        Автостарт attendance за розкладом груп.

        Підтримує формат:
        "пн,ср,пт 18:00-18:40" або "пн, ср, пт 18 00 - 18 40".
        """
        now = now or datetime.now()
        sent = 0
        for group in self._groups.get_active():
            if not group.coach_telegram_id:
                continue
            if not _schedule_matches_now(group.schedule, now):
                continue
            key = f"{group.group_id}:{now.strftime('%Y-%m-%d:%H:%M')}"
            if key in self._lesson_prompt_sent:
                continue
            journal = self.get_journal_for_group(group.group_id, now.date())
            names = "\n".join([f"• {item['full_name']}" for item in journal]) or "У групі поки немає учасників."
            text = (
                f"📋 <b>Починається тренування</b>\n\n"
                f"Група: <b>{group.name}</b>\n"
                f"Час: {now.strftime('%H:%M')}\n"
                f"Розклад: {group.schedule}\n\n"
                f"<b>Список учасників:</b>\n{names}\n\n"
                "Відмітьте присутніх/відсутніх кнопками нижче."
            )
            ok = self._notifications.send(
                group.coach_telegram_id,
                text,
                reminder_type=ReminderType.ATTENDANCE,
                target_id=group.group_id,
                reply_markup=kb.mark_attendance_keyboard(group.group_id, str(now.date()), journal),
            )
            if ok:
                self._lesson_prompt_sent.add(key)
                sent += 1
        return sent

    # ── Позначення відвідуваності ──────────────────────────────────────────────

    def get_journal_for_group(
        self, group_id: str, lesson_date: date
    ) -> List[Dict]:
        """
        Повертає список учнів групи зі статусом на конкретну дату.
        """
        members = self._members.get_by_group(group_id)
        records = {
            r.member_id: r
            for r in self._attendance.get_by_group_date(group_id, lesson_date)
        }
        result = []
        for member in members:
            rec = records.get(member.member_id)
            result.append({
                "member_id": member.member_id,
                "full_name": member.full_name,
                "status": rec.status.value if rec else None,
                "record_id": rec.record_id if rec else None,
            })
        return result

    def mark_attendance(
        self,
        group_id: str,
        lesson_date: date,
        member_id: str,
        status: AttendanceStatus,
        marked_by: int,
    ) -> AttendanceRecord:
        """
        Позначає або оновлює статус відвідуваності для конкретного учня.
        """
        existing = self._attendance.get_by_group_date(group_id, lesson_date)
        existing_rec = next((r for r in existing if r.member_id == member_id), None)

        if existing_rec:
            existing_rec.status = status
            existing_rec.marked_by = marked_by
            existing_rec.marked_at = datetime.now()
            self._attendance.upsert(existing_rec)
            return existing_rec
        else:
            import uuid
            record = AttendanceRecord(
                record_id=str(uuid.uuid4())[:8],
                group_id=group_id,
                lesson_date=lesson_date,
                member_id=member_id,
                status=status,
                marked_by=marked_by,
                marked_at=datetime.now(),
            )
            self._attendance.add(record)
            return record

    def close_journal(
        self, group_id: str, lesson_date: date, marked_by: int
    ) -> Tuple[int, int]:
        """
        'Закриває' журнал — позначає відсутніх для учнів без запису.
        Повертає (кількість присутніх, кількість відсутніх).
        """
        members = self._members.get_by_group(group_id)
        records = {
            r.member_id: r
            for r in self._attendance.get_by_group_date(group_id, lesson_date)
        }
        present = sum(
            1 for r in records.values() if r.status == AttendanceStatus.PRESENT
        )
        # Не відмічені → absent
        for member in members:
            if member.member_id not in records:
                self.mark_attendance(
                    group_id, lesson_date, member.member_id,
                    AttendanceStatus.ABSENT, marked_by
                )
        absent = len(members) - present
        log.info(
            "Журнал закрито: група=%s дата=%s присутніх=%d відсутніх=%d",
            group_id, lesson_date, present, absent
        )
        return present, absent

    def is_journal_closed(self, group_id: str, lesson_date: date) -> bool:
        """Перевіряє чи відмічено хоча б одного учня в журналі."""
        records = self._attendance.get_by_group_date(group_id, lesson_date)
        return len(records) > 0

    # ── Незакриті журнали (алерти власнику) ────────────────────────────────────

    def check_unclosed_journals(self, lesson_date: Optional[date] = None) -> int:
        """
        Перевіряє незакриті журнали всіх активних груп.
        Надсилає алерт власнику для кожної незакритої групи.
        Повертає кількість незакритих.
        """
        lesson_date = lesson_date or date.today()
        groups = self._groups.get_active()
        unclosed = 0

        for group in groups:
            if not self.is_journal_closed(group.group_id, lesson_date):
                unclosed += 1
                # Знаходимо ім'я тренера
                coach_name = f"ID {group.coach_telegram_id}" if group.coach_telegram_id else "Невідомий"
                text = self._templates.render(
                    "attendance_unclosed_alert",
                    group_name=group.name,
                    lesson_date=lesson_date.strftime("%d.%m.%Y"),
                    coach_name=coach_name,
                )
                self._notifications.send_to_owner(self._owner_chat_id, text)
                log.warning("Незакритий журнал: група '%s' за %s", group.name, lesson_date)

        return unclosed

    # ── Неактивні учні ────────────────────────────────────────────────────────

    def get_inactive_members(
        self, threshold_days: int = 7
    ) -> List[Tuple[Member, int]]:
        """
        Повертає список (учень, кількість_днів_без_відвідування)
        для учнів, що не відвідували threshold_days і більше.
        """
        members = self._members.get_active()
        today = date.today()
        inactive = []

        for member in members:
            records = self._attendance.get_member_last_n_days(
                member.member_id, threshold_days
            )
            # Фільтруємо лише 'present' записи
            present_records = [
                r for r in records if r.status == AttendanceStatus.PRESENT
            ]
            if not present_records:
                # Знаходимо дату останнього відвідування за всю историю
                all_records = self._attendance.get_by_member(member.member_id)
                present_all = [
                    r for r in all_records if r.status == AttendanceStatus.PRESENT
                ]
                if not present_all:
                    days_absent = threshold_days  # ніколи не відвідував
                else:
                    last_present = max(r.lesson_date for r in present_all)
                    days_absent = (today - last_present).days

                if days_absent >= threshold_days:
                    inactive.append((member, days_absent))

        return sorted(inactive, key=lambda x: x[1], reverse=True)

    def send_inactivity_alerts(self) -> Dict[int, int]:
        """
        Надсилає власнику нагадування для неактивних учнів.
        Порогові значення: 7, 14, 21 день.
        Повертає dict {threshold: count_sent}.
        """
        results: Dict[int, int] = {}
        processed_members = set()

        for threshold in sorted(INACTIVITY_THRESHOLDS, reverse=True):
            inactive = self.get_inactive_members(threshold)
            count = 0
            for member, days_absent in inactive:
                if member.member_id in processed_members:
                    continue
                if days_absent >= threshold:
                    tmpl_name = f"inactivity_{threshold}_days"
                    text = self._templates.render(
                        tmpl_name,
                        child_name=member.full_name,
                        days=days_absent,
                    )
                    ok = self._notifications.send_to_owner(self._owner_chat_id, text)
                    if ok:
                        count += 1
                        processed_members.add(member.member_id)

            results[threshold] = count
            log.info("Неактивних (>=%d днів): %d сповіщень", threshold, count)

        return results

    def get_attendance_summary(self, group_id: str, lesson_date: date) -> str:
        """Повертає текстовий звіт по журналу групи."""
        journal = self.get_journal_for_group(group_id, lesson_date)
        group = self._groups.get_by_id(group_id)
        group_name = group.name if group else group_id

        lines = [
            f"📋 <b>Журнал групи «{group_name}»</b>",
            f"📅 {lesson_date.strftime('%d.%m.%Y')}\n"
        ]
        present_list = [j for j in journal if j["status"] == "present"]
        absent_list = [j for j in journal if j["status"] == "absent"]
        excused_list = [j for j in journal if j["status"] == "excused"]
        unmarked = [j for j in journal if j["status"] is None]

        if present_list:
            lines.append(f"✅ Присутні ({len(present_list)}):")
            for j in present_list:
                lines.append(f"  • {j['full_name']}")

        if absent_list:
            lines.append(f"\n❌ Відсутні ({len(absent_list)}):")
            for j in absent_list:
                lines.append(f"  • {j['full_name']}")

        if excused_list:
            lines.append(f"\n📋 Поважна причина ({len(excused_list)}):")
            for j in excused_list:
                lines.append(f"  • {j['full_name']}")

        if unmarked:
            lines.append(f"\n⬜ Не відмічено ({len(unmarked)}):")
            for j in unmarked:
                lines.append(f"  • {j['full_name']}")

        return "\n".join(lines)


# ── Чисті функції для тестів ──────────────────────────────────────────────────

def _schedule_matches_now(schedule: str, now: datetime) -> bool:
    if not schedule:
        return False
    normalized = schedule.lower().replace(" ", "")
    day_map = {
        0: ("пн", "понеділок", "mon", "monday"),
        1: ("вт", "вівторок", "tue", "tuesday"),
        2: ("ср", "середа", "wed", "wednesday"),
        3: ("чт", "четвер", "thu", "thursday"),
        4: ("пт", "пʼятниця", "п'ятниця", "пятниця", "fri", "friday"),
        5: ("сб", "субота", "sat", "saturday"),
        6: ("нд", "неділя", "sun", "sunday"),
    }
    if not any(token in normalized for token in day_map[now.weekday()]):
        return False
    match = re.search(r"(\d{1,2})[:.]?(\d{2})", normalized)
    if not match:
        return False
    return now.hour == int(match.group(1)) and abs(now.minute - int(match.group(2))) <= 2

def find_inactive_from_records(
    records: List[AttendanceRecord],
    all_member_ids: List[str],
    threshold_days: int,
    reference_date: Optional[date] = None,
) -> List[Tuple[str, int]]:
    """
    Чиста функція без Sheets-залежності.
    Повертає [(member_id, days_absent)] для неактивних учнів.
    """
    today = reference_date or date.today()
    cutoff = today - timedelta(days=threshold_days)
    result = []

    for member_id in all_member_ids:
        member_records = [
            r for r in records
            if r.member_id == member_id and r.status == AttendanceStatus.PRESENT
        ]
        if not member_records:
            result.append((member_id, threshold_days))
            continue
        last_present = max(r.lesson_date for r in member_records)
        days_absent = (today - last_present).days
        if days_absent >= threshold_days:
            result.append((member_id, days_absent))

    return result
