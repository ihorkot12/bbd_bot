"""
services/birthdays.py — автоматичні привітання з днем народження.

Логіка:
  1. Щодня бот знаходить активних учасників, у яких сьогодні день народження.
  2. Якщо є згода на публічне привітання, бот надсилає тренеру/адміну/власнику текст на модерацію.
  3. Модератор тисне кнопку, і бот публікує привітання в канал батьків.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import List, Tuple

from app.access import Role
from app.models import Member
from app.repositories.base import IMemberRepository, IUserRoleRepository
from app.services.notifications import NotificationService
from app.services.templates import TemplateService
from app import keyboards as kb

log = logging.getLogger(__name__)


class BirthdayService:
    def __init__(
        self,
        members: IMemberRepository,
        users: IUserRoleRepository,
        notifications: NotificationService,
        templates: TemplateService,
        owner_chat_id: int,
        parents_channel_id: str = "",
    ) -> None:
        self._members = members
        self._users = users
        self._notifications = notifications
        self._templates = templates
        self._owner_chat_id = owner_chat_id
        self._parents_channel_id = parents_channel_id

    def todays_birthdays(self, today: date | None = None) -> List[Member]:
        today = today or date.today()
        result: List[Member] = []
        for member in self._members.get_active():
            if not member.birth_date:
                continue
            if member.birth_date.month == today.month and member.birth_date.day == today.day:
                if member.birthday_last_greeted_year == today.year:
                    continue
                result.append(member)
        return result

    def upcoming_birthdays(
        self,
        days: int = 14,
        today: date | None = None,
    ) -> List[Tuple[Member, date, int]]:
        today = today or date.today()
        horizon = max(0, days)
        result: List[Tuple[Member, date, int]] = []

        for member in self._members.get_active():
            if not member.birth_date:
                continue
            next_date = _next_birthday_date(member.birth_date, today)
            days_until = (next_date - today).days
            if 0 <= days_until <= horizon:
                result.append((member, next_date, days_until))

        return sorted(result, key=lambda item: (item[2], item[0].full_name))

    def coverage_stats(self) -> dict:
        members = self._members.get_active()
        with_birth_date = [m for m in members if m.birth_date]
        enabled = [m for m in with_birth_date if m.birthday_greeting_enabled]
        missing_birth = [m for m in members if not m.birth_date]
        disabled = [m for m in with_birth_date if not m.birthday_greeting_enabled]
        return {
            "total": len(members),
            "with_birth_date": len(with_birth_date),
            "enabled": len(enabled),
            "missing_birth": missing_birth,
            "disabled": disabled,
        }

    def send_moderation_requests(self, today: date | None = None) -> int:
        today = today or date.today()
        sent = 0
        moderators = self._moderator_chat_ids()
        for member in self.todays_birthdays(today):
            if not member.birthday_greeting_enabled:
                continue
            text = self.preview_text(member)
            moderation_text = (
                "🎂 <b>Привітання з днем народження на модерацію</b>\n\n"
                f"{text}\n\n"
                "Натисніть кнопку, якщо цей текст можна опублікувати в канал батьків."
            )
            for chat_id in moderators:
                ok = self._notifications.send(
                    chat_id,
                    moderation_text,
                    reply_markup=kb.birthday_moderation_keyboard(member.member_id, today.year),
                )
                sent += 1 if ok else 0
        return sent

    def preview_text(self, member: Member) -> str:
        public_name = member.birthday_public_name or member.full_name
        return self._templates.render(
            "birthday_channel_post",
            public_name=public_name,
            club_name="Black Bear Dojo",
        )

    def publish_to_parents_channel(self, member_id: str, year: int) -> tuple[bool, str]:
        if not self._parents_channel_id:
            return False, "Не задано PARENTS_CHANNEL_ID / parents_channel_id у settings."
        member = self._members.get_by_id(member_id)
        if not member:
            return False, "Учасника не знайдено."
        text = self.preview_text(member)
        chat_id = int(self._parents_channel_id) if str(self._parents_channel_id).lstrip("-").isdigit() else self._parents_channel_id
        ok = self._notifications.send(chat_id, text)
        if ok:
            member.birthday_last_greeted_year = year
            self._members.upsert(member)
            return True, "Опубліковано в канал батьків."
        return False, "Telegram не прийняв повідомлення в канал."

    def _moderator_chat_ids(self) -> List[int]:
        ids: List[int] = []
        try:
            for user in self._users.get_all():
                if user.active and user.role in (Role.COACH, Role.ADMIN, Role.OWNER):
                    ids.append(user.telegram_id)
        except Exception as e:
            log.warning("Не вдалося отримати модераторів ДН: %s", e)
        if self._owner_chat_id and self._owner_chat_id not in ids:
            ids.append(self._owner_chat_id)
        return ids


def _birthday_date_for_year(birth_date: date, year: int) -> date:
    try:
        return date(year, birth_date.month, birth_date.day)
    except ValueError:
        # 29.02 вітаємо 1.03 у не високосний рік.
        return date(year, 3, 1)


def _next_birthday_date(birth_date: date, today: date) -> date:
    next_date = _birthday_date_for_year(birth_date, today.year)
    if next_date < today:
        next_date = _birthday_date_for_year(birth_date, today.year + 1)
    return next_date
