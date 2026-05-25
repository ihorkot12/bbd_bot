"""
services/leads.py — лід/проб'ний воронка.

Підтримує:
- Дитячі ліди (participant_type=child): потребує даних батьків/опікунів
- Дорослі ліди (participant_type=adult): дані батьків опціональні
- Джерела реєстрації: google_form / bot

Флоу:
  new → trial_scheduled → trial_done → converted / declined / rescheduled
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import List, Optional, Tuple

from app.models import (
    Lead,
    LeadStatus,
    Member,
    ParticipantType,
    ReminderType,
    RegistrationSource,
)
from app.repositories.base import ILeadRepository, IMemberRepository
from app.services.notifications import NotificationService
from app.services.templates import TemplateService

log = logging.getLogger(__name__)


class LeadService:
    """
    Керує воронкою лідів та пробних тренувань.
    """

    def __init__(
        self,
        leads: ILeadRepository,
        members: IMemberRepository,
        notifications: NotificationService,
        templates: TemplateService,
        owner_chat_id: int,
        club_address: str,
        club_phone: str,
    ) -> None:
        self._leads = leads
        self._members = members
        self._notifications = notifications
        self._templates = templates
        self._owner_chat_id = owner_chat_id
        self._club_address = club_address
        self._club_phone = club_phone

    # ── Створення ліда ────────────────────────────────────────────────────────

    def create_lead(
        self,
        child_name: str,
        parent_name: str,
        participant_type: "ParticipantType" = None,
        parent_telegram_id: Optional[int] = None,
        parent_phone: Optional[str] = None,
        trial_date: Optional[date] = None,
        trial_group_id: Optional[str] = None,
        source: str = "bot",
        notes: Optional[str] = None,
    ) -> Lead:
        """
        Створює новий лід.
        Для дорослих (participant_type=adult) parent_name/phone є ОПЦІОНАЛЬНИМи.
        """
        from app.models import ParticipantType as PT
        pt = participant_type or PT.CHILD
        lead = Lead(
            lead_id=str(uuid.uuid4())[:8],
            child_name=child_name,
            parent_name=parent_name,
            participant_type=pt,
            parent_telegram_id=parent_telegram_id,
            parent_phone=parent_phone,
            status=LeadStatus.NEW if not trial_date else LeadStatus.TRIAL_SCHEDULED,
            trial_date=trial_date,
            trial_group_id=trial_group_id,
            source=source,
            notes=notes,
            created_at=datetime.now(),
        )
        self._leads.add(lead)
        log.info("Новий лід створено: %s (тип=%s, джерело=%s)", child_name, pt.value, source)
        return lead

    def create_lead_from_form(
        self,
        form_data: dict,
    ) -> Lead:
        """
        Створює лід з даних Google Form (або веб-реєстрації).
        form_data keys: child_name, parent_name, parent_phone, participant_type,
                        trial_date (optional), notes (optional)
        """
        from app.models import ParticipantType as PT
        pt_raw = str(form_data.get("participant_type", "child")).lower()
        try:
            pt = PT(pt_raw)
        except ValueError:
            pt = PT.CHILD

        return self.create_lead(
            child_name=form_data.get("child_name") or form_data.get("full_name") or "",
            parent_name=form_data.get("parent_name") or "",
            participant_type=pt,
            parent_telegram_id=None,
            parent_phone=form_data.get("parent_phone") or form_data.get("phone"),
            trial_date=_parse_date_flexible(form_data.get("trial_date")),
            source="google_form",
            notes=form_data.get("notes"),
        )

    # ── Нагадування про проб'ні ───────────────────────────────────────────────

    def send_trial_confirmation(self, lead: Lead, group_schedule: str = "") -> bool:
        """Надсилає підтвердження батькам/дорослому після запису на пробне."""
        if not lead.parent_telegram_id:
            return False

        # Для дорослого — звернення на ім'я самого учасника
        recipient_name = (
            lead.child_name
            if lead.is_adult
            else lead.parent_name or lead.child_name
        )

        text = self._templates.render(
            "trial_confirmation",
            child_name=lead.child_name,
            parent_name=recipient_name,
            trial_date=lead.trial_date.strftime("%d.%m.%Y") if lead.trial_date else "—",
            address=self._club_address,
            schedule=group_schedule,
            phone=self._club_phone,
        )
        return self._notifications.send(
            lead.parent_telegram_id,
            text,
            reminder_type=ReminderType.TRIAL,
            target_id=lead.lead_id,
        )

    def send_trial_reminders(self) -> Tuple[int, int]:
        """
        Надсилає нагадування:
        - батькам/дорослому за день до проб'ного (trial_reminder)
        - батькам/дорослому у день проб'ного (trial_day_reminder)
        Повертає (day_before_sent, today_sent).
        """
        today = date.today()
        tomorrow = today
        yesterday = today  # "today" reminder

        day_before = 0
        day_of = 0

        # Проби завтра
        trials_tomorrow = [
            ld for ld in self._leads.get_by_status(LeadStatus.TRIAL_SCHEDULED)
            if ld.trial_date and (ld.trial_date - today).days == 1
        ]
        for lead in trials_tomorrow:
            if not lead.parent_telegram_id:
                continue
            text = self._templates.render(
                "trial_reminder",
                child_name=lead.child_name,
                trial_date=lead.trial_date.strftime("%d.%m.%Y"),
                address=self._club_address,
            )
            ok = self._notifications.send(
                lead.parent_telegram_id,
                text,
                reminder_type=ReminderType.TRIAL,
                target_id=lead.lead_id,
            )
            if ok:
                day_before += 1

        # Проби сьогодні
        trials_today = self._leads.get_trials_on_date(today)
        trials_today = [
            ld for ld in trials_today if ld.status == LeadStatus.TRIAL_SCHEDULED
        ]
        for lead in trials_today:
            if not lead.parent_telegram_id:
                continue
            text = self._templates.render(
                "trial_day_reminder",
                child_name=lead.child_name,
                address=self._club_address,
            )
            ok = self._notifications.send(
                lead.parent_telegram_id,
                text,
                reminder_type=ReminderType.TRIAL,
                target_id=lead.lead_id,
            )
            if ok:
                day_of += 1

        return day_before, day_of

    def notify_after_trial(self, lead: Lead) -> None:
        """
        Надсилає власнику кнопки після пробного тренування.
        """
        from app.keyboards import after_trial_keyboard
        text = self._templates.render(
            "after_trial_owner",
            child_name=lead.child_name,
            parent_name=lead.parent_name or "—",
            trial_date=lead.trial_date.strftime("%d.%m.%Y") if lead.trial_date else "—",
        )
        self._notifications.send(
            self._owner_chat_id,
            text,
            reply_markup=after_trial_keyboard(lead.lead_id),
        )

    # ── Рішення після проб'ного ───────────────────────────────────────────────

    def mark_trial_present(self, lead_id: str) -> Optional[Lead]:
        lead = self._leads.get_by_id(lead_id)
        if not lead:
            return None
        lead.status = LeadStatus.TRIAL_DONE
        lead.trial_present = True
        lead.updated_at = datetime.now()
        self._leads.upsert(lead)
        log.info("Пробне відвідав: %s (lead=%s)", lead.child_name, lead_id)
        return lead

    def mark_trial_absent(self, lead_id: str) -> Optional[Lead]:
        lead = self._leads.get_by_id(lead_id)
        if not lead:
            return None
        lead.status = LeadStatus.TRIAL_DONE
        lead.trial_present = False
        lead.updated_at = datetime.now()
        self._leads.upsert(lead)
        return lead

    def reschedule_trial(self, lead_id: str, new_date: date) -> Optional[Lead]:
        lead = self._leads.get_by_id(lead_id)
        if not lead:
            return None
        lead.trial_date = new_date
        lead.status = LeadStatus.RESCHEDULED
        lead.updated_at = datetime.now()
        self._leads.upsert(lead)
        return lead

    def convert_to_member(
        self,
        lead_id: str,
        group_id: str,
        performed_by: int,
    ) -> Optional[Member]:
        """
        Конвертує лід у повноцінного учня.
        Підтримує як дітей (зберігає parent_telegram_id), так і дорослих.
        """
        lead = self._leads.get_by_id(lead_id)
        if not lead:
            log.error("Лід %s не знайдено", lead_id)
            return None

        member = Member(
            member_id=str(uuid.uuid4())[:8],
            full_name=lead.child_name,
            birth_date=None,
            participant_type=lead.participant_type,
            parent_telegram_id=lead.parent_telegram_id if not lead.is_adult else None,
            parent_name=lead.parent_name if not lead.is_adult else None,
            parent_phone=lead.parent_phone,
            group_id=group_id,
            active=True,
            join_date=date.today(),
            registration_source=lead.source or "bot",
            notes=lead.notes,
        )
        self._members.add(member)

        # Оновлюємо статус ліда
        lead.status = LeadStatus.CONVERTED
        lead.updated_at = datetime.now()
        self._leads.upsert(lead)

        log.info(
            "Лід %s конвертовано у учня %s (тип=%s)",
            lead_id, member.member_id, member.participant_type.value
        )

        # Сповіщаємо батьків/дорослого
        if lead.parent_telegram_id:
            text = self._templates.render(
                "info_first_visit",
                child_name=lead.child_name,
                address=self._club_address,
                trial_date=date.today().strftime("%d.%m.%Y"),
                phone=self._club_phone,
            )
            self._notifications.send(lead.parent_telegram_id, text)

        return member

    # ── Зведення лідів ────────────────────────────────────────────────────────

    def get_leads_summary(self) -> str:
        """Текстовий звіт по лідах для дайджесту."""
        all_leads = self._leads.get_all()
        new = [ld for ld in all_leads if ld.status == LeadStatus.NEW]
        scheduled = [ld for ld in all_leads if ld.status == LeadStatus.TRIAL_SCHEDULED]
        done = [ld for ld in all_leads if ld.status == LeadStatus.TRIAL_DONE]

        lines = ["🔍 <b>Ліди та проби:</b>"]
        lines.append(f"  Нові: {len(new)}")
        lines.append(f"  Заплановано пробних: {len(scheduled)}")
        lines.append(f"  Проведено (без рішення): {len(done)}")

        today = date.today()
        today_trials = self._leads.get_trials_on_date(today)
        tomorrow_trials = self._leads.get_trials_on_date(
            date.today().replace(day=today.day + 1) if today.day < 28
            else today  # спрощено
        )
        if today_trials:
            lines.append(f"\n📅 Проби сьогодні ({len(today_trials)}):")
            for ld in today_trials:
                pt_label = "👤" if ld.is_adult else "🧒"
                lines.append(f"  {pt_label} {ld.child_name}")

        return "\n".join(lines)


# ── Хелпери ───────────────────────────────────────────────────────────────────

def _parse_date_flexible(value) -> Optional[date]:
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
