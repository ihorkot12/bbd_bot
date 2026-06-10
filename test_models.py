"""
tests/test_payments.py — unit-тести для логіки оплат.

Тестує чисті функції без залежності від Google Sheets або Telegram.
"""
import pytest
from datetime import date, datetime
from app.models import Payment, PaymentStatus, Member, ParticipantType
from app.services.payments import (
    select_debtors_for_reminder,
    get_overdue_candidates,
    _format_period,
    _payment_status_ua,
)


# ── Фікстури ─────────────────────────────────────────────────────────────────

def make_payment(
    payment_id="p1",
    member_id="m1",
    period="2026-05",
    status=PaymentStatus.UNPAID,
    amount_due=1000.0,
    amount_paid=0.0,
    promised_date=None,
) -> Payment:
    return Payment(
        payment_id=payment_id,
        member_id=member_id,
        period=period,
        status=status,
        amount_due=amount_due,
        amount_paid=amount_paid,
        promised_date=promised_date,
    )


def test_member_from_row_reads_parent_full_name_fallback():
    member = Member.from_row(
        {
            "member_id": "m-parent",
            "full_name": "Тестова Дитина Codex",
            "birth_date": "15.03.2016",
            "participant_type": "child",
            "parent_full_name": "Тестова Мама Codex",
            "parent_phone": "+380501112233",
        }
    )

    assert member.parent_name == "Тестова Мама Codex"


# ── select_debtors_for_reminder ───────────────────────────────────────────────

class TestSelectDebtorsForReminder:

    def test_returns_unpaid_on_reminder_day(self):
        payments = [
            make_payment("p1", status=PaymentStatus.UNPAID),
            make_payment("p2", status=PaymentStatus.PARTIAL),
        ]
        result = select_debtors_for_reminder(payments, reminder_days=[1, 5, 10], reference_day=5)
        assert len(result) == 2

    def test_excludes_paid(self):
        payments = [
            make_payment("p1", status=PaymentStatus.PAID),
            make_payment("p2", status=PaymentStatus.UNPAID),
        ]
        result = select_debtors_for_reminder(payments, reminder_days=[1, 5, 10], reference_day=1)
        assert len(result) == 1
        assert result[0].payment_id == "p2"

    def test_excludes_frozen(self):
        payments = [
            make_payment("p1", status=PaymentStatus.FROZEN),
            make_payment("p2", status=PaymentStatus.OVERDUE),
        ]
        result = select_debtors_for_reminder(payments, reminder_days=[1, 5, 10], reference_day=10)
        assert len(result) == 1
        assert result[0].payment_id == "p2"

    def test_returns_empty_on_non_reminder_day(self):
        payments = [
            make_payment("p1", status=PaymentStatus.UNPAID),
        ]
        result = select_debtors_for_reminder(payments, reminder_days=[1, 5, 10], reference_day=15)
        assert result == []

    def test_includes_promised_on_reminder_day(self):
        payments = [
            make_payment("p1", status=PaymentStatus.PROMISED),
        ]
        result = select_debtors_for_reminder(payments, reminder_days=[1], reference_day=1)
        assert len(result) == 1

    def test_empty_payments(self):
        result = select_debtors_for_reminder([], reminder_days=[1, 5, 10], reference_day=1)
        assert result == []

    def test_all_exempt(self):
        payments = [
            make_payment("p1", status=PaymentStatus.PAID),
            make_payment("p2", status=PaymentStatus.FROZEN),
        ]
        result = select_debtors_for_reminder(payments, reminder_days=[5], reference_day=5)
        assert result == []


# ── get_overdue_candidates ────────────────────────────────────────────────────

class TestGetOverdueCandidates:

    def test_promised_past_date_becomes_overdue(self):
        payments = [
            make_payment("p1", status=PaymentStatus.PROMISED,
                         promised_date=date(2026, 5, 1)),
        ]
        result = get_overdue_candidates(payments, reference_date=date(2026, 5, 10))
        assert len(result) == 1
        assert result[0].payment_id == "p1"

    def test_promised_future_date_not_overdue(self):
        payments = [
            make_payment("p1", status=PaymentStatus.PROMISED,
                         promised_date=date(2026, 12, 31)),
        ]
        result = get_overdue_candidates(payments, reference_date=date(2026, 5, 23))
        assert result == []

    def test_non_promised_not_in_candidates(self):
        payments = [
            make_payment("p1", status=PaymentStatus.UNPAID),
            make_payment("p2", status=PaymentStatus.OVERDUE),
        ]
        result = get_overdue_candidates(payments, reference_date=date(2026, 5, 23))
        assert result == []

    def test_no_promised_date_excluded(self):
        payments = [
            make_payment("p1", status=PaymentStatus.PROMISED, promised_date=None),
        ]
        result = get_overdue_candidates(payments, reference_date=date(2026, 5, 23))
        assert result == []

    def test_promised_exactly_today_not_overdue(self):
        today = date(2026, 5, 23)
        payments = [
            make_payment("p1", status=PaymentStatus.PROMISED, promised_date=today),
        ]
        result = get_overdue_candidates(payments, reference_date=today)
        assert result == []  # прострочено лише якщо < today

    def test_multiple_overdue(self):
        payments = [
            make_payment("p1", status=PaymentStatus.PROMISED, promised_date=date(2026, 5, 1)),
            make_payment("p2", status=PaymentStatus.PROMISED, promised_date=date(2026, 5, 2)),
            make_payment("p3", status=PaymentStatus.PROMISED, promised_date=date(2026, 12, 31)),
        ]
        result = get_overdue_candidates(payments, reference_date=date(2026, 5, 23))
        assert len(result) == 2


# ── Payment.balance property ──────────────────────────────────────────────────

class TestPaymentBalance:

    def test_balance_unpaid(self):
        p = make_payment(amount_due=1500.0, amount_paid=0.0)
        assert p.balance == 1500.0

    def test_balance_partial(self):
        p = make_payment(amount_due=1500.0, amount_paid=500.0)
        assert p.balance == 1000.0

    def test_balance_paid(self):
        p = make_payment(status=PaymentStatus.PAID, amount_due=1000.0, amount_paid=1000.0)
        assert p.balance == 0.0

    def test_is_reminder_exempt_paid(self):
        p = make_payment(status=PaymentStatus.PAID)
        assert p.is_reminder_exempt is True

    def test_is_reminder_exempt_frozen(self):
        p = make_payment(status=PaymentStatus.FROZEN)
        assert p.is_reminder_exempt is True

    def test_is_reminder_not_exempt_unpaid(self):
        p = make_payment(status=PaymentStatus.UNPAID)
        assert p.is_reminder_exempt is False

    def test_is_reminder_not_exempt_overdue(self):
        p = make_payment(status=PaymentStatus.OVERDUE)
        assert p.is_reminder_exempt is False


# ── Helpers ───────────────────────────────────────────────────────────────────

class TestHelpers:

    def test_format_period_july_2025(self):
        result = _format_period("2025-07")
        assert "Липень" in result
        assert "2025" in result

    def test_format_period_january(self):
        result = _format_period("2026-01")
        assert "Січень" in result

    def test_format_period_invalid(self):
        result = _format_period("invalid")
        assert result == "invalid"

    def test_payment_status_ua_paid(self):
        assert "Сплачено" in _payment_status_ua(PaymentStatus.PAID)

    def test_payment_status_ua_overdue(self):
        assert "Прострочено" in _payment_status_ua(PaymentStatus.OVERDUE)


# ── Payment.from_row ──────────────────────────────────────────────────────────

class TestPaymentFromRow:

    def test_basic_row(self):
        row = {
            "payment_id": "abc123",
            "member_id": "m1",
            "period": "2026-05",
            "status": "unpaid",
            "amount_due": "1500",
            "amount_paid": "0",
        }
        p = Payment.from_row(row)
        assert p.payment_id == "abc123"
        assert p.status == PaymentStatus.UNPAID
        assert p.amount_due == 1500.0

    def test_empty_cells_safe(self):
        row = {
            "payment_id": "",
            "member_id": "",
            "period": "",
            "status": "",
            "amount_due": "",
            "amount_paid": "",
        }
        p = Payment.from_row(row)
        assert p.amount_due == 0.0
        assert p.status == PaymentStatus.UNPAID  # default

    def test_invalid_status_defaults(self):
        row = {
            "payment_id": "x", "member_id": "m", "period": "2026-05",
            "status": "TOTALLY_UNKNOWN", "amount_due": "100", "amount_paid": "0"
        }
        p = Payment.from_row(row)
        assert p.status == PaymentStatus.UNPAID
