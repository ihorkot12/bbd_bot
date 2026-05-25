"""
services/digest.py — щоденний дайджест для власника.

Збирає в одне повідомлення:
- Нові ліди
- Проби сьогодні / завтра
- Несплачені / прострочені / частково / обіцяні оплати
- Незакриті журнали відвідуваності
- Неактивні учні
- Найближчі події / дедлайни
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from app.models import LeadStatus, PaymentStatus
from app.repositories.base import (
    IAttendanceRepository,
    IEventRepository,
    IGroupRepository,
    ILeadRepository,
    IMemberRepository,
    IPaymentRepository,
)
from app.services.attendance import AttendanceService
from app.services.events import EventService
from app.services.leads import LeadService
from app.services.notifications import NotificationService
from app.services.payments import PaymentService, _format_period, _status_icon

log = logging.getLogger(__name__)

# Максимальна довжина одного блоку дайджесту (символи)
_MAX_BLOCK = 3000


class DigestService:
    """
    Збирає та надсилає щоденний дайджест власнику.
    """

    def __init__(
        self,
        payments_svc: PaymentService,
        attendance_svc: AttendanceService,
        leads_svc: LeadService,
        events_svc: EventService,
        leads: ILeadRepository,
        groups: IGroupRepository,
        notifications: NotificationService,
        owner_chat_id: int,
    ) -> None:
        self._payments_svc = payments_svc
        self._attendance_svc = attendance_svc
        self._leads_svc = leads_svc
        self._events_svc = events_svc
        self._leads = leads
        self._groups = groups
        self._notifications = notifications
        self._owner_chat_id = owner_chat_id

    def build(self, reference_date: Optional[date] = None) -> str:
        """
        Збирає повний текст дайджесту.
        """
        today = reference_date or date.today()
        tomorrow = today + timedelta(days=1)
        period = today.strftime("%Y-%m")

        sections: list[str] = []

        # ── Заголовок ─────────────────────────────────────────────────────────
        sections.append(
            f"📊 <b>Дайджест Black Bear Dojo</b>\n"
            f"📅 {today.strftime('%d.%m.%Y')} ({_weekday_ua(today)})\n"
            f"{'─' * 28}"
        )

        # ── Ліди ─────────────────────────────────────────────────────────────
        try:
            all_leads = self._leads.get_all()
            new_leads = [ld for ld in all_leads if ld.status == LeadStatus.NEW]
            trials_today = self._leads.get_trials_on_date(today)
            trials_tomorrow = self._leads.get_trials_on_date(tomorrow)
            done_no_decision = [ld for ld in all_leads if ld.status == LeadStatus.TRIAL_DONE]

            lines = ["🔍 <b>Ліди та проби:</b>"]
            lines.append(f"  Нові ліди: <b>{len(new_leads)}</b>")
            if trials_today:
                lines.append(f"  ⚡ Проби сьогодні: <b>{len(trials_today)}</b>")
                for ld in trials_today[:5]:
                    pt = "👤" if getattr(ld, 'is_adult', False) else "🧒"
                    lines.append(f"    {pt} {ld.child_name}")
            if trials_tomorrow:
                lines.append(f"  📅 Проби завтра: <b>{len(trials_tomorrow)}</b>")
                for ld in trials_tomorrow[:5]:
                    lines.append(f"    • {ld.child_name}")
            if done_no_decision:
                lines.append(f"  ⏳ Після проби (без рішення): <b>{len(done_no_decision)}</b>")
            sections.append("\n".join(lines))
        except Exception as e:
            log.warning("Помилка блоку лідів у дайджесті: %s", e)
            sections.append("🔍 Ліди: помилка завантаження")

        # ── Оплати ────────────────────────────────────────────────────────────
        try:
            debtors = self._payments_svc.get_debtors(period)
            overdue = [(m, p) for m, p in debtors if p.status == PaymentStatus.OVERDUE]
            unpaid = [(m, p) for m, p in debtors if p.status == PaymentStatus.UNPAID]
            partial = [(m, p) for m, p in debtors if p.status == PaymentStatus.PARTIAL]
            promised_exp = self._payments_svc.get_promised_expired()

            lines = [f"💰 <b>Оплати ({_format_period(period)}):</b>"]
            lines.append(f"  🔴 Прострочено: <b>{len(overdue)}</b>")
            lines.append(f"  ❌ Не сплачено: <b>{len(unpaid)}</b>")
            lines.append(f"  💛 Частково: <b>{len(partial)}</b>")
            if promised_exp:
                lines.append(f"  ⚠️ Обіцяно (прострочено): <b>{len(promised_exp)}</b>")
                for m, p in promised_exp[:3]:
                    lines.append(f"    • {m.full_name} (до {p.promised_date})")
            sections.append("\n".join(lines))
        except Exception as e:
            log.warning("Помилка блоку оплат у дайджесті: %s", e)
            sections.append("💰 Оплати: помилка завантаження")

        # ── Відвідуваність ────────────────────────────────────────────────────
        try:
            groups = self._groups.get_active()
            unclosed = [
                g for g in groups
                if not self._attendance_svc.is_journal_closed(g.group_id, today)
            ]
            inactive_7 = self._attendance_svc.get_inactive_members(7)
            inactive_14 = self._attendance_svc.get_inactive_members(14)
            inactive_21 = self._attendance_svc.get_inactive_members(21)

            lines = ["📋 <b>Відвідуваність:</b>"]
            lines.append(f"  Груп для позначення сьогодні: <b>{len(groups)}</b>")
            if unclosed:
                lines.append(f"  ⚠️ Незакриті журнали: <b>{len(unclosed)}</b>")
                for g in unclosed[:3]:
                    lines.append(f"    • {g.name}")

            if inactive_21:
                lines.append(f"  🔴 Відсутні 21+ день: <b>{len(inactive_21)}</b>")
                for m, d in inactive_21[:3]:
                    lines.append(f"    • {m.full_name} ({d} днів)")
            elif inactive_14:
                lines.append(f"  ⚠️ Відсутні 14+ день: <b>{len(inactive_14)}</b>")
            if inactive_7:
                lines.append(f"  😟 Відсутні 7+ днів: <b>{len(inactive_7)}</b>")
            sections.append("\n".join(lines))
        except Exception as e:
            log.warning("Помилка блоку відвідуваності у дайджесті: %s", e)
            sections.append("📋 Відвідуваність: помилка завантаження")

        # ── Події ─────────────────────────────────────────────────────────────
        try:
            events_block = self._events_svc.get_upcoming_summary(days=7)
            sections.append(events_block)
        except Exception as e:
            log.warning("Помилка блоку подій у дайджесті: %s", e)

        return "\n\n".join(sections)

    def send(self, reference_date: Optional[date] = None) -> bool:
        """Збирає і надсилає дайджест власнику."""
        try:
            text = self.build(reference_date)
            # Якщо текст задовгий — ділимо на частини
            if len(text) <= 4096:
                return self._notifications.send_to_owner(self._owner_chat_id, text)
            else:
                # Ділимо по секціях
                parts = text.split("\n\n")
                chunk = ""
                ok = True
                for part in parts:
                    if len(chunk) + len(part) + 2 > 4096:
                        if chunk:
                            ok = self._notifications.send_to_owner(self._owner_chat_id, chunk) and ok
                        chunk = part
                    else:
                        chunk = (chunk + "\n\n" + part).strip()
                if chunk:
                    ok = self._notifications.send_to_owner(self._owner_chat_id, chunk) and ok
                return ok
        except Exception as e:
            log.error("Помилка надсилання дайджесту: %s", e)
            return False


# ── Хелпери ───────────────────────────────────────────────────────────────────

def _weekday_ua(d: date) -> str:
    days = ["Понеділок", "Вівторок", "Середа", "Четвер",
            "П'ятниця", "Субота", "Неділя"]
    return days[d.weekday()]


def build_digest_text(
    new_leads_count: int,
    trials_today: list,
    trials_tomorrow: list,
    overdue_count: int,
    unpaid_count: int,
    partial_count: int,
    promised_expired: list,
    unclosed_journals: list,
    inactive_members: list,
    upcoming_events: list,
    period: str,
    today: Optional[date] = None,
) -> str:
    """
    Чиста функція для тестів — збирає текст дайджесту без залежностей.
    """
    today = today or date.today()
    lines = [
        f"📊 <b>Дайджест Black Bear Dojo</b>",
        f"📅 {today.strftime('%d.%m.%Y')} ({_weekday_ua(today)})",
        f"{'─' * 28}",
        "",
        f"🔍 <b>Ліди:</b> нових {new_leads_count}, "
        f"проби сьогодні {len(trials_today)}, "
        f"завтра {len(trials_tomorrow)}",
        "",
        f"💰 <b>Оплати ({_format_period(period)}):</b>",
        f"  🔴 Прострочено: {overdue_count}",
        f"  ❌ Не сплачено: {unpaid_count}",
        f"  💛 Частково: {partial_count}",
        f"  ⚠️ Обіцяно (прострочено): {len(promised_expired)}",
        "",
        f"📋 <b>Відвідуваність:</b>",
        f"  ⚠️ Незакриті журнали: {len(unclosed_journals)}",
        f"  😟 Неактивних учнів: {len(inactive_members)}",
        "",
    ]
    if upcoming_events:
        lines.append("📅 <b>Найближчі події:</b>")
        for ev in upcoming_events[:5]:
            d = ev.get("date", "—")
            t = ev.get("title", "—")
            lines.append(f"  • {d} — {t}")

    return "\n".join(lines)
