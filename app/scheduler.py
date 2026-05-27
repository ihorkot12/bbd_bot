"""
scheduler.py — фонові завдання (APScheduler BackgroundScheduler).

Усі джоби прив'язані до часового поясу Europe/Kyiv.
Конфігурація часу береться з Config та налаштувань у Sheets.

Розклад задач:
  - Щодня: нагадування про оплату (у дні payment_reminder_days)
  - Щодня о digest_time: дайджест власнику
  - Щодня о attendance_reminder_time: нагадування тренерам
  - Щодня о attendance_deadline_time: перевірка незакритих журналів
  - Щодня о 09:00: нагадування про проби (день до + в день проби)
  - Щотижня в понеділок: переведення в overdue
  - Щодня о 10:00: перевірка неактивних учнів
  - Щодня о 12:00: нагадування про майбутні події
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    _APSCHEDULER_AVAILABLE = True
except ImportError:
    _APSCHEDULER_AVAILABLE = False
    BackgroundScheduler = None
    CronTrigger = None

if TYPE_CHECKING:
    from app.services.attendance import AttendanceService
    from app.services.digest import DigestService
    from app.services.events import EventService
    from app.services.leads import LeadService
    from app.services.payments import PaymentService
    from app.services.birthdays import BirthdayService

log = logging.getLogger(__name__)


class BotScheduler:
    """
    Обгортка над APScheduler BackgroundScheduler.
    Ініціалізується після побудови всіх сервісів.
    """

    def __init__(
        self,
        payments_svc: "PaymentService",
        attendance_svc: "AttendanceService",
        leads_svc: "LeadService",
        events_svc: "EventService",
        digest_svc: "DigestService",
        birthday_svc: "BirthdayService" = None,
        timezone: str = "Europe/Kyiv",
        payment_reminder_days: list = None,
        attendance_reminder_time: str = "09:00",
        attendance_deadline_time: str = "22:00",
        coach_morning_card_time: str = "07:30",
        attendance_pre_reminder_minutes: list[int] | None = None,
        digest_time: str = "08:00",
        birthday_check_time: str = "09:00",
    ) -> None:
        self._payments_svc = payments_svc
        self._attendance_svc = attendance_svc
        self._leads_svc = leads_svc
        self._events_svc = events_svc
        self._digest_svc = digest_svc
        self._birthday_svc = birthday_svc
        self._timezone = timezone
        self._payment_reminder_days = payment_reminder_days or [1, 5, 10]
        self._att_reminder_h, self._att_reminder_m = _parse_time(attendance_reminder_time)
        self._att_deadline_h, self._att_deadline_m = _parse_time(attendance_deadline_time)
        self._coach_morning_h, self._coach_morning_m = _parse_time(coach_morning_card_time)
        self._attendance_pre_reminder_minutes = attendance_pre_reminder_minutes or [60, 30]
        self._digest_h, self._digest_m = _parse_time(digest_time)
        self._birthday_h, self._birthday_m = _parse_time(birthday_check_time)
        self._scheduler = None

    def start(self) -> None:
        """Запускає планувальник і реєструє всі задачі."""
        if not _APSCHEDULER_AVAILABLE:
            log.error(
                "APScheduler не встановлено. Виконайте: pip install apscheduler\n"
                "Планувальник не запущено."
            )
            return

        self._scheduler = BackgroundScheduler(timezone=self._timezone)
        self._register_jobs()
        self._scheduler.start()
        log.info("Планувальник запущено (timezone=%s)", self._timezone)

    def shutdown(self, wait: bool = False) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=wait)
            log.info("Планувальник зупинено")

    def _register_jobs(self) -> None:
        sch = self._scheduler

        # ── Дайджест власнику ─────────────────────────────────────────────
        sch.add_job(
            self._job_digest,
            CronTrigger(
                hour=self._digest_h, minute=self._digest_m,
                timezone=self._timezone
            ),
            id="daily_digest",
            name="Щоденний дайджест",
            replace_existing=True,
            misfire_grace_time=300,
        )

        # ── Нагадування про оплату ────────────────────────────────────────
        # Щодня о 10:00 — перевіряємо чи сьогодні день нагадування
        sch.add_job(
            self._job_payment_reminders,
            CronTrigger(hour=10, minute=0, timezone=self._timezone),
            id="payment_reminders",
            name="Нагадування про оплату",
            replace_existing=True,
            misfire_grace_time=600,
        )

        # ── Перехід у overdue (кожного понеділка о 07:00) ────────────────
        sch.add_job(
            self._job_transition_overdue,
            CronTrigger(
                day_of_week="mon", hour=7, minute=0,
                timezone=self._timezone
            ),
            id="transition_overdue",
            name="Перехід promised → overdue",
            replace_existing=True,
        )

        # ── Нагадування тренерам (перед заняттям) ────────────────────────
        sch.add_job(
            self._job_attendance_reminder,
            CronTrigger(
                hour=self._att_reminder_h, minute=self._att_reminder_m,
                timezone=self._timezone
            ),
            id="attendance_reminder",
            name="Нагадування тренерам",
            replace_existing=True,
            misfire_grace_time=300,
        )

        # ── Автостарт attendance саме у час групи ────────────────────────
        sch.add_job(
            self._job_group_lesson_starts,
            CronTrigger(minute="*/5", timezone=self._timezone),
            id="group_lesson_start_prompts",
            name="Автостарт attendance за розкладом груп",
            replace_existing=True,
            misfire_grace_time=120,
        )

        # ── Нагадування тренеру за 60/30 хв до заняття ───────────────────
        sch.add_job(
            self._job_pre_lesson_reminders,
            CronTrigger(minute="*/5", timezone=self._timezone),
            id="pre_lesson_reminders",
            name="Нагадування тренеру до тренування",
            replace_existing=True,
            misfire_grace_time=120,
        )

        # ── Ранкова картка тренера ────────────────────────────────────────
        sch.add_job(
            self._job_coach_morning_cards,
            CronTrigger(
                hour=self._coach_morning_h,
                minute=self._coach_morning_m,
                timezone=self._timezone,
            ),
            id="coach_morning_cards",
            name="Ранкова картка тренера",
            replace_existing=True,
            misfire_grace_time=300,
        )

        # ── Перевірка незакритих журналів (після дедлайну) ───────────────
        sch.add_job(
            self._job_unclosed_check,
            CronTrigger(
                hour=self._att_deadline_h, minute=self._att_deadline_m,
                timezone=self._timezone
            ),
            id="unclosed_check",
            name="Перевірка незакритих журналів",
            replace_existing=True,
            misfire_grace_time=300,
        )

        # ── Нагадування про проби (щодня о 09:00) ────────────────────────
        sch.add_job(
            self._job_trial_reminders,
            CronTrigger(hour=9, minute=0, timezone=self._timezone),
            id="trial_reminders",
            name="Нагадування про проби",
            replace_existing=True,
            misfire_grace_time=300,
        )

        # ── Перевірка неактивних учнів (щодня о 10:30) ───────────────────
        sch.add_job(
            self._job_inactivity_check,
            CronTrigger(hour=10, minute=30, timezone=self._timezone),
            id="inactivity_check",
            name="Перевірка неактивних учнів",
            replace_existing=True,
        )

        # ── Нагадування про майбутні події (щодня о 12:00) ───────────────
        sch.add_job(
            self._job_event_reminders,
            CronTrigger(hour=12, minute=0, timezone=self._timezone),
            id="event_reminders",
            name="Нагадування про події",
            replace_existing=True,
        )

        # ── Дні народження: тренеру/власнику на модерацію ─────────────────
        if self._birthday_svc:
            sch.add_job(
                self._job_birthdays,
                CronTrigger(hour=self._birthday_h, minute=self._birthday_m, timezone=self._timezone),
                id="birthday_moderation",
                name="Модерація привітань з ДН",
                replace_existing=True,
                misfire_grace_time=300,
            )

        log.info("Зареєстровано %d задач планувальника", len(sch.get_jobs()))

    # ── Джоби ─────────────────────────────────────────────────────────────────

    def _job_digest(self) -> None:
        log.info("[Scheduler] Запуск: дайджест власнику")
        try:
            self._digest_svc.send()
        except Exception as e:
            log.error("[Scheduler] Помилка дайджесту: %s", e)

    def _job_payment_reminders(self) -> None:
        log.info("[Scheduler] Запуск: нагадування про оплату")
        try:
            if self._payments_svc.should_send_reminder_today():
                sent = self._payments_svc.send_payment_reminders()
                log.info("[Scheduler] Надіслано нагадувань: %d", sent)
            else:
                log.debug("[Scheduler] Сьогодні не день нагадування про оплату")
        except Exception as e:
            log.error("[Scheduler] Помилка нагадувань про оплату: %s", e)

    def _job_transition_overdue(self) -> None:
        log.info("[Scheduler] Запуск: переведення promised → overdue")
        try:
            count = self._payments_svc.transition_overdue()
            log.info("[Scheduler] Переведено у overdue: %d", count)
        except Exception as e:
            log.error("[Scheduler] Помилка transition_overdue: %s", e)

    def _job_attendance_reminder(self) -> None:
        log.info("[Scheduler] Запуск: нагадування тренерам")
        try:
            sent = self._attendance_svc.send_coach_reminders()
            log.info("[Scheduler] Нагадувань тренерам: %d", sent)
        except Exception as e:
            log.error("[Scheduler] Помилка attendance_reminder: %s", e)

    def _job_group_lesson_starts(self) -> None:
        log.info("[Scheduler] Запуск: автостарт attendance за розкладом груп")
        try:
            now = datetime.now(ZoneInfo(self._timezone))
            sent = self._attendance_svc.send_due_group_attendance_prompts(now)
            if sent:
                log.info("[Scheduler] Attendance prompts за розкладом: %d", sent)
        except Exception as e:
            log.error("[Scheduler] Помилка group_lesson_start_prompts: %s", e)

    def _job_pre_lesson_reminders(self) -> None:
        log.debug("[Scheduler] Запуск: нагадування тренерам до початку тренування")
        try:
            now = datetime.now(ZoneInfo(self._timezone))
            sent = self._attendance_svc.send_pre_lesson_reminders(
                now, tuple(self._attendance_pre_reminder_minutes)
            )
            if sent:
                log.info("[Scheduler] Pre-lesson reminders надіслано: %d", sent)
        except Exception as e:
            log.error("[Scheduler] Помилка pre_lesson_reminders: %s", e)

    def _job_coach_morning_cards(self) -> None:
        log.info("[Scheduler] Запуск: ранкова картка тренера")
        try:
            now = datetime.now(ZoneInfo(self._timezone))
            sent = self._attendance_svc.send_morning_coach_cards(now)
            log.info("[Scheduler] Ранкових карток надіслано: %d", sent)
        except Exception as e:
            log.error("[Scheduler] Помилка coach_morning_cards: %s", e)

    def _job_unclosed_check(self) -> None:
        log.info("[Scheduler] Запуск: перевірка незакритих журналів")
        try:
            unclosed = self._attendance_svc.check_unclosed_journals()
            log.info("[Scheduler] Незакритих журналів: %d", unclosed)
        except Exception as e:
            log.error("[Scheduler] Помилка unclosed_check: %s", e)

    def _job_trial_reminders(self) -> None:
        log.info("[Scheduler] Запуск: нагадування про проби")
        try:
            day_before, today = self._leads_svc.send_trial_reminders()
            log.info("[Scheduler] Нагадувань (завтра/сьогодні): %d/%d", day_before, today)
        except Exception as e:
            log.error("[Scheduler] Помилка trial_reminders: %s", e)

    def _job_inactivity_check(self) -> None:
        log.info("[Scheduler] Запуск: перевірка неактивних учнів")
        try:
            results = self._attendance_svc.send_inactivity_alerts()
            log.info("[Scheduler] Сповіщення неактивних: %s", results)
        except Exception as e:
            log.error("[Scheduler] Помилка inactivity_check: %s", e)

    def _job_event_reminders(self) -> None:
        log.info("[Scheduler] Запуск: нагадування про події")
        try:
            sent = self._events_svc.send_upcoming_reminders()
            log.info("[Scheduler] Нагадувань про події: %d", sent)
        except Exception as e:
            log.error("[Scheduler] Помилка event_reminders: %s", e)

    def _job_birthdays(self) -> None:
        log.info("[Scheduler] Запуск: модерація привітань з ДН")
        try:
            sent = self._birthday_svc.send_moderation_requests() if self._birthday_svc else 0
            log.info("[Scheduler] Привітань на модерацію: %d", sent)
        except Exception as e:
            log.error("[Scheduler] Помилка birthday_moderation: %s", e)


# ── Хелпери ───────────────────────────────────────────────────────────────────

def _parse_time(time_str: str) -> tuple[int, int]:
    """'HH:MM' → (hour, minute)"""
    try:
        h, m = time_str.strip().split(":")
        return int(h), int(m)
    except Exception:
        return 9, 0
