"""
services/payments.py — логіка оплат: статуси, боржники, нагадування, прострочення.

Пріоритет #1 у бізнес-логіці.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

from app.models import Member, Payment, PaymentStatus, ReminderType
from app.repositories.base import (
    IMemberRepository,
    IPaymentRepository,
    IReminderLogRepository,
)
from app.services.notifications import NotificationService
from app.services.templates import TemplateService

log = logging.getLogger(__name__)


class PaymentService:
    """
    Управляє оплатами: статуси, боржники, нагадування, перехід у overdue.
    """

    def __init__(
        self,
        payments: IPaymentRepository,
        members: IMemberRepository,
        notifications: NotificationService,
        templates: TemplateService,
        reminder_log: IReminderLogRepository,
        reminder_days: List[int],
        owner_chat_id: int,
    ) -> None:
        self._payments = payments
        self._members = members
        self._notifications = notifications
        self._templates = templates
        self._reminder_log = reminder_log
        self._reminder_days = reminder_days  # напр. [1, 5, 10]
        self._owner_chat_id = owner_chat_id

    # ── Статус оплат ──────────────────────────────────────────────────────────

    def get_current_period(self) -> str:
        """Повертає поточний період у форматі YYYY-MM."""
        return datetime.now().strftime("%Y-%m")

    def get_debtors(self, period: Optional[str] = None) -> List[Tuple[Member, Payment]]:
        """
        Повертає пари (учень, оплата) для боржників поточного або вказаного періоду.
        Виключає paid та frozen.
        """
        period = period or self.get_current_period()
        payments = self._payments.get_by_period(period)
        debtors = []
        for p in payments:
            if p.is_reminder_exempt:
                continue
            member = self._members.get_by_id(p.member_id)
            if member and member.active:
                debtors.append((member, p))
        return debtors

    def get_overdue_payments(self, period: Optional[str] = None) -> List[Tuple[Member, Payment]]:
        """Повертає тільки прострочені платежі."""
        return [
            (m, p) for m, p in self.get_debtors(period)
            if p.status == PaymentStatus.OVERDUE
        ]

    def get_promised_expired(self) -> List[Tuple[Member, Payment]]:
        """Повертає 'обіцяні' оплати, де promised_date < сьогодні."""
        today = date.today()
        result = []
        for p in self._payments.get_by_status(PaymentStatus.PROMISED):
            if p.promised_date and p.promised_date < today:
                m = self._members.get_by_id(p.member_id)
                if m and m.active:
                    result.append((m, p))
        return result

    # ── Нагадування ───────────────────────────────────────────────────────────

    def should_send_reminder_today(self) -> bool:
        """Перевіряє чи сьогодні день нагадування про оплату."""
        today_day = date.today().day
        return today_day in self._reminder_days

    def send_payment_reminders(self, period: Optional[str] = None) -> int:
        """
        Надсилає нагадування всім боржникам (непоіоплаченим і частково оплаченим).
        Пропускає paid / frozen.
        Повертає кількість успішно надісланих.
        """
        period = period or self.get_current_period()
        debtors = self.get_debtors(period)
        sent = 0
        period_display = _format_period(period)

        for member, payment in debtors:
            parent_tg_id = member.parent_telegram_id
            if not parent_tg_id:
                log.warning("Учень %s не має parent_telegram_id — пропускаємо", member.member_id)
                continue

            # Перевіряємо чи вже надсилали сьогодні
            recent = self._reminder_log.get_recent(
                member.member_id, ReminderType.PAYMENT, hours=20
            )
            if recent:
                log.debug("Нагадування %s вже надіслано сьогодні", member.full_name)
                continue

            template_name = (
                "payment_overdue" if payment.status == PaymentStatus.OVERDUE
                else "payment_partial" if payment.status == PaymentStatus.PARTIAL
                else "payment_reminder"
            )
            text = self._templates.render(
                template_name,
                parent_name=member.full_name,
                period=period_display,
                amount_due=payment.amount_due,
                amount_paid=payment.amount_paid,
                balance=round(payment.amount_due - payment.amount_paid, 2),
                status=_payment_status_ua(payment.status),
            )
            ok = self._notifications.send(
                parent_tg_id,
                text,
                reminder_type=ReminderType.PAYMENT,
                target_id=member.member_id,
            )
            if ok:
                sent += 1

        log.info("Надіслано нагадувань про оплату: %d / %d", sent, len(debtors))
        return sent

    def send_debtors_summary_to_owner(self, period: Optional[str] = None) -> None:
        """Надсилає власнику зведення боржників."""
        period = period or self.get_current_period()
        debtors = self.get_debtors(period)
        period_display = _format_period(period)

        if not debtors:
            self._notifications.send_to_owner(
                self._owner_chat_id,
                f"✅ Боржників за {period_display} немає!"
            )
            return

        lines = [f"💰 <b>Боржники за {period_display}</b>\n"]
        for member, payment in debtors:
            icon = _status_icon(payment.status)
            lines.append(
                f"{icon} <b>{member.full_name}</b> — "
                f"{_payment_status_ua(payment.status)}"
                f" ({payment.amount_due - payment.amount_paid:.0f} грн)"
            )

        lines.append(f"\nВсього: <b>{len(debtors)}</b> осіб")
        self._notifications.send_to_owner(self._owner_chat_id, "\n".join(lines))

    # ── Перехід у overdue ─────────────────────────────────────────────────────

    def transition_overdue(self, period: Optional[str] = None) -> int:
        """
        Переводить 'promised' оплати у 'overdue' якщо promised_date прострочено.
        Повертає кількість переведених.
        """
        today = date.today()
        count = 0
        for member, payment in self.get_promised_expired():
            payment.status = PaymentStatus.OVERDUE
            payment.updated_at = datetime.now()
            try:
                self._payments.upsert(payment)
                count += 1
                log.info(
                    "Перевід у overdue: %s (payment_id=%s)",
                    member.full_name, payment.payment_id
                )
            except Exception as e:
                log.error("Помилка переводу overdue для %s: %s", member.full_name, e)
        return count

    # ── Оновлення статусу ─────────────────────────────────────────────────────

    def update_payment_status(
        self,
        payment_id: str,
        new_status: PaymentStatus,
        performed_by: int,
        amount_paid: Optional[float] = None,
        promised_date: Optional[date] = None,
    ) -> Optional[Payment]:
        """
        Оновлює статус оплати.
        Повертає оновлений Payment або None при помилці.
        """
        # Знаходимо по payment_id
        all_payments = self._payments.get_all()
        payment = next((p for p in all_payments if p.payment_id == payment_id), None)
        if not payment:
            log.error("Оплату %s не знайдено", payment_id)
            return None

        payment.status = new_status
        if amount_paid is not None:
            payment.amount_paid = amount_paid
        if promised_date is not None:
            payment.promised_date = promised_date
        if new_status == PaymentStatus.PAID:
            payment.paid_date = date.today()
        payment.updated_at = datetime.now()

        try:
            self._payments.upsert(payment)
            log.info(
                "Оплата %s → %s (by %s)", payment_id, new_status.value, performed_by
            )
            return payment
        except Exception as e:
            log.error("Помилка оновлення оплати %s: %s", payment_id, e)
            return None

    def get_member_payment_summary(self, member_id: str, period: Optional[str] = None) -> str:
        """Повертає текстовий опис статусу оплати учня."""
        period = period or self.get_current_period()
        payments = self._payments.get_by_member(member_id)
        payment = next((p for p in payments if p.period == period), None)
        if not payment:
            return f"Запис про оплату за {_format_period(period)} відсутній."
        icon = _status_icon(payment.status)
        balance = payment.amount_due - payment.amount_paid
        return (
            f"{icon} Статус: <b>{_payment_status_ua(payment.status)}</b>\n"
            f"До сплати: {payment.amount_due:.0f} грн\n"
            f"Сплачено: {payment.amount_paid:.0f} грн\n"
            f"Залишок: {balance:.0f} грн"
        )


# ── Хелпери ───────────────────────────────────────────────────────────────────

def _format_period(period: str) -> str:
    """'2025-07' → 'Липень 2025'"""
    try:
        dt = datetime.strptime(period, "%Y-%m")
        months_ua = [
            "", "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
            "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень"
        ]
        return f"{months_ua[dt.month]} {dt.year}"
    except Exception:
        return period


def _payment_status_ua(status: PaymentStatus) -> str:
    return {
        PaymentStatus.PAID: "✅ Сплачено",
        PaymentStatus.PARTIAL: "💛 Частково",
        PaymentStatus.UNPAID: "❌ Не сплачено",
        PaymentStatus.PROMISED: "🤝 Обіцяно",
        PaymentStatus.OVERDUE: "🔴 Прострочено",
        PaymentStatus.FROZEN: "❄️ Заморожено",
    }.get(status, status.value)


def _status_icon(status: PaymentStatus) -> str:
    return {
        PaymentStatus.PAID: "✅",
        PaymentStatus.PARTIAL: "💛",
        PaymentStatus.UNPAID: "❌",
        PaymentStatus.PROMISED: "🤝",
        PaymentStatus.OVERDUE: "🔴",
        PaymentStatus.FROZEN: "❄️",
    }.get(status, "❓")


def select_debtors_for_reminder(
    payments: List[Payment],
    reminder_days: List[int],
    reference_day: Optional[int] = None,
) -> List[Payment]:
    """
    Чиста функція: повертає платежі, що потребують нагадування сьогодні.
    Не нагадуємо paid / frozen.
    Використовується у тестах без Sheets-залежності.
    """
    today_day = reference_day if reference_day is not None else date.today().day
    if today_day not in reminder_days:
        return []
    return [p for p in payments if not p.is_reminder_exempt]


def get_overdue_candidates(
    payments: List[Payment],
    reference_date: Optional[date] = None,
) -> List[Payment]:
    """
    Чиста функція: повертає promised-платежі з простроченою датою.
    Використовується у тестах.
    """
    today = reference_date or date.today()
    return [
        p for p in payments
        if p.status == PaymentStatus.PROMISED
        and p.promised_date is not None
        and p.promised_date < today
    ]
