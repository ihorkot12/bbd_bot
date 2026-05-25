"""
access.py — перевірка ролей і дозволів.

Рольова ієрархія (від нижчого до вищого):
  guest < lead < parent < coach < admin < owner

Кожна роль включає всі дозволи нижчих ролей.
"""
from __future__ import annotations

from functools import wraps
from typing import Callable, Optional, Set

import telebot

from app.models import Role


# ── Ієрархія ролей ────────────────────────────────────────────────────────────

_ROLE_LEVEL: dict[Role, int] = {
    Role.GUEST: 0,
    Role.LEAD: 1,
    Role.PARENT: 2,
    Role.COACH: 3,
    Role.ADMIN: 4,
    Role.OWNER: 5,
}


def role_level(role: Role) -> int:
    return _ROLE_LEVEL.get(role, -1)


def has_min_role(user_role: Role, required: Role) -> bool:
    """Повертає True, якщо user_role >= required у ієрархії."""
    return role_level(user_role) >= role_level(required)


# ── Дозволи по дії ────────────────────────────────────────────────────────────

_PERMISSIONS: dict[str, Role] = {
    # Платежі
    "view_payments": Role.COACH,
    "edit_payments": Role.ADMIN,
    "send_payment_reminder": Role.ADMIN,
    "view_own_payment": Role.PARENT,

    # Відвідуваність
    "mark_attendance": Role.COACH,
    "view_attendance": Role.COACH,
    "view_own_child_attendance": Role.PARENT,

    # Учні
    "view_members": Role.COACH,
    "edit_members": Role.ADMIN,
    "add_member": Role.ADMIN,

    # Ліди / проб'ні
    "create_lead": Role.GUEST,
    "view_leads": Role.COACH,
    "manage_leads": Role.ADMIN,
    "convert_lead": Role.ADMIN,

    # Події
    "view_events": Role.PARENT,
    "create_event": Role.ADMIN,
    "announce_event": Role.ADMIN,

    # Шаблони
    "view_templates": Role.COACH,
    "edit_templates": Role.ADMIN,

    # Дайджест
    "view_digest": Role.OWNER,

    # Завдання
    "view_tasks": Role.COACH,
    "manage_tasks": Role.ADMIN,

    # Налаштування
    "edit_settings": Role.OWNER,

    # Аудит
    "view_audit": Role.OWNER,
}


def can(user_role: Role, action: str) -> bool:
    """
    Перевіряє, чи має користувач з роллю user_role дозвіл на дію action.
    Якщо дія невідома — забороняємо за замовчуванням.
    """
    required = _PERMISSIONS.get(action)
    if required is None:
        return False
    return has_min_role(user_role, required)


# ── Реєстр ролей (простий in-memory кеш) ─────────────────────────────────────
# Реальний Registry делегує до репозиторію; цей клас зберігає кеш.

class RoleRegistry:
    """
    Кеш відповідності telegram_id → Role.
    Заповнюється при старті з Google Sheets; оновлюється при змінах.
    """

    def __init__(self) -> None:
        self._cache: dict[int, Role] = {}

    def set_role(self, telegram_id: int, role: Role) -> None:
        self._cache[telegram_id] = role

    def get_role(self, telegram_id: int) -> Role:
        return self._cache.get(telegram_id, Role.GUEST)

    def load_from_list(self, user_roles: list) -> None:
        """Завантажує список UserRole у кеш."""
        for ur in user_roles:
            self._cache[ur.telegram_id] = ur.role

    def is_owner(self, telegram_id: int) -> bool:
        return self.get_role(telegram_id) == Role.OWNER

    def is_coach_or_above(self, telegram_id: int) -> bool:
        return has_min_role(self.get_role(telegram_id), Role.COACH)

    def is_admin_or_above(self, telegram_id: int) -> bool:
        return has_min_role(self.get_role(telegram_id), Role.ADMIN)


# Глобальний singleton реєстру
_registry: Optional[RoleRegistry] = None


def get_registry() -> RoleRegistry:
    global _registry
    if _registry is None:
        _registry = RoleRegistry()
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None


# ── Декоратори для хендлерів pyTelegramBotAPI ──────────────────────────────

def require_role(min_role: Role):
    """
    Декоратор для хендлерів pyTelegramBotAPI.
    Якщо роль нижча за вимогу — відповідає відмовою та не викликає хендлер.

    Приклад:
        @bot.message_handler(commands=["digest"])
        @require_role(Role.OWNER)
        def handle_digest(message):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(message_or_call, *args, **kwargs):
            if isinstance(message_or_call, telebot.types.Message):
                tg_id = message_or_call.from_user.id
                reply = lambda text: message_or_call.reply_text if hasattr(
                    message_or_call, "reply_text"
                ) else None
            elif isinstance(message_or_call, telebot.types.CallbackQuery):
                tg_id = message_or_call.from_user.id
            else:
                tg_id = 0

            user_role = get_registry().get_role(tg_id)
            if not has_min_role(user_role, min_role):
                # Намагаємося відповісти (якщо є bot в kwargs)
                bot = kwargs.get("bot")
                _deny(bot, message_or_call)
                return
            return func(message_or_call, *args, **kwargs)
        return wrapper
    return decorator


def _deny(bot, message_or_call) -> None:
    """Надсилає відповідь про відсутність доступу."""
    text = "⛔ У вас немає доступу до цієї функції."
    try:
        if bot is None:
            return
        if isinstance(message_or_call, telebot.types.Message):
            bot.reply_to(message_or_call, text)
        elif isinstance(message_or_call, telebot.types.CallbackQuery):
            bot.answer_callback_query(message_or_call.id, text, show_alert=True)
    except Exception:
        pass


# ── Допоміжні функції ─────────────────────────────────────────────────────────

def get_user_role(telegram_id: int) -> Role:
    """Повертає роль користувача з глобального реєстру."""
    return get_registry().get_role(telegram_id)


def user_can(telegram_id: int, action: str) -> bool:
    """Перевіряє дозвіл для telegram_id."""
    role = get_user_role(telegram_id)
    return can(role, action)
