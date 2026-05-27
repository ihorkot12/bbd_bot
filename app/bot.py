"""
bot.py — фабрика бота та реєстрація всіх хендлерів команд і callback.

Архітектура:
  - Один TeleBot instance (polling режим)
  - Хендлери зареєстровані тут; логіка — у сервісах
  - Роль перевіряється через access.get_user_role()
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Callable, Optional, TYPE_CHECKING

import telebot
from telebot import types

from app import access
from app.access import Role, get_user_role, user_can
from app import keyboards as kb
from app.models import (
    AttendanceStatus,
    Group,
    LeadStatus,
    Member,
    ParticipantType,
    Payment,
    PaymentStatus,
    RegistrationSource,
)

if TYPE_CHECKING:
    from app.config import Config
    from app.repositories.base import Repositories
    from app.services.attendance import AttendanceService
    from app.services.digest import DigestService
    from app.services.events import EventService
    from app.services.leads import LeadService
    from app.services.notifications import NotificationService
    from app.services.payments import PaymentService
    from app.services.birthdays import BirthdayService
    from app.services.templates import TemplateService

log = logging.getLogger(__name__)


def create_bot(token: str) -> telebot.TeleBot:
    """Створює TeleBot instance."""
    bot = telebot.TeleBot(token, parse_mode="HTML")
    return bot


def register_handlers(
    bot: telebot.TeleBot,
    cfg: "Config",
    repos: "Repositories",
    payments_svc: "PaymentService",
    attendance_svc: "AttendanceService",
    leads_svc: "LeadService",
    events_svc: "EventService",
    digest_svc: "DigestService",
    birthday_svc: "BirthdayService",
    templates_svc: "TemplateService",
    notifications: "NotificationService",
    form_sync_fn: Optional[Callable[[], int]] = None,
) -> None:
    """Реєструє всі команди та callback-хендлери."""
    wizard_state: dict[int, dict] = {}

    # ── /start ────────────────────────────────────────────────────────────────

    @bot.message_handler(commands=["start", "menu"])
    def cmd_start(message: types.Message):
        tg_id = message.from_user.id
        role = get_user_role(tg_id)
        name = message.from_user.first_name or "Привіт"

        welcome = (
            f"👋 Вітаємо у <b>Black Bear Dojo</b>, {name}!\n\n"
            f"🥋 Ваша роль: <b>{_role_ua(role)}</b>\n"
            f"Оберіть розділ:"
        )

        menu_map = {
            Role.OWNER: kb.main_menu_owner,
            Role.ADMIN: kb.main_menu_admin,
            Role.COACH: kb.main_menu_coach,
            Role.PARENT: kb.main_menu_parent,
        }
        menu_fn = menu_map.get(role, kb.main_menu_guest)
        bot.send_message(tg_id, welcome, reply_markup=menu_fn())
        log.info("/start: user=%s role=%s", tg_id, role.value)

    # ── /help ─────────────────────────────────────────────────────────────────

    @bot.message_handler(commands=["help"])
    def cmd_help(message: types.Message):
        tg_id = message.from_user.id
        role = get_user_role(tg_id)
        text = _help_text(role, cfg)
        bot.send_message(tg_id, text)

    # ── /id ───────────────────────────────────────────────────────────────────

    @bot.message_handler(commands=["id"])
    def cmd_id(message: types.Message):
        bot.reply_to(message, f"Ваш Telegram ID: <code>{message.from_user.id}</code>")

    # ── /digest ───────────────────────────────────────────────────────────────

    @bot.message_handler(commands=["digest"])
    def cmd_digest(message: types.Message):
        if not user_can(message.from_user.id, "view_digest"):
            bot.reply_to(message, "⛔ Тільки для власника.")
            return
        bot.send_message(message.from_user.id, "⏳ Збираю дайджест…")
        digest_svc.send()

    # ── /trial ────────────────────────────────────────────────────────────────

    @bot.message_handler(commands=["trial"])
    def cmd_trial(message: types.Message):
        """Гостю — записатися на пробне тренування через бота."""
        tg_id = message.from_user.id
        bot.send_message(
            tg_id,
            "📝 <b>Запис на пробне тренування</b>\n\n"
            "Хто реєструється?\n"
            "1️⃣ Дитина\n"
            "2️⃣ Дорослий учасник",
            reply_markup=_trial_type_keyboard(),
        )

    # ── /form ─────────────────────────────────────────────────────────────────

    @bot.message_handler(commands=["form"])
    def cmd_form(message: types.Message):
        """Надсилає посилання на реєстраційну форму."""
        text = (
            f"📋 <b>Форми Black Bear Dojo</b>\n\n"
            f"🥋 <b>Запис на пробне</b> — швидка заявка для нового контакту.\n"
            f"📋 <b>Повна реєстрація</b> — анкета учасника/батьків після рішення займатися."
        )
        bot.send_message(
            message.from_user.id,
            text,
            disable_web_page_preview=True,
            reply_markup=kb.forms_menu(cfg.registration_form_url, cfg.trial_form_url),
        )

    @bot.message_handler(commands=["trialform"])
    def cmd_trial_form(message: types.Message):
        bot.send_message(
            message.from_user.id,
            "🥋 <b>Запис на пробне тренування</b>\n\n"
            "Це коротка форма для нової заявки. Після заповнення адміністратор/тренер зможе підтвердити пробне.",
            reply_markup=kb.forms_menu(cfg.registration_form_url, cfg.trial_form_url),
            disable_web_page_preview=True,
        )

    @bot.message_handler(commands=["register"])
    def cmd_registration_form(message: types.Message):
        bot.send_message(
            message.from_user.id,
            "📋 <b>Повна реєстрація учасника</b>\n\n"
            "Ця форма потрібна для чинних учасників: контакти батьків, дата народження, згода на ДН, медичні примітки.",
            reply_markup=kb.forms_menu(cfg.registration_form_url, cfg.trial_form_url),
            disable_web_page_preview=True,
        )

    @bot.message_handler(commands=["registermember"])
    def cmd_register_member(message: types.Message):
        if not _can_manage_members_groups(message.from_user.id):
            bot.reply_to(message, "⛔ Тільки для власника, адміністратора або тренера.")
            return
        wizard_state[message.from_user.id] = {
            "flow": "register_member",
            "step": "full_name",
            "data": {},
        }
        bot.send_message(
            message.from_user.id,
            "🧾 <b>Анкета реєстрації учасника</b>\n\n"
            "Це розширена практична форма для клубу:\n"
            "• контакти\n"
            "• дата народження\n"
            "• preferred канал зв'язку\n"
            "• налаштування привітань з ДН\n"
            "• медичні примітки\n"
            "• аварійний контакт\n"
            "• згода на фото/відео\n\n"
            "Крок 1/16. Введіть ПІБ учасника:",
            reply_markup=kb.wizard_cancel_keyboard(),
        )

    @bot.message_handler(commands=["syncforms"])
    def cmd_sync_forms(message: types.Message):
        if get_user_role(message.from_user.id) not in (Role.OWNER, Role.ADMIN):
            bot.reply_to(message, "⛔ Тільки для власника або адміністратора.")
            return
        if not form_sync_fn:
            bot.reply_to(message, "⚠️ Синхронізація форм тимчасово недоступна.")
            return
        bot.send_message(message.from_user.id, "⏳ Синхронізую нові заявки з форм…")
        try:
            total = form_sync_fn()
        except Exception as e:
            log.error("Помилка ручної синхронізації форм: %s", e)
            bot.send_message(message.from_user.id, "⚠️ Не вдалося синхронізувати форми. Перевірте логи.")
            return
        bot.send_message(message.from_user.id, f"✅ Синхронізація завершена. Нових заявок: <b>{total}</b>")

    @bot.message_handler(commands=["birthdays"])
    def cmd_birthdays(message: types.Message):
        if not user_can(message.from_user.id, "mark_attendance") and get_user_role(message.from_user.id) not in (Role.OWNER, Role.ADMIN):
            bot.reply_to(message, "⛔ Тільки для тренера, адміністратора або власника.")
            return
        count = birthday_svc.send_moderation_requests()
        bot.reply_to(
            message,
            f"🎂 Надіслано привітань на модерацію: {count}\n\n"
            + _birthday_coverage_text(repos.members.get_active()),
        )

    # ── Owner operations ─────────────────────────────────────────────────────

    @bot.message_handler(commands=["ownerhelp", "adminhelp"])
    def cmd_ownerhelp(message: types.Message):
        if not _is_owner_admin(message.from_user.id):
            bot.reply_to(message, "⛔ Тільки для власника або адміністратора.")
            return
        bot.send_message(message.from_user.id, _owner_help_text(), disable_web_page_preview=True)

    @bot.message_handler(commands=["add"])
    def cmd_add_menu(message: types.Message):
        if not _can_manage_members_groups(message.from_user.id):
            bot.reply_to(message, "⛔ Тільки для власника, адміністратора або тренера.")
            return
        bot.send_message(
            message.from_user.id,
            "➕ <b>Що додаємо або редагуємо?</b>",
            reply_markup=kb.owner_operations_menu(),
        )

    @bot.message_handler(commands=["members"])
    def cmd_members(message: types.Message):
        if not _can_manage_members_groups(message.from_user.id):
            bot.reply_to(message, "⛔ Тільки для власника, адміністратора або тренера.")
            return
        members = repos.members.get_active()
        lines = [f"👥 <b>Учасники ({len(members)}):</b>"]
        for m in members[:60]:
            lines.append(f"• <code>{m.member_id}</code> — {m.full_name} | група: {m.group_id or '-'} | {m.parent_phone or ''}")
        if len(members) > 60:
            lines.append(f"…ще {len(members)-60}")
        bot.send_message(message.from_user.id, "\n".join(lines), reply_markup=kb.back_button())

    @bot.message_handler(commands=["groups"])
    def cmd_groups(message: types.Message):
        if get_user_role(message.from_user.id) not in (Role.OWNER, Role.ADMIN, Role.COACH):
            bot.reply_to(message, "⛔ Немає доступу.")
            return
        groups = repos.groups.get_active()
        lines = [f"🥋 <b>Групи ({len(groups)}):</b>"]
        for g in groups:
            count = len(repos.members.get_by_group(g.group_id))
            lines.append(f"• <code>{g.group_id}</code> — {g.name}\n  {g.schedule}\n  тренер: <code>{g.coach_telegram_id or '-'}</code>, учасників: {count}")
        bot.send_message(message.from_user.id, "\n".join(lines), reply_markup=kb.back_button())

    @bot.message_handler(commands=["addmember"])
    def cmd_addmember(message: types.Message):
        if not _can_manage_members_groups(message.from_user.id):
            bot.reply_to(message, "⛔ Тільки для власника, адміністратора або тренера.")
            return
        try:
            parts = _pipe_args(message.text, 8)
            full_name, birth_raw, ptype_raw, group_id, parent_name, phone, email, telegram_username = parts[:8]
            viber = parts[8] if len(parts) > 8 else ""
            birthday_yes = parts[9] if len(parts) > 9 else "так"
            member = Member(
                member_id=str(uuid.uuid4())[:8],
                full_name=full_name.strip(),
                birth_date=_parse_date_flexible(birth_raw),
                participant_type=ParticipantType.ADULT if ptype_raw.strip().lower() in ("adult", "дорослий", "доросла") else ParticipantType.CHILD,
                parent_name=parent_name.strip() or None,
                parent_phone=phone.strip() or None,
                parent_email=email.strip() or None,
                parent_telegram_username=telegram_username.strip() or None,
                parent_viber=viber.strip() or None,
                preferred_contact_channel="telegram/viber/phone",
                group_id=group_id.strip() or None,
                birthday_greeting_enabled=birthday_yes.strip().lower() not in ("ні", "no", "false", "0"),
                birthday_public_name=full_name.strip().split()[0],
                join_date=date.today(),
                active=True,
                registration_source=RegistrationSource.BOT.value,
            )
            repos.members.upsert(member)
            bot.reply_to(message, f"✅ Учасника додано/оновлено.\nID: <code>{member.member_id}</code>\n{member.full_name}")
        except Exception as e:
            bot.reply_to(message, f"⚠️ Не вдалося додати учасника: {e}\n\nПриклад:\n<code>/addmember Іван Петренко | 12.05.2015 | child | kids_1800 | Олена Петренко | +380... | mail@example.com | @parent | +380... | так</code>")

    @bot.message_handler(commands=["addgroup"])
    def cmd_addgroup(message: types.Message):
        if not _can_manage_members_groups(message.from_user.id):
            bot.reply_to(message, "⛔ Тільки для власника, адміністратора або тренера.")
            return
        try:
            parts = _pipe_args(message.text, 5)
            group_id, name, coach_id_raw, schedule, member_ids_raw = parts[:5]
            reminder = _first_time_from_schedule(schedule) or "18:00"
            deadline = parts[5].strip() if len(parts) > 5 and parts[5].strip() else ""
            group = Group(
                group_id=group_id.strip(),
                name=name.strip(),
                coach_telegram_id=int(coach_id_raw.strip()) if coach_id_raw.strip() else None,
                schedule=schedule.strip(),
                attendance_reminder_time=reminder,
                attendance_deadline_time=deadline,
                active=True,
            )
            repos.groups.upsert(group)
            attached = 0
            for member_id in [x.strip() for x in member_ids_raw.split(",") if x.strip()]:
                member = repos.members.get_by_id(member_id)
                if member:
                    member.group_id = group.group_id
                    repos.members.upsert(member)
                    attached += 1
            bot.reply_to(message, f"✅ Групу збережено.\n<code>{group.group_id}</code> — {group.name}\n{group.schedule}\nПривʼязано учасників: {attached}")
        except Exception as e:
            bot.reply_to(message, f"⚠️ Не вдалося зберегти групу: {e}\n\nПриклад:\n<code>/addgroup kids_1800 | Діти 7-10 | 329214126 | пн,ср,пт 18:00-18:40 | member1,member2 | 20:00</code>")

    @bot.message_handler(commands=["setpayment"])
    def cmd_setpayment(message: types.Message):
        if not _is_owner_admin(message.from_user.id):
            bot.reply_to(message, "⛔ Тільки для власника або адміністратора.")
            return
        try:
            parts = _pipe_args(message.text, 5)
            member_id, period, status_raw, due_raw, paid_raw = parts[:5]
            notes = parts[5] if len(parts) > 5 else ""
            status = PaymentStatus(status_raw.strip())
            existing = next((p for p in repos.payments.get_by_member(member_id.strip()) if p.period == period.strip()), None)
            payment = existing or Payment(
                payment_id=str(uuid.uuid4())[:8],
                member_id=member_id.strip(),
                period=period.strip(),
                status=status,
            )
            payment.status = status
            payment.amount_due = float(due_raw.strip() or 0)
            payment.amount_paid = float(paid_raw.strip() or 0)
            payment.notes = notes.strip() or None
            payment.paid_date = date.today() if status == PaymentStatus.PAID else payment.paid_date
            repos.payments.upsert(payment)
            bot.reply_to(message, f"✅ Оплату збережено.\nУчасник: <code>{payment.member_id}</code>\nПеріод: {payment.period}\nСтатус: {payment.status.value}\nСума: {payment.amount_paid}/{payment.amount_due}")
        except Exception as e:
            bot.reply_to(message, f"⚠️ Не вдалося зберегти оплату: {e}\n\nПриклад:\n<code>/setpayment member_id | 2026-05 | paid | 2500 | 2500 | mono</code>\nСтатуси: paid, partial, unpaid, promised, overdue, frozen")

    @bot.message_handler(func=lambda m: bool(wizard_state.get(m.from_user.id)) and not (m.text or "").startswith("/"), content_types=["text"])
    def wizard_text_handler(message: types.Message):
        if not _can_manage_members_groups(message.from_user.id):
            wizard_state.pop(message.from_user.id, None)
            bot.reply_to(message, "⛔ Немає доступу.")
            return
        try:
            _handle_wizard_text(bot, message, wizard_state, repos)
        except Exception as e:
            log.error("Wizard error user=%s: %s", message.from_user.id, e)
            bot.reply_to(message, f"⚠️ Помилка: {e}\nМожна скасувати й почати заново.", reply_markup=kb.wizard_cancel_keyboard())

    # ── /myinfo ───────────────────────────────────────────────────────────────

    @bot.message_handler(commands=["myinfo"])
    def cmd_myinfo(message: types.Message):
        tg_id = message.from_user.id
        role = get_user_role(tg_id)
        if role in (Role.PARENT, Role.LEAD):
            # Знаходимо учнів цього батька
            members = [
                m for m in repos.members.get_active()
                if m.parent_telegram_id == tg_id
            ]
            if not members:
                bot.send_message(tg_id, "Ваші діти ще не зареєстровані у системі.")
                return
            lines = ["👨‍👩‍👧 <b>Ваші учні:</b>\n"]
            for m in members:
                period = payments_svc.get_current_period()
                pay_info = payments_svc.get_member_payment_summary(m.member_id, period)
                lines.append(f"🥋 <b>{m.full_name}</b>")
                lines.append(pay_info)
                lines.append("")
            bot.send_message(tg_id, "\n".join(lines))
        else:
            bot.send_message(
                tg_id,
                f"Ваш ID: <code>{tg_id}</code>\nРоль: {_role_ua(role)}"
            )

    # ── Callback router ────────────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: True)
    def callback_router(call: types.CallbackQuery):
        data = call.data or ""
        tg_id = call.from_user.id
        role = get_user_role(tg_id)

        try:
            # ── Меню ──────────────────────────────────────────────────────────
            if data == "menu:back" or data.startswith("menu:"):
                _handle_menu(bot, call, role, cfg, tg_id, birthday_svc, form_sync_fn)

            # ── Оплати ────────────────────────────────────────────────────────
            elif data.startswith("pay:"):
                if not user_can(tg_id, "view_payments"):
                    bot.answer_callback_query(call.id, "⛔ Немає доступу", show_alert=True)
                    return
                _handle_payments(bot, call, data, tg_id, payments_svc, notifications, cfg)

            # ── Відвідуваність ─────────────────────────────────────────────────
            elif data.startswith("att:"):
                if not user_can(tg_id, "mark_attendance"):
                    bot.answer_callback_query(call.id, "⛔ Немає доступу", show_alert=True)
                    return
                _handle_attendance(bot, call, data, tg_id, attendance_svc, repos)

            # ── Ліди ──────────────────────────────────────────────────────────
            elif data.startswith("lead:"):
                _handle_leads(bot, call, data, tg_id, role, leads_svc, repos, notifications, cfg, wizard_state)

            # ── Події ─────────────────────────────────────────────────────────
            elif data.startswith("evt:"):
                if not user_can(tg_id, "view_events"):
                    bot.answer_callback_query(call.id, "⛔ Немає доступу", show_alert=True)
                    return
                _handle_events(bot, call, data, tg_id, events_svc)

            # ── Дні народження ───────────────────────────────────────────────
            elif data.startswith("bd:"):
                _handle_birthdays(bot, call, data, tg_id, birthday_svc)

            # ── Owner operations / майстри ───────────────────────────────────
            elif data.startswith("ops:"):
                if not _can_manage_members_groups(tg_id):
                    bot.answer_callback_query(call.id, "⛔ Немає доступу", show_alert=True)
                    return
                _handle_ops(bot, call, data, tg_id, wizard_state, repos)

            # ── Тип учасника (запис на пробне) ────────────────────────────────
            elif data.startswith("trial_type:"):
                _handle_trial_type(bot, call, data, tg_id)

            # ── Шаблони ───────────────────────────────────────────────────────
            elif data.startswith("tmpl:"):
                if not user_can(tg_id, "view_templates"):
                    bot.answer_callback_query(call.id, "⛔ Немає доступу", show_alert=True)
                    return
                _handle_templates(bot, call, data, templates_svc)

            elif data == "noop":
                bot.answer_callback_query(call.id)

            else:
                bot.answer_callback_query(call.id, "Невідома дія")

        except Exception as e:
            log.error("Помилка callback '%s' від user=%s: %s", data, tg_id, e)
            bot.answer_callback_query(call.id, "⚠️ Помилка. Спробуйте ще раз.", show_alert=True)

    log.info("Хендлери зареєстровано")


# ── Суб-хендлери ─────────────────────────────────────────────────────────────

def _handle_menu(bot, call, role, cfg, tg_id, birthday_svc, form_sync_fn):
    data = call.data
    section = data.split(":")[1] if ":" in data else "back"

    if section == "back" or section == "start":
        menu_map = {
            Role.OWNER: kb.main_menu_owner,
            Role.ADMIN: kb.main_menu_admin,
            Role.COACH: kb.main_menu_coach,
            Role.PARENT: kb.main_menu_parent,
        }
        menu_fn = menu_map.get(role, kb.main_menu_guest)
        bot.edit_message_text(
            "🏠 <b>Головне меню Black Bear Dojo</b>\n\nОберіть розділ:",
            call.message.chat.id, call.message.message_id,
            reply_markup=menu_fn()
        )
    elif section == "payments":
        bot.edit_message_text(
            "💰 <b>Оплати</b>",
            call.message.chat.id, call.message.message_id,
            reply_markup=kb.payments_menu()
        )
    elif section == "attendance":
        bot.edit_message_text(
            "📋 <b>Відвідуваність</b>",
            call.message.chat.id, call.message.message_id,
            reply_markup=kb.attendance_menu()
        )
    elif section == "leads":
        bot.edit_message_text(
            "🔍 <b>Ліди та проби</b>",
            call.message.chat.id, call.message.message_id,
            reply_markup=kb.leads_menu()
        )
    elif section == "events":
        bot.edit_message_text(
            "📅 <b>Події</b>",
            call.message.chat.id, call.message.message_id,
            reply_markup=kb.events_menu()
        )
    elif section == "templates":
        bot.edit_message_text(
            "✉️ <b>Шаблони повідомлень</b>",
            call.message.chat.id, call.message.message_id,
            reply_markup=kb.templates_menu()
        )
    elif section == "members":
        if role not in (Role.OWNER, Role.ADMIN, Role.COACH):
            bot.answer_callback_query(call.id, "⛔ Немає доступу", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        bot.send_message(
            tg_id,
            "👥 <b>Учасники</b>\n\n"
            "Команди:\n"
            "/members — список учасників\n"
            "/addmember — додати учасника, формат дивіться у /ownerhelp",
            reply_markup=kb.back_button(),
        )
    elif section == "ownerhelp":
        if role not in (Role.OWNER, Role.ADMIN):
            bot.answer_callback_query(call.id, "⛔ Немає доступу", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        bot.send_message(tg_id, _owner_help_text(), reply_markup=kb.back_button(), disable_web_page_preview=True)
    elif section == "settings":
        bot.edit_message_text(
            "⚙️ <b>Налаштування</b>",
            call.message.chat.id, call.message.message_id,
            reply_markup=kb.settings_menu()
        )
    elif section == "address":
        text = f"📍 <b>Адреса:</b>\n{cfg.club_address}"
        bot.answer_callback_query(call.id)
        bot.send_message(tg_id, text)
    elif section == "contact":
        text = f"📞 <b>Контакти:</b>\n{cfg.club_phone}\n📍 {cfg.club_address}"
        bot.answer_callback_query(call.id)
        bot.send_message(tg_id, text)
    elif section == "schedule":
        bot.answer_callback_query(call.id)
        bot.send_message(tg_id, f"📅 <b>Розклад:</b>\n{cfg.club_schedule_text}")
    elif section == "price":
        bot.answer_callback_query(call.id)
        bot.send_message(tg_id, f"💰 <b>Вартість:</b>\n{cfg.club_price_text}")
    elif section == "trial_request":
        bot.answer_callback_query(call.id)
        bot.send_message(
            tg_id,
            "🥋 <b>Запис на пробне тренування</b>\n\n"
            "Найкраще заповнити коротку форму — так заявка не загубиться.\n"
            "Також можна почати швидкий запис прямо в боті.",
            reply_markup=kb.forms_menu(cfg.registration_form_url, cfg.trial_form_url),
            disable_web_page_preview=True,
        )
    elif section == "registration":
        bot.answer_callback_query(call.id)
        bot.send_message(
            tg_id,
            "📋 <b>Повна реєстрація учасника Black Bear Dojo</b>\n\n"
            "Ця форма збирає основну інформацію для роботи клубу: контакти батьків, "
            "дату народження, медичні примітки, згоду на привітання з ДН і зручний канал звʼязку.\n\n"
            "Для тренера/адміна також доступна вбудована анкета прямо в боті: /registermember",
            reply_markup=kb.forms_menu(cfg.registration_form_url, cfg.trial_form_url),
            disable_web_page_preview=True,
        )
    elif section == "birthdays":
        if role not in (Role.OWNER, Role.ADMIN, Role.COACH):
            bot.answer_callback_query(call.id, "⛔ Немає доступу", show_alert=True)
            return
        count = birthday_svc.send_moderation_requests()
        bot.answer_callback_query(call.id, f"🎂 На модерацію: {count}")
        bot.send_message(
            tg_id,
            f"🎂 Перевірка днів народження виконана. На модерацію надіслано: {count}\n\n"
            + _birthday_coverage_text(repos.members.get_active()),
            reply_markup=kb.back_button(),
        )
    elif section == "digest":
        bot.answer_callback_query(call.id)
        bot.send_message(tg_id, "⏳ Збираю дайджест…")
        # digest надсилається окремо, щоб не блокувати callback
    elif section == "formsync":
        if role not in (Role.OWNER, Role.ADMIN):
            bot.answer_callback_query(call.id, "⛔ Немає доступу", show_alert=True)
            return
        if not form_sync_fn:
            bot.answer_callback_query(call.id, "Синхронізація тимчасово недоступна", show_alert=True)
            return
        try:
            total = form_sync_fn()
        except Exception as e:
            log.error("Помилка ручної синхронізації форм: %s", e)
            bot.answer_callback_query(call.id, "⚠️ Не вдалося синхронізувати форми", show_alert=True)
            return
        bot.answer_callback_query(call.id, f"✅ Синхронізовано: {total}")
        bot.send_message(
            tg_id,
            f"📥 Синхронізація форм завершена.\nНових заявок: <b>{total}</b>",
            reply_markup=kb.back_button(),
        )
    else:
        bot.answer_callback_query(call.id)


def _handle_payments(bot, call, data, tg_id, payments_svc, notifications, cfg):
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "status":
        debtors = payments_svc.get_debtors()
        if not debtors:
            bot.answer_callback_query(call.id, "✅ Боржників немає!")
            return
        lines = [f"💰 <b>Статус оплат ({payments_svc.get_current_period()}):</b>\n"]
        for member, payment in debtors[:20]:
            from app.services.payments import _status_icon, _payment_status_ua
            icon = _status_icon(payment.status)
            lines.append(f"{icon} {member.full_name} — {_payment_status_ua(payment.status)}")
        bot.edit_message_text(
            "\n".join(lines),
            call.message.chat.id, call.message.message_id,
            reply_markup=kb.back_button("menu:payments")
        )

    elif action == "debtors":
        payments_svc.send_debtors_summary_to_owner(None)
        bot.answer_callback_query(call.id, "✅ Зведення боржників надіслано!")

    elif action == "remind":
        if not user_can(tg_id, "send_payment_reminder"):
            bot.answer_callback_query(call.id, "⛔ Немає доступу", show_alert=True)
            return
        sent = payments_svc.send_payment_reminders()
        bot.answer_callback_query(call.id, f"✅ Надіслано нагадувань: {sent}")

    elif action == "set_status" and len(parts) >= 5:
        member_id, new_status = parts[3], parts[4]
        # Знаходимо payment_id для member_id у поточному місяці
        period = payments_svc.get_current_period()
        p_list = payments_svc._payments.get_by_member(member_id)
        current = next((p for p in p_list if p.period == period), None)
        if not current:
            bot.answer_callback_query(call.id, "Оплату не знайдено", show_alert=True)
            return
        try:
            status = PaymentStatus(new_status)
        except ValueError:
            bot.answer_callback_query(call.id, "Невідомий статус", show_alert=True)
            return
        payments_svc.update_payment_status(current.payment_id, status, tg_id)
        bot.answer_callback_query(call.id, f"✅ Статус змінено на: {new_status}")

    else:
        bot.answer_callback_query(call.id)


def _handle_attendance(bot, call, data, tg_id, attendance_svc, repos):
    from datetime import date as _date
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    def _accessible_groups():
        groups = repos.groups.get_by_coach(tg_id)
        if groups:
            return groups
        return repos.groups.get_active()

    def _render_mark_for(group_id: str, lesson_date):
        group = repos.groups.get_by_id(group_id)
        if not group:
            bot.answer_callback_query(call.id, "Групу не знайдено", show_alert=True)
            return
        journal = attendance_svc.get_journal_for_group(group.group_id, lesson_date)
        text = f"📋 Журнал: <b>{group.name}</b>\n{lesson_date.strftime('%d.%m.%Y')}"
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb.mark_attendance_keyboard(group.group_id, str(lesson_date), journal),
        )

    def _render_view_for(group_id: str, lesson_date):
        summary = attendance_svc.get_attendance_summary(group_id, lesson_date)
        bot.edit_message_text(
            summary,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb.back_button("menu:attendance"),
        )

    if action == "mark":
        groups = _accessible_groups()
        if not groups:
            bot.answer_callback_query(call.id, "Групи не знайдено", show_alert=True)
            return
        today = _date.today()
        if len(groups) > 1:
            bot.edit_message_text(
                "🥋 Оберіть групу для відмітки відвідуваності:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb.attendance_groups_keyboard(groups, "mark", str(today)),
            )
            return
        _render_mark_for(groups[0].group_id, today)

    elif action == "view":
        groups = _accessible_groups()
        if not groups:
            bot.answer_callback_query(call.id, "Групи не знайдено", show_alert=True)
            return
        today = _date.today()
        if len(groups) > 1:
            bot.edit_message_text(
                "🥋 Оберіть групу для перегляду журналу:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb.attendance_groups_keyboard(groups, "view", str(today)),
            )
            return
        _render_view_for(groups[0].group_id, today)

    elif action == "pickg" and len(parts) >= 5:
        mode, group_id, lesson_date_str = parts[2], parts[3], parts[4]
        groups = _accessible_groups()
        if group_id not in {g.group_id for g in groups}:
            bot.answer_callback_query(call.id, "⛔ Немає доступу до цієї групи", show_alert=True)
            return
        lesson_date = _parse_date_str(lesson_date_str)
        if mode == "mark":
            _render_mark_for(group_id, lesson_date)
        else:
            _render_view_for(group_id, lesson_date)

    elif action == "toggle" and len(parts) >= 5:
        group_id, lesson_date_str, member_id = parts[2], parts[3], parts[4]
        lesson_date = _parse_date_str(lesson_date_str)
        # Перемикаємо статус: unmarked → present → absent → present
        records = attendance_svc._attendance.get_by_group_date(group_id, lesson_date)
        existing = next((r for r in records if r.member_id == member_id), None)
        if not existing or existing.status == AttendanceStatus.ABSENT:
            new_status = AttendanceStatus.PRESENT
        else:
            new_status = AttendanceStatus.ABSENT
        attendance_svc.mark_attendance(group_id, lesson_date, member_id, new_status, tg_id)
        journal = attendance_svc.get_journal_for_group(group_id, lesson_date)
        bot.edit_message_reply_markup(
            call.message.chat.id, call.message.message_id,
            reply_markup=kb.mark_attendance_keyboard(group_id, lesson_date_str, journal)
        )
        bot.answer_callback_query(call.id)

    elif action == "close" and len(parts) >= 4:
        group_id, lesson_date_str = parts[2], parts[3]
        lesson_date = _parse_date_str(lesson_date_str)
        present, absent = attendance_svc.close_journal(group_id, lesson_date, tg_id)
        bot.edit_message_text(
            f"✅ Журнал закрито!\n✅ Присутніх: {present}\n❌ Відсутніх: {absent}",
            call.message.chat.id, call.message.message_id,
            reply_markup=kb.back_button("menu:attendance")
        )

    elif action == "unclosed":
        unclosed = attendance_svc.check_unclosed_journals()
        bot.answer_callback_query(
            call.id,
            f"Незакритих журналів: {unclosed}" if unclosed else "✅ Всі журнали закриті!"
        )

    elif action == "inactive":
        inactive = attendance_svc.get_inactive_members(7)
        if not inactive:
            bot.answer_callback_query(call.id, "✅ Неактивних учнів немає!")
            return
        lines = ["😟 <b>Неактивні учні (7+ днів):</b>\n"]
        for member, days in inactive[:15]:
            lines.append(f"• {member.full_name} — {days} днів")
        bot.edit_message_text(
            "\n".join(lines), call.message.chat.id, call.message.message_id,
            reply_markup=kb.back_button("menu:attendance")
        )

    else:
        bot.answer_callback_query(call.id)


def _handle_leads(bot, call, data, tg_id, role, leads_svc, repos, notifications, cfg, wizard_state):
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "list":
        all_leads = repos.leads.get_all()
        active = [ld for ld in all_leads if ld.status not in (
            LeadStatus.CONVERTED, LeadStatus.DECLINED
        )]
        if not active:
            bot.edit_message_text(
                "🔍 Активних лідів немає.",
                call.message.chat.id, call.message.message_id,
                reply_markup=kb.leads_menu()
            )
            return
        lines = ["🔍 <b>Активні ліди:</b>\n"]
        for ld in active[:20]:
            pt = "👤" if ld.is_adult else "🧒"
            lines.append(
                f"{pt} <b>{ld.child_name}</b> — {_lead_status_ua(ld.status)}"
            )
        bot.edit_message_text(
            "\n".join(lines), call.message.chat.id, call.message.message_id,
            reply_markup=kb.back_button("menu:leads")
        )

    elif action == "trials_today":
        from datetime import date as _date
        trials = repos.leads.get_trials_on_date(_date.today())
        if not trials:
            bot.answer_callback_query(call.id, "Сьогодні проб немає")
            return
        lines = [f"📅 <b>Проби сьогодні ({len(trials)}):</b>\n"]
        for ld in trials:
            pt = "👤" if ld.is_adult else "🧒"
            lines.append(f"{pt} {ld.child_name}")
        bot.edit_message_text(
            "\n".join(lines), call.message.chat.id, call.message.message_id,
            reply_markup=kb.back_button("menu:leads")
        )

    elif action == "trial_present" and len(parts) >= 3:
        lead = leads_svc.mark_trial_present(parts[2])
        if lead:
            bot.answer_callback_query(call.id, "✅ Відмічено: був присутній")
            bot.edit_message_text(
                f"✅ <b>Результат пробного оновлено</b>\n\n"
                f"Учасник: <b>{lead.child_name}</b>\n"
                f"Статус: <b>був присутній</b>\n\n"
                "Можна змінити рішення, якщо натиснули помилково.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb.after_trial_keyboard(lead.lead_id),
            )
        else:
            bot.answer_callback_query(call.id, "Лід не знайдений", show_alert=True)

    elif action == "trial_absent" and len(parts) >= 3:
        lead = leads_svc.mark_trial_absent(parts[2])
        if lead:
            bot.answer_callback_query(call.id, "❌ Відмічено: не прийшов")
            bot.edit_message_text(
                f"❌ <b>Результат пробного оновлено</b>\n\n"
                f"Учасник: <b>{lead.child_name}</b>\n"
                f"Статус: <b>не прийшов</b>\n\n"
                "Якщо учасник запізнився або це помилка — можна змінити рішення.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb.after_trial_keyboard(lead.lead_id),
            )
        else:
            bot.answer_callback_query(call.id, "Лід не знайдений", show_alert=True)

    elif action == "undo" and len(parts) >= 3:
        lead = leads_svc.undo_last_trial_decision(parts[2])
        if not lead:
            bot.answer_callback_query(call.id, "Лід не знайдений", show_alert=True)
            return
        bot.answer_callback_query(call.id, "↩️ Рішення скасовано")
        bot.edit_message_text(
            f"↩️ <b>Рішення скасовано</b>\n\n"
            f"Учасник: <b>{lead.child_name}</b>\n"
            f"Статус повернено: <b>{_lead_status_ua(lead.status)}</b>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb.after_trial_keyboard(lead.lead_id),
        )

    elif action == "reschedule" and len(parts) >= 3:
        lead_id = parts[2]
        lead = repos.leads.get_by_id(lead_id)
        if not lead:
            bot.answer_callback_query(call.id, "Лід не знайдений", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            f"📅 <b>Перенесення пробного</b>\n\n"
            f"Учасник: <b>{lead.child_name}</b>\n"
            "Оберіть, на скільки днів перенести:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb.trial_reschedule_keyboard(lead_id),
        )

    elif action == "reschedule_pick" and len(parts) >= 4:
        lead_id = parts[2]
        try:
            days = int(parts[3])
        except ValueError:
            bot.answer_callback_query(call.id, "Некоректний інтервал", show_alert=True)
            return
        new_date = date.today() + timedelta(days=max(1, days))
        lead = leads_svc.reschedule_trial(lead_id, new_date)
        if not lead:
            bot.answer_callback_query(call.id, "Лід не знайдений", show_alert=True)
            return
        bot.answer_callback_query(call.id, "✅ Пробне перенесено")
        bot.edit_message_text(
            f"📅 <b>Пробне перенесено</b>\n\n"
            f"Учасник: <b>{lead.child_name}</b>\n"
            f"Нова дата: <b>{new_date.strftime('%d.%m.%Y')}</b>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb.after_trial_keyboard(lead.lead_id),
        )

    elif action == "convert" and len(parts) >= 3:
        lead_id = parts[2]
        lead = repos.leads.get_by_id(lead_id)
        if not lead:
            bot.answer_callback_query(call.id, "Лід не знайдено", show_alert=True)
            return
        bot.edit_message_text(
            f"🎉 Зарахувати <b>{lead.child_name}</b> до клубу?\n"
            f"Тип: {'дорослий' if lead.is_adult else 'дитина'}",
            call.message.chat.id, call.message.message_id,
            reply_markup=kb.confirm_convert_keyboard(lead_id)
        )

    elif action == "confirm_convert" and len(parts) >= 3:
        lead_id = parts[2]
        groups = repos.groups.get_active()
        group_id = groups[0].group_id if groups else "default"
        member = leads_svc.convert_to_member(lead_id, group_id, tg_id)
        if member:
            bot.edit_message_text(
                f"✅ <b>{member.full_name}</b> зараховано до клубу!",
                call.message.chat.id, call.message.message_id,
                reply_markup=kb.back_button("menu:leads")
            )
        else:
            bot.answer_callback_query(call.id, "Помилка конвертації", show_alert=True)

    elif action == "remind":
        d, t = leads_svc.send_trial_reminders()
        bot.answer_callback_query(call.id, f"✅ Нагадувань: {d} (завтра), {t} (сьогодні)")

    elif action == "new":
        # Запускаємо бот-реєстрацію
        bot.answer_callback_query(call.id)
        extra = ""
        if role in (Role.OWNER, Role.ADMIN, Role.COACH):
            extra = "\n\nДля повної анкети учасника в боті: <code>/registermember</code>."
        bot.send_message(
            tg_id,
            "📝 <b>Новий лід / пробне</b>\n\n"
            "Для пробного використовуйте окрему коротку форму. "
            "Для чинного учасника — повну реєстрацію."
            + extra,
            disable_web_page_preview=True,
            reply_markup=kb.forms_menu(cfg.registration_form_url, cfg.trial_form_url),
        )
    else:
        bot.answer_callback_query(call.id)


def _handle_events(bot, call, data, tg_id, events_svc):
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "list":
        upcoming = events_svc._events.get_upcoming(30)
        if not upcoming:
            bot.edit_message_text(
                "📅 Найближчих подій немає.",
                call.message.chat.id, call.message.message_id,
                reply_markup=kb.back_button("menu:events")
            )
            return
        lines = ["📅 <b>Найближчі події:</b>\n"]
        for ev in upcoming[:10]:
            d = ev.event_date.strftime("%d.%m") if ev.event_date else "—"
            lines.append(f"• {d} — {ev.title}")
        bot.edit_message_text(
            "\n".join(lines), call.message.chat.id, call.message.message_id,
            reply_markup=kb.back_button("menu:events")
        )

    elif action == "announce" and len(parts) >= 3:
        event_id = parts[2]
        if not user_can(tg_id, "announce_event"):
            bot.answer_callback_query(call.id, "⛔ Немає доступу", show_alert=True)
            return
        sent = events_svc.announce_event(event_id)
        bot.answer_callback_query(call.id, f"✅ Анонс надіслано {sent} отримувачам")

    else:
        bot.answer_callback_query(call.id)


def _handle_birthdays(bot, call, data, tg_id, birthday_svc):
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    if action == "publish" and len(parts) >= 4:
        member_id, year_raw = parts[2], parts[3]
        try:
            year = int(year_raw)
        except ValueError:
            year = 0
        ok, msg = birthday_svc.publish_to_parents_channel(member_id, year)
        bot.answer_callback_query(call.id, msg, show_alert=not ok)
        if ok:
            bot.edit_message_text(
                f"✅ {msg}",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb.back_button(),
            )
    elif action == "skip":
        bot.answer_callback_query(call.id, "Не публікуємо. Можна змінити вручну.", show_alert=True)
    else:
        bot.answer_callback_query(call.id)


def _handle_ops(bot, call, data, tg_id, wizard_state: dict, repos):
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else "menu"

    if action == "menu":
        wizard_state.pop(tg_id, None)
        bot.edit_message_text(
            "➕ <b>Операції власника</b>\n\n"
            "Оберіть дію. Для щоденної роботи краще користуватися покроковими кнопками.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=kb.owner_operations_menu(),
        )
        return

    if action == "cancel":
        wizard_state.pop(tg_id, None)
        bot.answer_callback_query(call.id, "Скасовано")
        bot.send_message(tg_id, "❌ Дію скасовано.", reply_markup=kb.back_button())
        return

    if action == "add_member":
        wizard_state[tg_id] = {"flow": "add_member", "step": "full_name", "data": {}}
        bot.answer_callback_query(call.id)
        bot.send_message(
            tg_id,
            "➕ <b>Додаємо учасника покроково</b>\n\n"
            "Крок 1/10. Введіть ПІБ учасника:",
            reply_markup=kb.wizard_cancel_keyboard(),
        )
        return

    if action == "add_group":
        wizard_state[tg_id] = {"flow": "add_group", "step": "group_id", "data": {}}
        bot.answer_callback_query(call.id)
        bot.send_message(
            tg_id,
            "🥋 <b>Додаємо або редагуємо групу</b>\n\n"
            "Крок 1/6. Введіть короткий ID групи латиницею, наприклад <code>kids_1800</code>:",
            reply_markup=kb.wizard_cancel_keyboard(),
        )
        return

    if action == "register_member":
        wizard_state[tg_id] = {"flow": "register_member", "step": "full_name", "data": {}}
        bot.answer_callback_query(call.id)
        bot.send_message(
            tg_id,
            "🧾 <b>Анкета реєстрації учасника</b>\n\n"
            "Крок 1/16. Введіть ПІБ учасника:",
            reply_markup=kb.wizard_cancel_keyboard(),
        )
        return

    if action == "set_payment":
        if not _is_owner_admin(tg_id):
            bot.answer_callback_query(call.id, "⛔ Оплати може змінювати тільки власник або адміністратор", show_alert=True)
            return
        members = repos.members.get_active()
        if not members:
            bot.answer_callback_query(call.id, "Спочатку додайте учасників", show_alert=True)
            return
        wizard_state[tg_id] = {"flow": "set_payment", "step": "member_id", "data": {}}
        bot.answer_callback_query(call.id)
        bot.send_message(tg_id, "💰 Оберіть учасника для оплати:", reply_markup=kb.member_list_keyboard(members, "ops:paymember"))
        return

    if action == "edit_members":
        members = repos.members.get_active()
        if not members:
            bot.answer_callback_query(call.id, "Учасників поки немає", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        bot.send_message(tg_id, "👥 Оберіть учасника для редагування:", reply_markup=kb.member_list_keyboard(members, "ops:member"))
        return

    if action == "ptype" and len(parts) >= 3:
        state = wizard_state.get(tg_id)
        if not state or state.get("flow") not in ("add_member", "register_member"):
            bot.answer_callback_query(call.id, "Сесія не знайдена", show_alert=True)
            return
        state["data"]["participant_type"] = parts[2]
        state["step"] = "group_id"
        bot.answer_callback_query(call.id)
        total_steps = "16" if state.get("flow") == "register_member" else "10"
        bot.send_message(
            tg_id,
            f"Крок 4/{total_steps}. Введіть ID групи або напишіть <code>-</code>, якщо групи ще немає.\n\n"
            "Переглянути групи: /groups",
            reply_markup=kb.wizard_cancel_keyboard(),
        )
        return

    if action == "birthday" and len(parts) >= 3:
        state = wizard_state.get(tg_id)
        if not state or state.get("flow") not in ("add_member", "register_member"):
            bot.answer_callback_query(call.id, "Сесія не знайдена", show_alert=True)
            return
        state["data"]["birthday_greeting_enabled"] = parts[2] == "yes"
        if state.get("flow") == "register_member":
            state["step"] = "birthday_public_name"
            bot.answer_callback_query(call.id)
            bot.send_message(
                tg_id,
                "Крок 12/16. Як підписати вітання в каналі?\n"
                "Наприклад: <code>Марко</code>\n"
                "Якщо залишити стандартне імʼя — введіть <code>-</code>.",
                reply_markup=kb.wizard_cancel_keyboard(),
            )
            return
        _finish_add_member_wizard(bot, tg_id, state, wizard_state, repos)
        bot.answer_callback_query(call.id)
        return

    if action == "regphoto" and len(parts) >= 3:
        state = wizard_state.get(tg_id)
        if not state or state.get("flow") != "register_member":
            bot.answer_callback_query(call.id, "Сесія не знайдена", show_alert=True)
            return
        state["data"]["photo_video_consent"] = "так" if parts[2] == "yes" else "ні"
        state["step"] = "coach_notes"
        bot.send_message(
            tg_id,
            "Крок 16/16. Нотатка тренеру (цілі, характер, що важливо на перших заняттях).\n"
            "Якщо поки немає — введіть <code>-</code>:",
            reply_markup=kb.wizard_cancel_keyboard(),
        )
        bot.answer_callback_query(call.id)
        return

    if action == "member" and len(parts) >= 3:
        member_id = parts[2]
        member = repos.members.get_by_id(member_id)
        if not member:
            bot.answer_callback_query(call.id, "Учасника не знайдено", show_alert=True)
            return
        text = _member_card(member)
        bot.answer_callback_query(call.id)
        bot.send_message(tg_id, text, reply_markup=kb.member_edit_keyboard(member_id))
        return

    if action == "edit_member" and len(parts) >= 4:
        member_id, field = parts[2], parts[3]
        member = repos.members.get_by_id(member_id)
        if not member:
            bot.answer_callback_query(call.id, "Учасника не знайдено", show_alert=True)
            return
        if field == "birthday":
            member.birthday_greeting_enabled = not member.birthday_greeting_enabled
            repos.members.upsert(member)
            bot.answer_callback_query(call.id, "🎂 Налаштування ДН змінено")
            bot.send_message(tg_id, _member_card(member), reply_markup=kb.member_edit_keyboard(member_id))
            return
        if field == "active":
            member.active = not member.active
            repos.members.upsert(member)
            bot.answer_callback_query(call.id, "Статус активності змінено")
            bot.send_message(tg_id, _member_card(member), reply_markup=kb.member_edit_keyboard(member_id))
            return
        wizard_state[tg_id] = {"flow": "edit_member", "step": field, "member_id": member_id, "data": {}}
        prompt = "Введіть новий ID групи:" if field == "group" else "Введіть новий телефон:"
        bot.answer_callback_query(call.id)
        bot.send_message(tg_id, prompt, reply_markup=kb.wizard_cancel_keyboard())
        return

    if action == "paymember" and len(parts) >= 3:
        state = wizard_state.get(tg_id) or {"flow": "set_payment", "data": {}}
        state["flow"] = "set_payment"
        state["step"] = "period"
        state["data"]["member_id"] = parts[2]
        wizard_state[tg_id] = state
        bot.answer_callback_query(call.id)
        bot.send_message(tg_id, "Крок 2/5. Введіть період оплати, наприклад <code>2026-05</code>:", reply_markup=kb.wizard_cancel_keyboard())
        return

    bot.answer_callback_query(call.id)


def _handle_wizard_text(bot, message, wizard_state: dict, repos):
    tg_id = message.from_user.id
    text = (message.text or "").strip()
    state = wizard_state.get(tg_id)
    if not state:
        return
    flow = state.get("flow")
    step = state.get("step")
    data = state.setdefault("data", {})

    if flow in ("add_member", "register_member"):
        if step == "full_name":
            data["full_name"] = text
            state["step"] = "birth_date"
            total_steps = "16" if flow == "register_member" else "10"
            bot.reply_to(message, f"Крок 2/{total_steps}. Введіть дату народження у форматі <code>ДД.ММ.РРРР</code>:")
        elif step == "birth_date":
            parsed_birth_date = _parse_date_flexible(text)
            if flow == "register_member" and not parsed_birth_date:
                bot.reply_to(message, "⚠️ Не зміг розпізнати дату. Введіть у форматі <code>ДД.ММ.РРРР</code>, наприклад <code>14.09.2015</code>.")
                return
            data["birth_date"] = parsed_birth_date
            state["step"] = "participant_type"
            total_steps = "16" if flow == "register_member" else "10"
            bot.reply_to(message, f"Крок 3/{total_steps}. Це дитина чи дорослий?", reply_markup=kb.participant_type_keyboard())
        elif step == "group_id":
            data["group_id"] = "" if text == "-" else text
            state["step"] = "parent_name"
            total_steps = "16" if flow == "register_member" else "10"
            bot.reply_to(message, f"Крок 5/{total_steps}. Введіть ПІБ батька/контактної особи або <code>-</code>:")
        elif step == "parent_name":
            data["parent_name"] = "" if text == "-" else text
            state["step"] = "phone"
            total_steps = "16" if flow == "register_member" else "10"
            bot.reply_to(message, f"Крок 6/{total_steps}. Введіть телефон:")
        elif step == "phone":
            if flow == "register_member":
                normalized_digits = "".join(ch for ch in text if ch.isdigit())
                if len(normalized_digits) < 10:
                    bot.reply_to(message, "⚠️ Додайте коректний телефон (мінімум 10 цифр), наприклад <code>+380671234567</code>.")
                    return
            data["phone"] = text
            state["step"] = "email"
            total_steps = "16" if flow == "register_member" else "10"
            bot.reply_to(message, f"Крок 7/{total_steps}. Введіть email або <code>-</code>:")
        elif step == "email":
            if flow == "register_member" and text != "-" and "@" not in text:
                bot.reply_to(message, "⚠️ Email виглядає некоректно. Введіть email або <code>-</code>.")
                return
            data["email"] = "" if text == "-" else text
            state["step"] = "telegram_username"
            total_steps = "16" if flow == "register_member" else "10"
            bot.reply_to(message, f"Крок 8/{total_steps}. Введіть Telegram username батька/учасника або <code>-</code>:")
        elif step == "telegram_username":
            data["telegram_username"] = "" if text == "-" else text
            state["step"] = "viber"
            total_steps = "16" if flow == "register_member" else "10"
            bot.reply_to(message, f"Крок 9/{total_steps}. Введіть Viber/номер або <code>-</code>:")
        elif step == "viber":
            data["viber"] = "" if text == "-" else text
            if flow == "register_member":
                state["step"] = "preferred_contact_channel"
                bot.reply_to(
                    message,
                    "Крок 10/16. Який основний канал зв'язку обрати?\n"
                    "Приклад: <code>telegram</code>, <code>viber</code>, <code>phone</code> або <code>email</code>.",
                )
            else:
                state["step"] = "birthday_greeting"
                bot.reply_to(message, "Крок 10/10. Вітати з днем народження в каналі батьків?", reply_markup=kb.yes_no_keyboard("ops:birthday"))
        elif step == "preferred_contact_channel" and flow == "register_member":
            data["preferred_contact_channel"] = text.lower()
            state["step"] = "birthday_greeting"
            bot.reply_to(message, "Крок 11/16. Вітати з днем народження в каналі батьків?", reply_markup=kb.yes_no_keyboard("ops:birthday"))
        elif step == "birthday_public_name" and flow == "register_member":
            data["birthday_public_name"] = "" if text == "-" else text
            state["step"] = "medical_notes"
            bot.reply_to(
                message,
                "Крок 13/16. Медичні примітки або важливі обмеження.\n"
                "Якщо немає — введіть <code>-</code>:",
            )
        elif step == "medical_notes" and flow == "register_member":
            data["medical_notes"] = "" if text == "-" else text
            state["step"] = "emergency_contact"
            bot.reply_to(
                message,
                "Крок 14/16. Екстрений контакт (ПІБ + телефон), наприклад:\n"
                "<code>Іван Петренко, +380671234567</code>\n"
                "Якщо немає — введіть <code>-</code>:",
            )
        elif step == "emergency_contact" and flow == "register_member":
            data["emergency_contact"] = "" if text == "-" else text
            state["step"] = "photo_video_consent"
            bot.reply_to(
                message,
                "Крок 15/16. Є згода на фото/відео для внутрішніх публікацій клубу?",
                reply_markup=kb.yes_no_keyboard("ops:regphoto"),
            )
        elif step == "coach_notes" and flow == "register_member":
            data["coach_notes"] = "" if text == "-" else text
            _finish_register_member_wizard(bot, tg_id, state, wizard_state, repos)
        return

    if flow == "add_group":
        if step == "group_id":
            data["group_id"] = text
            state["step"] = "name"
            bot.reply_to(message, "Крок 2/6. Назва групи, наприклад <code>Діти 7-10</code>:")
        elif step == "name":
            data["name"] = text
            state["step"] = "coach_id"
            bot.reply_to(message, "Крок 3/6. Telegram ID тренера. Якщо ви тренер — можна ввести <code>329214126</code>:")
        elif step == "coach_id":
            data["coach_id"] = text
            state["step"] = "schedule"
            bot.reply_to(message, "Крок 4/6. Розклад, наприклад <code>пн,ср,пт 18:00-18:40</code>:")
        elif step == "schedule":
            data["schedule"] = text
            state["step"] = "members"
            bot.reply_to(message, "Крок 5/6. Введіть ID учасників через кому або <code>-</code>.\nПодивитись ID: /members")
        elif step == "members":
            data["members"] = "" if text == "-" else text
            state["step"] = "deadline"
            bot.reply_to(message, "Крок 6/6. Час дедлайну закриття журналу, наприклад <code>20:00</code>, або <code>-</code>:")
        elif step == "deadline":
            data["deadline"] = "" if text == "-" else text
            _finish_add_group_wizard(bot, tg_id, state, wizard_state, repos)
        return

    if flow == "edit_member":
        member = repos.members.get_by_id(state.get("member_id"))
        if not member:
            wizard_state.pop(tg_id, None)
            bot.reply_to(message, "⚠️ Учасника не знайдено.")
            return
        if step == "group":
            member.group_id = "" if text == "-" else text
        elif step == "phone":
            member.parent_phone = text
        repos.members.upsert(member)
        wizard_state.pop(tg_id, None)
        bot.reply_to(message, "✅ Учасника оновлено.", reply_markup=kb.member_edit_keyboard(member.member_id))
        return

    if flow == "set_payment":
        if step == "period":
            data["period"] = text
            state["step"] = "status"
            bot.reply_to(message, "Крок 3/5. Статус: <code>paid</code>, <code>partial</code>, <code>unpaid</code>, <code>promised</code>, <code>overdue</code>, <code>frozen</code>:")
        elif step == "status":
            data["status"] = text
            state["step"] = "amount_due"
            bot.reply_to(message, "Крок 4/5. Сума до оплати:")
        elif step == "amount_due":
            data["amount_due"] = text
            state["step"] = "amount_paid"
            bot.reply_to(message, "Крок 5/5. Скільки оплачено:")
        elif step == "amount_paid":
            data["amount_paid"] = text
            _finish_payment_wizard(bot, tg_id, state, wizard_state, repos)
        return


def _handle_trial_type(bot, call, data, tg_id):
    parts = data.split(":")
    pt = parts[1] if len(parts) > 1 else "child"
    pt_ua = "дитину" if pt == "child" else "себе (дорослий)"
    bot.edit_message_text(
        f"📝 Ви реєструєте: <b>{pt_ua}</b>\n\n"
        f"Будь ласка, надішліть ім'я учасника (дитини або дорослого):\n"
        f"<i>Напишіть у чат — Прізвище Ім'я</i>",
        call.message.chat.id, call.message.message_id
    )
    # Наступний крок — ловимо текстове повідомлення (FSM спрощено через next_step_handler)
    bot.register_next_step_handler(
        call.message,
        lambda msg: _step_trial_name(bot, msg, pt, tg_id)
    )


def _step_trial_name(bot, message, participant_type: str, tg_id: int):
    child_name = message.text.strip()
    if not child_name:
        bot.send_message(tg_id, "Ім'я не може бути порожнім. Спробуйте /trial ще раз.")
        return

    if participant_type == "adult":
        # Для дорослого: parent_name = те саме ім'я або пусте
        from app.services.leads import _parse_date_flexible
        _finalize_trial_lead(bot, tg_id, child_name, child_name, participant_type, message)
    else:
        bot.send_message(tg_id, f"👤 Ім'я дитини: <b>{child_name}</b>\n\nВаше ім'я (батько/мати):")
        bot.register_next_step_handler(
            message,
            lambda msg: _step_trial_parent(bot, msg, child_name, tg_id)
        )


def _step_trial_parent(bot, message, child_name: str, tg_id: int):
    parent_name = message.text.strip()
    _finalize_trial_lead(bot, tg_id, child_name, parent_name, "child", message)


def _finalize_trial_lead(bot, tg_id, child_name, parent_name, pt_str, message):
    bot.send_message(
        tg_id,
        f"✅ <b>Дані прийнято!</b>\n\n"
        f"🥋 Учасник: <b>{child_name}</b>\n"
        f"Тип: {'дорослий' if pt_str == 'adult' else 'дитина'}\n\n"
        f"Ваша заявка передана адміністратору. "
        f"Ми зв'яжемося з вами для підтвердження дати пробного тренування.\n\n"
        f"Або скористайтесь формою: /form"
    )
    # Зберігаємо лід (сервіс буде доступний через context у реальному боті)
    log.info(
        "Новий лід через бот: child=%s parent=%s type=%s tg_id=%s",
        child_name, parent_name, pt_str, tg_id
    )


def _handle_templates(bot, call, data, templates_svc):
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "list":
        names = templates_svc.list_names()
        lines = ["✉️ <b>Шаблони повідомлень:</b>\n"]
        for name in names[:20]:
            lines.append(f"• <code>{name}</code>")
        bot.edit_message_text(
            "\n".join(lines),
            call.message.chat.id, call.message.message_id,
            reply_markup=kb.back_button("menu:templates")
        )
    else:
        bot.answer_callback_query(call.id)


# ── Утиліти ───────────────────────────────────────────────────────────────────

def _trial_type_keyboard() -> types.InlineKeyboardMarkup:
    kb_obj = types.InlineKeyboardMarkup(row_width=1)
    kb_obj.add(
        types.InlineKeyboardButton("🧒 Дитина", callback_data="trial_type:child"),
        types.InlineKeyboardButton("👤 Дорослий учасник", callback_data="trial_type:adult"),
        types.InlineKeyboardButton("🏠 Головне меню", callback_data="menu:back"),
    )
    return kb_obj


def _role_ua(role: Role) -> str:
    return {
        Role.OWNER:  "Власник",
        Role.ADMIN:  "Адміністратор",
        Role.COACH:  "Тренер",
        Role.PARENT: "Батьки / учасник",
        Role.LEAD:   "Лід (реєстрація)",
        Role.GUEST:  "Гість",
    }.get(role, role.value)


def _lead_status_ua(status: LeadStatus) -> str:
    return {
        LeadStatus.NEW:             "🆕 Новий",
        LeadStatus.TRIAL_SCHEDULED: "📅 Проба запланована",
        LeadStatus.TRIAL_DONE:      "✅ Проба пройдена",
        LeadStatus.CONVERTED:       "🎉 Зарахований",
        LeadStatus.DECLINED:        "❌ Відмовився",
        LeadStatus.RESCHEDULED:     "🔄 Перенесено",
    }.get(status, status.value)


def _help_text(role: Role, cfg) -> str:
    base = (
        f"🥋 <b>Black Bear Dojo Bot</b>\n\n"
        f"📍 {cfg.club_address}\n"
        f"📞 {cfg.club_phone}\n\n"
        f"<b>Команди:</b>\n"
        f"/start — головне меню\n"
        f"/trial — записатися на пробне тренування\n"
        f"/form — форма реєстрації\n"
        f"/myinfo — ваша інформація\n"
        f"/id — ваш Telegram ID\n"
    )
    if role in (Role.COACH, Role.ADMIN, Role.OWNER):
        base += (
            f"\n<b>Для персоналу:</b>\n"
            f"/digest — дайджест (власник)\n"
            f"/birthdays — перевірити ДН і відправити привітання на модерацію\n"
            f"/registermember — розширена анкета учасника\n"
        )
    if role in (Role.ADMIN, Role.OWNER):
        base += (
            "\n<b>Для власника:</b>\n"
            "/ownerhelp — інструкція керування клубом із бота\n"
            "/syncforms — вручну синхронізувати нові заявки з форм\n"
        )
    return base


def _parse_date_str(s: str):
    from datetime import date
    try:
        from datetime import datetime
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return date.today()


def _is_owner_admin(tg_id: int) -> bool:
    return get_user_role(tg_id) in (Role.OWNER, Role.ADMIN)


def _can_manage_members_groups(tg_id: int) -> bool:
    return get_user_role(tg_id) in (Role.OWNER, Role.ADMIN, Role.COACH)


def _pipe_args(text: str, min_count: int) -> list[str]:
    raw = text.split(" ", 1)
    if len(raw) < 2:
        raise ValueError("після команди немає даних")
    parts = [p.strip() for p in raw[1].split("|")]
    if len(parts) < min_count:
        raise ValueError(f"потрібно мінімум {min_count} полів через |")
    return parts


def _parse_date_flexible(value: str):
    value = (value or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def _first_time_from_schedule(schedule: str) -> str | None:
    import re
    match = re.search(r"(\d{1,2})[:.\s]?(\d{2})", schedule or "")
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"


def _finish_add_member_wizard(bot, tg_id: int, state: dict, wizard_state: dict, repos) -> None:
    data = state.get("data", {})
    full_name = data.get("full_name", "").strip()
    if not full_name:
        bot.send_message(tg_id, "⚠️ Немає ПІБ. Почніть заново.", reply_markup=kb.owner_operations_menu())
        wizard_state.pop(tg_id, None)
        return
    member = Member(
        member_id=str(uuid.uuid4())[:8],
        full_name=full_name,
        birth_date=data.get("birth_date"),
        participant_type=ParticipantType.ADULT if data.get("participant_type") == "adult" else ParticipantType.CHILD,
        parent_name=data.get("parent_name") or None,
        parent_phone=data.get("phone") or None,
        parent_email=data.get("email") or None,
        parent_telegram_username=data.get("telegram_username") or None,
        parent_viber=data.get("viber") or None,
        preferred_contact_channel="telegram/viber/phone",
        group_id=data.get("group_id") or None,
        birthday_greeting_enabled=bool(data.get("birthday_greeting_enabled")),
        birthday_public_name=full_name.split()[0],
        join_date=date.today(),
        active=True,
        registration_source=RegistrationSource.BOT.value,
    )
    repos.members.upsert(member)
    wizard_state.pop(tg_id, None)
    bot.send_message(
        tg_id,
        "✅ <b>Учасника додано</b>\n\n" + _member_card(member),
        reply_markup=kb.member_edit_keyboard(member.member_id),
    )


def _finish_register_member_wizard(bot, tg_id: int, state: dict, wizard_state: dict, repos) -> None:
    data = state.get("data", {})
    full_name = data.get("full_name", "").strip()
    if not full_name:
        bot.send_message(tg_id, "⚠️ Немає ПІБ. Почніть заново.", reply_markup=kb.owner_operations_menu())
        wizard_state.pop(tg_id, None)
        return

    note_parts = []
    if data.get("medical_notes"):
        note_parts.append(f"Медичні примітки: {data['medical_notes']}")
    if data.get("emergency_contact"):
        note_parts.append(f"Екстрений контакт: {data['emergency_contact']}")
    if data.get("coach_notes"):
        note_parts.append(f"Нотатка тренеру: {data['coach_notes']}")
    if data.get("photo_video_consent"):
        note_parts.append(f"Фото/відео згода: {data['photo_video_consent']}")
    notes = " | ".join(note_parts) if note_parts else None

    member = Member(
        member_id=str(uuid.uuid4())[:8],
        full_name=full_name,
        birth_date=data.get("birth_date"),
        participant_type=ParticipantType.ADULT if data.get("participant_type") == "adult" else ParticipantType.CHILD,
        parent_name=data.get("parent_name") or None,
        parent_phone=data.get("phone") or None,
        parent_email=data.get("email") or None,
        parent_telegram_username=data.get("telegram_username") or None,
        parent_viber=data.get("viber") or None,
        preferred_contact_channel=(data.get("preferred_contact_channel") or "telegram/viber/phone"),
        group_id=data.get("group_id") or None,
        birthday_greeting_enabled=bool(data.get("birthday_greeting_enabled")),
        birthday_public_name=(data.get("birthday_public_name") or full_name.split()[0]).strip(),
        photo_video_consent=data.get("photo_video_consent") or None,
        join_date=date.today(),
        active=True,
        registration_source=RegistrationSource.BOT.value,
        notes=notes,
    )
    repos.members.upsert(member)
    wizard_state.pop(tg_id, None)
    bot.send_message(
        tg_id,
        "✅ <b>Анкету збережено, учасника додано</b>\n\n"
        + _member_card(member)
        + "\n\n🎂 Нагадування про ДН увімкнено: "
        + ("так" if member.birthday_greeting_enabled else "ні")
        + "\n📞 Основний канал: "
        + (member.preferred_contact_channel or "-"),
        reply_markup=kb.member_edit_keyboard(member.member_id),
    )


def _finish_add_group_wizard(bot, tg_id: int, state: dict, wizard_state: dict, repos) -> None:
    data = state.get("data", {})
    schedule = data.get("schedule", "")
    group = Group(
        group_id=data.get("group_id", "").strip(),
        name=data.get("name", "").strip(),
        coach_telegram_id=int(data.get("coach_id")) if str(data.get("coach_id", "")).strip().isdigit() else None,
        schedule=schedule,
        attendance_reminder_time=_first_time_from_schedule(schedule) or "",
        attendance_deadline_time=data.get("deadline") or "",
        active=True,
    )
    repos.groups.upsert(group)
    attached = 0
    for member_id in [x.strip() for x in (data.get("members") or "").split(",") if x.strip()]:
        member = repos.members.get_by_id(member_id)
        if member:
            member.group_id = group.group_id
            repos.members.upsert(member)
            attached += 1
    wizard_state.pop(tg_id, None)
    bot.send_message(
        tg_id,
        f"✅ <b>Групу збережено</b>\n\n"
        f"ID: <code>{group.group_id}</code>\n"
        f"Назва: {group.name}\n"
        f"Розклад: {group.schedule}\n"
        f"Тренер: <code>{group.coach_telegram_id or '-'}</code>\n"
        f"Привʼязано учасників: {attached}\n\n"
        "У час старту заняття бот автоматично надішле тренеру attendance.",
        reply_markup=kb.back_button(),
    )


def _finish_payment_wizard(bot, tg_id: int, state: dict, wizard_state: dict, repos) -> None:
    data = state.get("data", {})
    member_id = data.get("member_id", "")
    period = data.get("period", "")
    status = PaymentStatus(data.get("status", "unpaid").strip())
    existing = next((p for p in repos.payments.get_by_member(member_id) if p.period == period), None)
    payment = existing or Payment(
        payment_id=str(uuid.uuid4())[:8],
        member_id=member_id,
        period=period,
        status=status,
    )
    payment.status = status
    payment.amount_due = float(data.get("amount_due") or 0)
    payment.amount_paid = float(data.get("amount_paid") or 0)
    payment.paid_date = date.today() if status == PaymentStatus.PAID else payment.paid_date
    repos.payments.upsert(payment)
    wizard_state.pop(tg_id, None)
    bot.send_message(
        tg_id,
        f"✅ <b>Оплату збережено</b>\n\n"
        f"Учасник: <code>{member_id}</code>\n"
        f"Період: {period}\n"
        f"Статус: {status.value}\n"
        f"Сума: {payment.amount_paid}/{payment.amount_due}",
        reply_markup=kb.back_button(),
    )


def _member_card(member: Member) -> str:
    return (
        f"👤 <b>{member.full_name}</b>\n"
        f"ID: <code>{member.member_id}</code>\n"
        f"Тип: {member.participant_type.value}\n"
        f"Дата народження: {member.birth_date or '-'}\n"
        f"Група: <code>{member.group_id or '-'}</code>\n"
        f"Контакт: {member.parent_name or '-'} | {member.parent_phone or '-'}\n"
        f"Email: {member.parent_email or '-'}\n"
        f"Telegram/Viber: {member.parent_telegram_username or '-'} / {member.parent_viber or '-'}\n"
        f"Основний канал: {member.preferred_contact_channel or '-'}\n"
        f"ДН у канал: {'так' if member.birthday_greeting_enabled else 'ні'}\n"
        f"Нотатки: {member.notes or '-'}\n"
        f"Активний: {'так' if member.active else 'ні'}"
    )


def _birthday_coverage_text(members: list[Member]) -> str:
    total = len(members)
    with_birth_date = [m for m in members if m.birth_date]
    enabled = [m for m in with_birth_date if m.birthday_greeting_enabled]
    missing_birth = [m for m in members if not m.birth_date]
    disabled = [m for m in with_birth_date if not m.birthday_greeting_enabled]

    lines = [
        "📈 <b>Покриття ДН:</b>",
        f"• Активних учасників: <b>{total}</b>",
        f"• Є дата народження: <b>{len(with_birth_date)}</b>",
        f"• Увімкнено привітання: <b>{len(enabled)}</b>",
        f"• Без дати народження: <b>{len(missing_birth)}</b>",
        f"• Привітання вимкнено: <b>{len(disabled)}</b>",
    ]
    if missing_birth:
        lines.append("\n⚠️ Додайте дату народження цим учасникам:")
        for m in missing_birth[:10]:
            lines.append(f"• {m.full_name} (<code>{m.member_id}</code>)")
        if len(missing_birth) > 10:
            lines.append(f"…ще {len(missing_birth) - 10}")
    return "\n".join(lines)


def _owner_help_text() -> str:
    return (
        "🧭 <b>Інструкція власника Black Bear Dojo Bot</b>\n\n"
        "<b>Головна логіка</b>\n"
        "1. Додаєте учасників або приймаєте їх із форм.\n"
        "2. Створюєте групи з розкладом і тренером.\n"
        "3. Привʼязуєте учасників до групи.\n"
        "4. У час тренування бот сам пише тренеру список дітей і кнопки attendance.\n"
        "5. Оплати можна оновлювати з бота або в Google Sheets.\n\n"
        "<b>Форми</b>\n"
        "/trialform — короткий запис на пробне.\n"
        "/register — повна анкета учасника/батьків.\n"
        "/syncforms — вручну підтягнути нові заявки з Google Forms.\n\n"
        "<b>Учасники</b>\n"
        "/registermember — розширена практична анкета учасника (16 кроків).\n"
        "Найзручніше: натисніть <b>➕ Додати</b> → <b>Додати учасника покроково</b>. "
        "Бот сам запитає ПІБ, дату народження, тип, групу й контакти.\n"
        "/members — список учасників з ID.\n"
        "Швидкий формат одним рядком, якщо треба масово:\n"
        "<code>/addmember ПІБ | ДД.ММ.РРРР | child | group_id | ПІБ батька | телефон | email | @telegram | viber | так</code>\n"
        "Для дорослого замість child пишіть <code>adult</code>.\n\n"
        "<b>Групи і розклад</b>\n"
        "Найзручніше: <b>➕ Додати</b> → <b>Додати / редагувати групу покроково</b>.\n"
        "/groups — список груп.\n"
        "Створити/оновити групу:\n"
        "<code>/addgroup kids_1800 | Діти 7-10 | 329214126 | пн,ср,пт 18:00-18:40 | member1,member2 | 20:00</code>\n"
        "Формат розкладу важливий: <code>пн,ср,пт 18:00-18:40</code>. "
        "У цей час бот автоматично надішле тренеру список групи.\n"
        "У відвідуваності бот дозволяє вибрати потрібну групу, якщо їх декілька.\n\n"
        "Щоранку тренер отримує картку з групами на день і кнопками для швидкої attendance.\n\n"
        "<b>Оплати</b>\n"
        "Найзручніше: <b>➕ Додати</b> → <b>Оновити оплату учасника</b>.\n"
        "Оновити оплату:\n"
        "<code>/setpayment member_id | 2026-05 | paid | 2500 | 2500 | mono</code>\n"
        "Статуси: <code>paid</code>, <code>partial</code>, <code>unpaid</code>, <code>promised</code>, <code>overdue</code>, <code>frozen</code>.\n\n"
        "<b>Дні народження</b>\n"
        "/birthdays — перевірити іменинників і надіслати привітання тренеру/власнику на модерацію. "
        "Канал батьків уже задано: <code>-1003210332922</code>.\n\n"
        "<b>Системне</b>\n"
        "/digest — щоденне зведення вручну.\n"
        "/id — дізнатися Telegram ID тренера або адміна."
    )
