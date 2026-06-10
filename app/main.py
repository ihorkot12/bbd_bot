"""
main.py — точка входу в застосунок Black Bear Dojo Bot V2.

Порядок ініціалізації:
  1. Логування
  2. Конфігурація (читає .env)
  3. Google Sheets репозиторії (або dry-run stub)
  4. Сервіси (payments, attendance, leads, events, digest, notifications)
  5. Реєстр ролей (завантаження з Sheets)
  6. Планувальник (APScheduler)
  7. Реєстрація хендлерів бота
  8. Polling

Запуск: python -m app.main
"""
from __future__ import annotations

import signal
import sys
import time

from app.logging_setup import setup_logging, get_logger
from app.config import get_config

# Логування ініціалізуємо першим (до будь-якого імпорту сервісів)
_cfg_tmp_loglevel = __import__("os").getenv("LOG_LEVEL", "INFO")
setup_logging(_cfg_tmp_loglevel)
log = get_logger("main")


def main() -> None:
    # ── 1. Конфігурація ───────────────────────────────────────────────────────
    log.info("=== Black Bear Dojo Bot V2 — старт ===")
    cfg = get_config()
    setup_logging(cfg.log_level, cfg.log_file or None)

    # ── 2. Google Sheets репозиторії ─────────────────────────────────────────
    repos = None
    sheets_client = None

    if cfg.dry_run:
        log.warning("DRY_RUN=true — Google Sheets не ініціалізується")
        repos = _build_stub_repos()
    else:
        try:
            from app.repositories.google_sheets import build_repositories, build_google_sheets_client
            log.info("Підключення до Google Sheets…")
            sheets_client = build_google_sheets_client(cfg.google_credentials_file)
            repos = build_repositories(cfg.google_credentials_file, cfg.spreadsheet_id)
            log.info("Google Sheets підключено: %s", cfg.spreadsheet_id)
        except Exception as e:
            log.error(
                "Не вдалося підключитися до Google Sheets: %s\n"
                "Перевірте GOOGLE_CREDENTIALS_FILE та SPREADSHEET_ID у .env\n"
                "Для запуску без Sheets: DRY_RUN=true",
                e
            )
            sys.exit(1)

    # ── 3. Бот ────────────────────────────────────────────────────────────────
    from app.bot import create_bot
    log.info("Ініціалізація Telegram бота…")
    bot = create_bot(cfg.telegram_token)

    # ── 4. Сервіси ────────────────────────────────────────────────────────────
    from app.services.notifications import NotificationService
    from app.services.templates import TemplateService
    from app.services.payments import PaymentService
    from app.services.attendance import AttendanceService
    from app.services.leads import LeadService
    from app.services.events import EventService
    from app.services.digest import DigestService
    from app.services.form_poller import FormPollerService
    from app.services.birthdays import BirthdayService

    notifications = NotificationService(bot, repos.reminder_log)
    templates_svc = TemplateService(repos.templates)

    payments_svc = PaymentService(
        payments=repos.payments,
        members=repos.members,
        notifications=notifications,
        templates=templates_svc,
        reminder_log=repos.reminder_log,
        reminder_days=cfg.payment_reminder_days,
        owner_chat_id=cfg.owner_chat_id,
    )
    attendance_svc = AttendanceService(
        attendance=repos.attendance,
        groups=repos.groups,
        members=repos.members,
        notifications=notifications,
        templates=templates_svc,
        owner_chat_id=cfg.owner_chat_id,
    )
    leads_svc = LeadService(
        leads=repos.leads,
        members=repos.members,
        notifications=notifications,
        templates=templates_svc,
        owner_chat_id=cfg.owner_chat_id,
        club_address=cfg.club_address,
        club_phone=cfg.club_phone,
    )
    events_svc = EventService(
        events=repos.events,
        members=repos.members,
        users=repos.users,
        notifications=notifications,
        templates=templates_svc,
        owner_chat_id=cfg.owner_chat_id,
    )
    digest_svc = DigestService(
        payments_svc=payments_svc,
        attendance_svc=attendance_svc,
        leads_svc=leads_svc,
        events_svc=events_svc,
        leads=repos.leads,
        groups=repos.groups,
        notifications=notifications,
        owner_chat_id=cfg.owner_chat_id,
    )
    birthday_svc = BirthdayService(
        members=repos.members,
        users=repos.users,
        notifications=notifications,
        templates=templates_svc,
        owner_chat_id=cfg.owner_chat_id,
        parents_channel_id=cfg.parents_channel_id,
    )
    form_poller = FormPollerService(
        lead_service=leads_svc,
        leads_repo=repos.leads,
        members_repo=repos.members,
        sheets_client=sheets_client,
        spreadsheet_id=cfg.spreadsheet_id,
        form_id=cfg.registration_form_id,
        sheets_fallback=False,
        target="members",
    )
    trial_form_poller = FormPollerService(
        lead_service=leads_svc,
        leads_repo=repos.leads,
        sheets_client=sheets_client,
        spreadsheet_id=cfg.spreadsheet_id,
        form_id=cfg.trial_form_id,
        sheets_fallback=cfg.dry_run,
    )

    def sync_member_registration_forms() -> int:
        processed = form_poller.poll_and_process()
        if processed:
            _notify_owner_about_todays_birthdays_after_form_sync(
                birthday_svc=birthday_svc,
                notifications=notifications,
                owner_chat_id=cfg.owner_chat_id,
                imported_count=processed,
            )
        return processed

    def sync_all_forms() -> int:
        return sync_member_registration_forms() + trial_form_poller.poll_and_process()

    # ── 5. Реєстр ролей ───────────────────────────────────────────────────────
    from app import access
    try:
        user_roles = repos.users.get_all()
        access.get_registry().load_from_list(user_roles)
        log.info("Завантажено %d ролей із Sheets", len(user_roles))
        # Власник завжди є у реєстрі
        if cfg.owner_chat_id:
            from app.models import Role
            access.get_registry().set_role(cfg.owner_chat_id, Role.OWNER)
    except Exception as e:
        log.warning("Не вдалося завантажити ролі: %s", e)

    # ── 6. Засів шаблонів (тільки вручну/перший запуск) ──────────────────────
    # У продакшені не робимо це на кожному старті, щоб не впиратися в Google
    # Sheets read quota. Вбудовані шаблони все одно доступні як fallback.
    if cfg.seed_templates_on_startup:
        try:
            seeded = templates_svc.seed_defaults()
            if seeded:
                log.info("Засіяно %d шаблонів у Sheets", seeded)
        except Exception as e:
            log.warning("Не вдалося засіяти шаблони: %s", e)
    else:
        log.info("SEED_TEMPLATES_ON_STARTUP=false — пропускаю засів шаблонів")

    # ── 7. Планувальник ───────────────────────────────────────────────────────
    from app.scheduler import BotScheduler
    scheduler = BotScheduler(
        payments_svc=payments_svc,
        attendance_svc=attendance_svc,
        leads_svc=leads_svc,
        events_svc=events_svc,
        digest_svc=digest_svc,
        birthday_svc=birthday_svc,
        timezone=cfg.timezone,
        payment_reminder_days=cfg.payment_reminder_days,
        attendance_reminder_time=cfg.attendance_reminder_time,
        attendance_deadline_time=cfg.attendance_deadline_time,
        coach_morning_card_time=cfg.coach_morning_card_time,
        attendance_pre_reminder_minutes=cfg.attendance_pre_reminder_minutes,
        parent_absence_followup_time=cfg.parent_absence_followup_time,
        digest_time=cfg.digest_time,
        birthday_check_time=cfg.birthday_check_time,
    )
    scheduler.start()

    # Додаємо опитування форми у планувальник
    try:
        from apscheduler.triggers.interval import IntervalTrigger
        scheduler._scheduler.add_job(
            sync_member_registration_forms,
            IntervalTrigger(minutes=cfg.form_poll_interval_minutes),
            id="form_poller",
            name="Опитування Google Form",
            replace_existing=True,
        )
        log.info(
            "Form poller додано (інтервал: %d хв)", cfg.form_poll_interval_minutes
        )
        scheduler._scheduler.add_job(
            trial_form_poller.poll_and_process,
            IntervalTrigger(minutes=cfg.form_poll_interval_minutes),
            id="trial_form_poller",
            name="Опитування форми пробного",
            replace_existing=True,
        )
        log.info(
            "Trial form poller додано (інтервал: %d хв)", cfg.form_poll_interval_minutes
        )
    except Exception as e:
        log.warning("Не вдалося додати form_poller до планувальника: %s", e)

    # ── 8. Хендлери бота ─────────────────────────────────────────────────────
    from app.bot import register_handlers
    register_handlers(
        bot=bot,
        cfg=cfg,
        repos=repos,
        payments_svc=payments_svc,
        attendance_svc=attendance_svc,
        leads_svc=leads_svc,
        events_svc=events_svc,
        digest_svc=digest_svc,
        birthday_svc=birthday_svc,
        templates_svc=templates_svc,
        notifications=notifications,
        form_sync_fn=sync_all_forms,
    )

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    def _shutdown(signum, frame):
        log.info("Отримано сигнал %s — завершення…", signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # ── 9. Polling ────────────────────────────────────────────────────────────
    log.info(
        "Бот запущено. Owner ID: %s | Таблиця: %s",
        cfg.owner_chat_id, cfg.spreadsheet_id
    )
    log.info("Форма реєстрації: %s", cfg.registration_form_url)
    log.info("Форма пробного: %s", cfg.trial_form_url)
    log.info("Натисніть Ctrl+C для зупинки")

    try:
        log.info("Resetting Telegram webhook before polling...")
        try:
            bot.remove_webhook(drop_pending_updates=False)
        except TypeError:
            bot.remove_webhook()
    except Exception as e:
        log.warning("Could not reset Telegram webhook before polling: %s", e)

    while True:
        try:
            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=20,
                logger_level=None,
                allowed_updates=["message", "callback_query"],
            )
        except Exception:
            log.exception("Telegram polling crashed; restarting in 15 seconds")
            time.sleep(15)


def _build_stub_repos():
    """
    Заглушка репозиторіїв для dry-run / тестів.
    Повертає об'єкт Repositories з порожніми in-memory реалізаціями.
    """
    from app.repositories.base import Repositories
    from app.repositories.stub import build_stub_repositories
    return build_stub_repositories()


def _notify_owner_about_todays_birthdays_after_form_sync(
    *,
    birthday_svc,
    notifications,
    owner_chat_id: int,
    imported_count: int,
) -> None:
    enabled_today = [
        member
        for member in birthday_svc.todays_birthdays()
        if member.birthday_greeting_enabled
    ]
    if not enabled_today:
        return
    names = ", ".join(member.full_name for member in enabled_today[:8])
    if len(enabled_today) > 8:
        names += f" та ще {len(enabled_today) - 8}"
    notifications.send_to_owner(
        owner_chat_id,
        (
            "🎂 <b>Після синхронізації форми є ДН сьогодні</b>\n\n"
            f"Імпортовано нових записів: <b>{imported_count}</b>\n"
            f"Сьогодні можна відправити на модерацію: <b>{len(enabled_today)}</b>\n"
            f"{names}\n\n"
            "Відкрийте /birthdays → <b>📨 На модерацію</b>, "
            "щоб перевірити текст перед публікацією."
        ),
    )


if __name__ == "__main__":
    main()
