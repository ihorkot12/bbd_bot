"""
keyboards.py — Ukrainian inline та reply keyboards для pyTelegramBotAPI.

Усі тексти кнопок — українською мовою.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any, List, Optional

from telebot import types


_ATTENDANCE_CALLBACK_TTL_SECONDS = 6 * 60 * 60
_ATTENDANCE_CALLBACKS: dict[str, tuple[float, tuple[Any, ...]]] = {}


def _cleanup_attendance_callbacks(now: float) -> None:
    expired = [
        token
        for token, (expires_at, _) in _ATTENDANCE_CALLBACKS.items()
        if expires_at <= now
    ]
    for token in expired:
        _ATTENDANCE_CALLBACKS.pop(token, None)


def register_attendance_callback(*payload: Any) -> str:
    now = time.time()
    _cleanup_attendance_callbacks(now)
    token = uuid.uuid4().hex[:12]
    _ATTENDANCE_CALLBACKS[token] = (
        now + _ATTENDANCE_CALLBACK_TTL_SECONDS,
        tuple(payload),
    )
    return token


def resolve_attendance_callback(token: str) -> tuple[Any, ...] | None:
    item = _ATTENDANCE_CALLBACKS.get(token)
    if not item:
        return None
    expires_at, payload = item
    if expires_at <= time.time():
        _ATTENDANCE_CALLBACKS.pop(token, None)
        return None
    return payload


def attendance_id_token(value: str) -> str:
    return hashlib.blake2s(str(value).encode("utf-8"), digest_size=5).hexdigest()


# ── Головні меню ──────────────────────────────────────────────────────────────

def main_menu_owner() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💰 Оплати", callback_data="menu:payments"),
        types.InlineKeyboardButton("📋 Відвідуваність", callback_data="menu:attendance"),
        types.InlineKeyboardButton("➕ Додати", callback_data="ops:menu"),
        types.InlineKeyboardButton("👥 Учні", callback_data="menu:members"),
        types.InlineKeyboardButton("🔍 Ліди / Проби", callback_data="menu:leads"),
        types.InlineKeyboardButton("📅 Події", callback_data="menu:events"),
        types.InlineKeyboardButton("🎂 Дні народження", callback_data="menu:birthdays"),
        types.InlineKeyboardButton("📊 Дайджест", callback_data="menu:digest"),
        types.InlineKeyboardButton("🧭 Інструкція", callback_data="menu:ownerhelp"),
        types.InlineKeyboardButton("✉️ Шаблони", callback_data="menu:templates"),
        types.InlineKeyboardButton("⚙️ Налаштування", callback_data="menu:settings"),
        types.InlineKeyboardButton("📥 Оновити форми", callback_data="menu:formsync"),
    )
    return kb


def main_menu_admin() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💰 Оплати", callback_data="menu:payments"),
        types.InlineKeyboardButton("📋 Відвідуваність", callback_data="menu:attendance"),
        types.InlineKeyboardButton("➕ Додати", callback_data="ops:menu"),
        types.InlineKeyboardButton("👥 Учні", callback_data="menu:members"),
        types.InlineKeyboardButton("🔍 Ліди / Проби", callback_data="menu:leads"),
        types.InlineKeyboardButton("📅 Події", callback_data="menu:events"),
        types.InlineKeyboardButton("🎂 Дні народження", callback_data="menu:birthdays"),
        types.InlineKeyboardButton("🧭 Інструкція", callback_data="menu:ownerhelp"),
        types.InlineKeyboardButton("✉️ Шаблони", callback_data="menu:templates"),
        types.InlineKeyboardButton("📥 Оновити форми", callback_data="menu:formsync"),
    )
    return kb


def main_menu_coach() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📋 Відвідуваність", callback_data="menu:attendance"),
        types.InlineKeyboardButton("➕ Додати", callback_data="ops:menu"),
        types.InlineKeyboardButton("👥 Мої учні", callback_data="menu:members"),
        types.InlineKeyboardButton("🔍 Ліди", callback_data="menu:leads"),
        types.InlineKeyboardButton("📅 Події", callback_data="menu:events"),
        types.InlineKeyboardButton("🎂 Привітання ДН", callback_data="menu:birthdays"),
    )
    return kb


def main_menu_parent() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💰 Моя оплата", callback_data="menu:my_payment"),
        types.InlineKeyboardButton("📋 Відвідуваність дитини", callback_data="menu:my_attendance"),
        types.InlineKeyboardButton("📅 Розклад / події", callback_data="menu:events"),
        types.InlineKeyboardButton("📞 Контакти", callback_data="menu:contact"),
    )
    return kb


def main_menu_guest() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🥋 Запис на пробне", callback_data="menu:trial_request"),
        types.InlineKeyboardButton("📋 Реєстрація учасника", callback_data="menu:registration"),
        types.InlineKeyboardButton("📅 Розклад", callback_data="menu:schedule"),
        types.InlineKeyboardButton("💰 Вартість", callback_data="menu:price"),
        types.InlineKeyboardButton("📍 Адреса", callback_data="menu:address"),
        types.InlineKeyboardButton("📞 Контакти", callback_data="menu:contact"),
    )
    return kb


# ── Оплати ────────────────────────────────────────────────────────────────────

def payments_menu() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📊 Статус оплат", callback_data="pay:status"),
        types.InlineKeyboardButton("⚠️ Боржники", callback_data="pay:debtors"),
        types.InlineKeyboardButton("🔔 Надіслати нагадування", callback_data="pay:remind"),
        types.InlineKeyboardButton("✏️ Змінити статус", callback_data="pay:edit"),
    )
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="menu:back"))
    return kb


def owner_operations_menu() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🧾 Анкета реєстрації учасника", callback_data="ops:register_member"),
        types.InlineKeyboardButton("➕ Додати учасника покроково", callback_data="ops:add_member"),
        types.InlineKeyboardButton("🥋 Додати / редагувати групу покроково", callback_data="ops:add_group"),
        types.InlineKeyboardButton("👥 Редагувати учасників кнопками", callback_data="ops:edit_members"),
        types.InlineKeyboardButton("💰 Оновити оплату учасника", callback_data="ops:set_payment"),
        types.InlineKeyboardButton("❄️ Заморозити абонемент (1 кнопка)", callback_data="ops:freeze_subscription"),
        types.InlineKeyboardButton("🧭 Інструкція власника", callback_data="menu:ownerhelp"),
        types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"),
    )
    return kb


def wizard_cancel_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("❌ Скасувати", callback_data="ops:cancel"),
        types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"),
    )
    return kb


def participant_type_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🧒 Дитина", callback_data="ops:ptype:child"),
        types.InlineKeyboardButton("👤 Дорослий", callback_data="ops:ptype:adult"),
    )
    kb.add(types.InlineKeyboardButton("❌ Скасувати", callback_data="ops:cancel"))
    return kb


def yes_no_keyboard(prefix: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Так", callback_data=f"{prefix}:yes"),
        types.InlineKeyboardButton("❌ Ні", callback_data=f"{prefix}:no"),
    )
    kb.add(types.InlineKeyboardButton("❌ Скасувати", callback_data="ops:cancel"))
    return kb


def member_list_keyboard(members: List, prefix: str = "ops:member") -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    for member in members[:30]:
        kb.add(types.InlineKeyboardButton(
            f"{member.full_name} ({member.member_id})",
            callback_data=f"{prefix}:{member.member_id}"
        ))
    kb.add(types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"))
    return kb


def member_edit_keyboard(member_id: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🥋 Змінити групу", callback_data=f"ops:edit_member:{member_id}:group"),
        types.InlineKeyboardButton("📞 Змінити телефон", callback_data=f"ops:edit_member:{member_id}:phone"),
        types.InlineKeyboardButton("🎂 Перемкнути привітання ДН", callback_data=f"ops:edit_member:{member_id}:birthday"),
        types.InlineKeyboardButton("🚫 Активний / Неактивний", callback_data=f"ops:edit_member:{member_id}:active"),
        types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"),
    )
    return kb


def payment_status_keyboard(member_id: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    statuses = [
        ("✅ Сплачено", "paid"),
        ("💛 Частково", "partial"),
        ("❌ Не сплачено", "unpaid"),
        ("🤝 Обіцяно", "promised"),
        ("🔴 Прострочено", "overdue"),
        ("❄️ Заморожено", "frozen"),
    ]
    for label, status in statuses:
        kb.add(types.InlineKeyboardButton(
            label, callback_data=f"pay:set_status:{member_id}:{status}"
        ))
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="pay:status"))
    kb.add(types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"))
    return kb


# ── Відвідуваність ────────────────────────────────────────────────────────────

def attendance_menu() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📌 Сьогодні", callback_data="att:today"),
        types.InlineKeyboardButton("📝 Відмітити присутність", callback_data="att:mark"),
        types.InlineKeyboardButton("📊 Переглянути журнал", callback_data="att:view"),
        types.InlineKeyboardButton("📞 2+ пропуски", callback_data="att:followups"),
        types.InlineKeyboardButton("⚠️ Незакриті журнали", callback_data="att:unclosed"),
        types.InlineKeyboardButton("😴 Неактивні учні", callback_data="att:inactive"),
    )
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="menu:back"))
    return kb


def attendance_today_keyboard(items: List[dict], lesson_date: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    for item in items[:30]:
        time_part = f"{item.get('time')} · " if item.get("time") else ""
        label = f"📝 {time_part}{item['name']}"
        kb.add(
            types.InlineKeyboardButton(
                label,
                callback_data=(
                    f"att:dg:mark:{attendance_id_token(item['group_id'])}:{lesson_date}"
                ),
            )
        )
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="menu:attendance"))
    kb.add(types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"))
    return kb


def attendance_groups_keyboard(groups: List, mode: str,
                               lesson_date: str) -> types.InlineKeyboardMarkup:
    """
    Клавіатура вибору групи для журналу.
    mode: "mark" або "view"
    lesson_date: YYYY-MM-DD
    """
    kb = types.InlineKeyboardMarkup(row_width=1)
    for group in groups[:30]:
        label = f"🥋 {group.name}"
        kb.add(
            types.InlineKeyboardButton(
                label,
                callback_data=f"att:dg:{mode}:{attendance_id_token(group.group_id)}:{lesson_date}",
            )
        )
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="menu:attendance"))
    kb.add(types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"))
    return kb


def mark_attendance_keyboard(group_id: str, lesson_date: str,
                              members: List[dict],
                              undo_token: Optional[str] = None) -> types.InlineKeyboardMarkup:
    """
    Динамічна клавіатура для позначення кожного учня.
    members: список dict з ключами member_id, full_name, status (або None).
    """
    group_token = attendance_id_token(group_id)
    unmarked_count = sum(1 for m in members if not m.get("status"))

    kb = types.InlineKeyboardMarkup(row_width=2)
    if undo_token:
        kb.add(
            types.InlineKeyboardButton(
                "↩️ Скасувати останню дію",
                callback_data=f"att:du:{undo_token}",
            )
        )
    if unmarked_count:
        kb.add(
            types.InlineKeyboardButton(
                f"✅ Порожні = присутні ({unmarked_count})",
                callback_data=f"att:db:present:{group_token}:{lesson_date}",
            ),
            types.InlineKeyboardButton(
                f"❌ Порожні = відсутні ({unmarked_count})",
                callback_data=f"att:db:absent:{group_token}:{lesson_date}",
            ),
        )
        kb.add(
            types.InlineKeyboardButton(
                f"📋 Порожні = поважна ({unmarked_count})",
                callback_data=f"att:db:excused:{group_token}:{lesson_date}",
            )
        )
    kb.add(
        types.InlineKeyboardButton(
            "🔄 Оновити",
            callback_data=f"att:dg:mark:{group_token}:{lesson_date}",
        )
    )
    for m in members:
        mid = m["member_id"]
        name = m["full_name"]
        status = m.get("status")
        if status == "present":
            icon = "✅"
        elif status == "absent":
            icon = "❌"
        else:
            icon = "⬜"
        if status == "excused":
            icon = "📋"
        if status == "present" and str(m.get("notes") or "").strip().lower() == "late":
            icon = "⏱"
        member_token = attendance_id_token(mid)
        kb.row(
            types.InlineKeyboardButton(
                f"{icon} {name}",
                callback_data=f"att:dt:{group_token}:{lesson_date}:{member_token}",
            ),
            types.InlineKeyboardButton(
                "✏️",
                callback_data=f"att:de:{group_token}:{lesson_date}:{member_token}",
            ),
        )
    if unmarked_count:
        kb.add(types.InlineKeyboardButton(
            f"⚠️ Не відмічено: {unmarked_count}",
            callback_data=f"att:dg:mark:{group_token}:{lesson_date}",
        ))
    kb.add(
        types.InlineKeyboardButton(
            "💾 Зберегти і закрити",
            callback_data=f"att:dc:{group_token}:{lesson_date}"
        )
    )
    kb.add(types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"))
    return kb


def attendance_status_keyboard(group_id: str, lesson_date: str,
                                member_id: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton(
            "✅ Присутній",
            callback_data=f"att:ds:present:{attendance_id_token(group_id)}:{lesson_date}:{attendance_id_token(member_id)}"
        ),
        types.InlineKeyboardButton(
            "❌ Відсутній",
            callback_data=f"att:ds:absent:{attendance_id_token(group_id)}:{lesson_date}:{attendance_id_token(member_id)}"
        ),
        types.InlineKeyboardButton(
            "⏱ Запізнився",
            callback_data=f"att:ds:late:{attendance_id_token(group_id)}:{lesson_date}:{attendance_id_token(member_id)}"
        ),
        types.InlineKeyboardButton(
            "📋 Поважна",
            callback_data=f"att:ds:excused:{attendance_id_token(group_id)}:{lesson_date}:{attendance_id_token(member_id)}"
        ),
    )
    kb.add(
        types.InlineKeyboardButton(
            "⬜ Очистити",
            callback_data=f"att:ds:clear:{attendance_id_token(group_id)}:{lesson_date}:{attendance_id_token(member_id)}",
        )
    )
    kb.add(
        types.InlineKeyboardButton(
            "◀️ Назад до журналу",
            callback_data=f"att:dg:mark:{attendance_id_token(group_id)}:{lesson_date}",
        )
    )
    return kb


# ── Ліди / Проби ──────────────────────────────────────────────────────────────

def attendance_closed_keyboard(group_id: str, lesson_date: str) -> types.InlineKeyboardMarkup:
    group_token = attendance_id_token(group_id)
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "✏️ Редагувати журнал",
            callback_data=f"att:dg:mark:{group_token}:{lesson_date}",
        ),
        types.InlineKeyboardButton(
            "📊 Переглянути журнал",
            callback_data=f"att:dg:view:{group_token}:{lesson_date}",
        ),
        types.InlineKeyboardButton("⬅️ Назад", callback_data="menu:attendance"),
        types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"),
    )
    return kb


def leads_menu() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📋 Список лідів", callback_data="lead:list"),
        types.InlineKeyboardButton("➕ Новий лід", callback_data="lead:new"),
        types.InlineKeyboardButton("📅 Проби сьогодні", callback_data="lead:trials_today"),
        types.InlineKeyboardButton("🔔 Надіслати нагадування", callback_data="lead:remind"),
    )
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="menu:back"))
    return kb


def after_trial_keyboard(lead_id: str) -> types.InlineKeyboardMarkup:
    """Кнопки для власника/тренера після пробного тренування."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(
            "✅ Був присутній", callback_data=f"lead:trial_present:{lead_id}"
        ),
        types.InlineKeyboardButton(
            "❌ Не прийшов", callback_data=f"lead:trial_absent:{lead_id}"
        ),
        types.InlineKeyboardButton(
            "📅 Перенести", callback_data=f"lead:reschedule:{lead_id}"
        ),
        types.InlineKeyboardButton(
            "🎉 Зарахувати до клубу", callback_data=f"lead:convert:{lead_id}"
        ),
    )
    kb.add(
        types.InlineKeyboardButton(
            "↩️ Скасувати останнє рішення", callback_data=f"lead:undo:{lead_id}"
        ),
    )
    kb.add(types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"))
    return kb


def confirm_convert_keyboard(lead_id: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Підтвердити", callback_data=f"lead:confirm_convert:{lead_id}"),
        types.InlineKeyboardButton("❌ Скасувати", callback_data=f"lead:list"),
    )
    kb.add(types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"))
    return kb


def trial_reschedule_keyboard(lead_id: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📅 +1 день", callback_data=f"lead:reschedule_pick:{lead_id}:1"),
        types.InlineKeyboardButton("📅 +2 дні", callback_data=f"lead:reschedule_pick:{lead_id}:2"),
        types.InlineKeyboardButton("📅 +7 днів", callback_data=f"lead:reschedule_pick:{lead_id}:7"),
    )
    kb.add(types.InlineKeyboardButton("◀️ Назад до лідів", callback_data="menu:leads"))
    kb.add(types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"))
    return kb


# ── Події ─────────────────────────────────────────────────────────────────────

def events_menu() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📋 Список подій", callback_data="evt:list"),
        types.InlineKeyboardButton("➕ Нова подія", callback_data="evt:new"),
        types.InlineKeyboardButton("📢 Оголошення", callback_data="evt:announce"),
        types.InlineKeyboardButton("🔔 Нагадування", callback_data="evt:remind"),
    )
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="menu:back"))
    return kb


def event_audience_keyboard(event_id: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("👥 Всім учасникам", callback_data=f"evt:audience:all:{event_id}"),
        types.InlineKeyboardButton("👨‍👩‍👧 Батькам", callback_data=f"evt:audience:parents:{event_id}"),
        types.InlineKeyboardButton("🥋 Тренерам", callback_data=f"evt:audience:coaches:{event_id}"),
    )
    kb.add(types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"))
    return kb


# ── Підтвердження ─────────────────────────────────────────────────────────────

def confirm_keyboard(yes_data: str, no_data: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Так", callback_data=yes_data),
        types.InlineKeyboardButton("❌ Ні", callback_data=no_data),
    )
    return kb


# ── Навігація ────────────────────────────────────────────────────────────────

def back_button(callback: str = "menu:back") -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data=callback))
    kb.add(types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"))
    return kb


def forms_menu(registration_url: str, trial_url: str) -> types.InlineKeyboardMarkup:
    """Дві окремі форми: повна реєстрація і швидкий запис на пробне."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🥋 Запис на пробне тренування", url=trial_url),
        types.InlineKeyboardButton("📋 Повна реєстрація учасника", url=registration_url),
        types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"),
    )
    return kb


def coach_morning_card_keyboard(groups: List[dict], lesson_date: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    for item in groups:
        label = f"📝 Відмітити: {item['name']} ({item['time']})"
        kb.add(
            types.InlineKeyboardButton(
                label,
                callback_data=f"att:dg:mark:{attendance_id_token(item['group_id'])}:{lesson_date}",
            )
        )
    kb.add(types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"))
    return kb


def birthday_moderation_keyboard(member_id: str, year: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("✅ Опублікувати в канал батьків", callback_data=f"bd:publish:{member_id}:{year}"),
        types.InlineKeyboardButton("✏️ Не публікувати / вручну змінити", callback_data=f"bd:skip:{member_id}:{year}"),
        types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"),
    )
    return kb


def pagination_keyboard(page: int, total_pages: int,
                         prefix: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    if page > 0:
        buttons.append(types.InlineKeyboardButton(
            "◀️", callback_data=f"{prefix}:page:{page - 1}"
        ))
    buttons.append(types.InlineKeyboardButton(
        f"{page + 1}/{total_pages}", callback_data="noop"
    ))
    if page < total_pages - 1:
        buttons.append(types.InlineKeyboardButton(
            "▶️", callback_data=f"{prefix}:page:{page + 1}"
        ))
    kb.add(*buttons)
    kb.add(types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"))
    return kb


# ── Reply keyboards (постійні) ─────────────────────────────────────────────────

def request_contact_keyboard() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(types.KeyboardButton("📱 Поділитися контактом", request_contact=True))
    kb.add(types.KeyboardButton("❌ Скасувати"))
    return kb


def remove_keyboard() -> types.ReplyKeyboardRemove:
    return types.ReplyKeyboardRemove()


# ── Шаблони ───────────────────────────────────────────────────────────────────

def templates_menu() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📋 Список шаблонів", callback_data="tmpl:list"),
        types.InlineKeyboardButton("✏️ Редагувати", callback_data="tmpl:edit"),
        types.InlineKeyboardButton("🔄 Скинути до дефолтів", callback_data="tmpl:reset"),
    )
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="menu:back"))
    return kb


# ── Налаштування ──────────────────────────────────────────────────────────────

def settings_menu() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("📅 Дні нагадувань про оплату", callback_data="set:pay_days"),
        types.InlineKeyboardButton("⏰ Час нагадування тренеру", callback_data="set:att_time"),
        types.InlineKeyboardButton("⏰ Дедлайн журналу", callback_data="set:att_deadline"),
        types.InlineKeyboardButton("📊 Час дайджесту", callback_data="set:digest_time"),
    )
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="menu:back"))
    return kb
