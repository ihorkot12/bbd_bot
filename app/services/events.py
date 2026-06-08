"""
services/events.py — логіка подій та анонсів.

- Створення подій
- Оголошення учасникам
- Автоматичні нагадування за N днів до події
- Відстеження документів, атестацій, федеральних міток
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import List, Optional

from app.models import Event, EventStatus, Member, ReminderType, UserRole
from app.repositories.base import (
    IEventRepository,
    IMemberRepository,
    IUserRoleRepository,
)
from app.services.notifications import NotificationService
from app.services.templates import TemplateService

log = logging.getLogger(__name__)

# За скільки днів до події надсилати нагадування
DEFAULT_REMINDER_DAYS_BEFORE = 3


class EventService:
    """
    Управляє подіями: створення, анонси, нагадування.
    """

    def __init__(
        self,
        events: IEventRepository,
        members: IMemberRepository,
        users: IUserRoleRepository,
        notifications: NotificationService,
        templates: TemplateService,
        owner_chat_id: int,
        reminder_days_before: int = DEFAULT_REMINDER_DAYS_BEFORE,
    ) -> None:
        self._events = events
        self._members = members
        self._users = users
        self._notifications = notifications
        self._templates = templates
        self._owner_chat_id = owner_chat_id
        self._reminder_days_before = reminder_days_before

    # ── Створення події ───────────────────────────────────────────────────────

    def create_event(
        self,
        title: str,
        event_date: Optional[date],
        description: Optional[str],
        audience: str = "all",
        created_by: Optional[int] = None,
    ) -> Event:
        event = Event(
            event_id=str(uuid.uuid4())[:8],
            title=title,
            event_date=event_date,
            description=description,
            status=EventStatus.PLANNED,
            audience=audience,
            reminder_sent=False,
            created_by=created_by,
            created_at=datetime.now(),
        )
        self._events.add(event)
        log.info("Подія створена: '%s' (%s)", title, event_date)
        return event

    # ── Анонс події ────────────────────────────────────────────────────────────

    def announce_event(self, event_id: str) -> int:
        """
        Надсилає анонс події відповідній аудиторії.
        audience: "all" | "parents" | "coaches"
        Повертає кількість надісланих повідомлень.
        """
        event = self._events.get_by_id(event_id)
        if not event:
            log.error("Подія %s не знайдена", event_id)
            return 0

        recipients = self._get_recipients(event.audience)
        if not recipients:
            log.warning("Немає отримувачів для події %s (audience=%s)", event_id, event.audience)
            return 0

        text = self._templates.render(
            "event_announcement",
            title=event.title,
            event_date=event.event_date.strftime("%d.%m.%Y") if event.event_date else "—",
            description=event.description or "",
        )
        results = self._notifications.send_batch(
            recipients, text,
            reminder_type=ReminderType.EVENT,
            target_id=event.event_id,
        )
        sent = sum(1 for ok in results.values() if ok)

        # Оновлюємо статус
        event.status = EventStatus.ANNOUNCED
        self._events.upsert(event)
        log.info("Анонс '%s' надіслано %d/%d", event.title, sent, len(recipients))
        return sent

    # ── Автоматичні нагадування ────────────────────────────────────────────────

    def send_upcoming_reminders(
        self,
        days_before: Optional[int] = None,
    ) -> int:
        """
        Надсилає нагадування для подій, що відбудуться через days_before днів.
        Не повторює якщо reminder_sent=True.
        """
        days_before = days_before or self._reminder_days_before
        target_date = date.today() + timedelta(days=days_before)
        upcoming = [
            e for e in self._events.get_all()
            if e.event_date == target_date
            and not e.reminder_sent
            and e.status not in (EventStatus.DONE, EventStatus.CANCELLED)
        ]
        sent_total = 0
        for event in upcoming:
            recipients = self._get_recipients(event.audience)
            text = self._templates.render(
                "event_reminder",
                title=event.title,
                event_date=event.event_date.strftime("%d.%m.%Y"),
                description=event.description or "",
            )
            results = self._notifications.send_batch(
                recipients, text,
                reminder_type=ReminderType.EVENT,
                target_id=event.event_id,
            )
            sent = sum(1 for ok in results.values() if ok)
            sent_total += sent

            event.reminder_sent = True
            self._events.upsert(event)
            log.info("Нагадування '%s' → %d отримувачів", event.title, sent)

        return sent_total

    # ── Допоміжні методи ──────────────────────────────────────────────────────

    def _get_recipients(self, audience: Optional[str]) -> List[int]:
        """Повертає список telegram_id відповідно до аудиторії."""
        audience = (audience or "all").lower()
        users = self._users.get_all()
        members = self._members.get_active()

        if audience == "all":
            # Всі активні батьки та тренери
            parent_ids = {m.parent_telegram_id for m in members if m.parent_telegram_id}
            # Дорослі учасники
            adult_ids = {
                m.parent_telegram_id for m in members
                if m.parent_telegram_id and getattr(m, 'participant_type', None)
                and m.participant_type.value == 'adult'
            }
            coach_ids = {u.telegram_id for u in users if u.role.value in ("coach", "admin", "owner")}
            return list(parent_ids | adult_ids | coach_ids)

        elif audience == "parents":
            return [m.parent_telegram_id for m in members if m.parent_telegram_id]

        elif audience == "coaches":
            return [u.telegram_id for u in users if u.role.value in ("coach", "admin", "owner")]

        else:
            # Конкретна група — audience == group_id
            group_members = [m for m in members if m.group_id == audience]
            return [m.parent_telegram_id for m in group_members if m.parent_telegram_id]

    def get_upcoming_summary(self, days: int = 7) -> str:
        """Текстовий звіт найближчих подій для дайджесту."""
        upcoming = self._events.get_upcoming(days)
        if not upcoming:
            return "📅 Найближчих подій немає."
        lines = [f"📅 <b>Найближчі події (7 днів):</b>"]
        for event in upcoming:
            date_str = event.event_date.strftime("%d.%m") if event.event_date else "—"
            lines.append(f"  • {date_str} — {event.title}")
        return "\n".join(lines)

    def mark_done(self, event_id: str) -> bool:
        event = self._events.get_by_id(event_id)
        if not event:
            return False
        event.status = EventStatus.DONE
        self._events.upsert(event)
        return True
