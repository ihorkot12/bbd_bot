"""
tests/test_models.py — unit-тести моделей (from_row, парсинг, ParticipantType).
"""
import pytest
from datetime import date, datetime
from app.models import (
    Member, Lead, Payment, UserRole, Group, AttendanceRecord, Event,
    ParticipantType, RegistrationSource, PaymentStatus, LeadStatus,
    AttendanceStatus, Role, EventStatus, FormResponse,
    _parse_date, _parse_dt, _int_or_none, _float_or, _truthy, _safe_enum,
)


# ── _parse_date ───────────────────────────────────────────────────────────────

class TestParseDate:
    def test_iso_format(self):
        assert _parse_date("2026-05-23") == date(2026, 5, 23)

    def test_dot_format(self):
        assert _parse_date("23.05.2026") == date(2026, 5, 23)

    def test_slash_format(self):
        assert _parse_date("23/05/2026") == date(2026, 5, 23)

    def test_empty_string(self):
        assert _parse_date("") is None

    def test_none(self):
        assert _parse_date(None) is None

    def test_whitespace(self):
        assert _parse_date("   ") is None

    def test_invalid(self):
        assert _parse_date("not-a-date") is None


# ── _parse_dt ─────────────────────────────────────────────────────────────────

class TestParseDt:
    def test_full_datetime(self):
        result = _parse_dt("2026-05-23 08:30:00")
        assert result == datetime(2026, 5, 23, 8, 30, 0)

    def test_date_only(self):
        result = _parse_dt("2026-05-23")
        assert result is not None
        assert result.date() == date(2026, 5, 23)

    def test_none(self):
        assert _parse_dt(None) is None

    def test_empty(self):
        assert _parse_dt("") is None


# ── _truthy ───────────────────────────────────────────────────────────────────

class TestTruthy:
    @pytest.mark.parametrize("val", ["true", "True", "TRUE", "1", "так", "yes", "y"])
    def test_truthy_values(self, val):
        assert _truthy(val) is True

    @pytest.mark.parametrize("val", ["false", "False", "0", "ні", "no", "", "  "])
    def test_falsy_values(self, val):
        assert _truthy(val) is False


# ── _safe_enum ────────────────────────────────────────────────────────────────

class TestSafeEnum:
    def test_valid_value(self):
        assert _safe_enum(Role, "owner", Role.GUEST) == Role.OWNER

    def test_invalid_value_returns_default(self):
        assert _safe_enum(Role, "invalid", Role.GUEST) == Role.GUEST

    def test_empty_returns_default(self):
        assert _safe_enum(PaymentStatus, "", PaymentStatus.UNPAID) == PaymentStatus.UNPAID

    def test_none_returns_default(self):
        assert _safe_enum(PaymentStatus, None, PaymentStatus.UNPAID) == PaymentStatus.UNPAID


# ── Member ────────────────────────────────────────────────────────────────────

class TestMember:

    def test_child_member_from_row(self):
        row = {
            "member_id": "m001",
            "full_name": "Тест Іванов",
            "birth_date": "2015-06-15",
            "participant_type": "child",
            "parent_telegram_id": "329214126",
            "parent_name": "Іван Іванов",
            "parent_phone": "+380501234567",
            "group_id": "g1",
            "active": "true",
            "belt": "white",
            "join_date": "2026-01-01",
            "registration_source": "bot",
            "notes": "",
        }
        m = Member.from_row(row)
        assert m.member_id == "m001"
        assert m.participant_type == ParticipantType.CHILD
        assert m.parent_telegram_id == 329214126
        assert m.is_adult is False
        assert m.birth_date == date(2015, 6, 15)

    def test_adult_member_from_row(self):
        row = {
            "member_id": "m002",
            "full_name": "Дорослий Учасник",
            "birth_date": "1990-03-20",
            "participant_type": "adult",
            "parent_telegram_id": "",
            "parent_name": "",
            "parent_phone": "+380671112233",
            "group_id": "g2",
            "active": "true",
            "belt": "",
            "join_date": "",
            "registration_source": "google_form",
            "notes": "Дорослий учасник",
        }
        m = Member.from_row(row)
        assert m.participant_type == ParticipantType.ADULT
        assert m.is_adult is True
        assert m.parent_telegram_id is None
        assert m.registration_source == "google_form"

    def test_empty_cells_safe(self):
        row = {k: "" for k in [
            "member_id", "full_name", "birth_date", "participant_type",
            "parent_telegram_id", "parent_name", "parent_phone",
            "group_id", "active", "belt", "join_date", "registration_source", "notes"
        ]}
        m = Member.from_row(row)
        assert m.participant_type == ParticipantType.CHILD  # default
        assert m.active is False  # empty → falsy
        assert m.parent_telegram_id is None

    def test_active_default_true_for_string_true(self):
        row = {"member_id": "x", "full_name": "X", "birth_date": "",
               "active": "true", "participant_type": "child",
               "parent_telegram_id": "", "parent_name": "", "parent_phone": "",
               "group_id": "", "belt": "", "join_date": "",
               "registration_source": "bot", "notes": ""}
        m = Member.from_row(row)
        assert m.active is True


# ── Lead ─────────────────────────────────────────────────────────────────────

class TestLead:

    def test_child_lead(self):
        row = {
            "lead_id": "ld1", "child_name": "Дитина", "parent_name": "Батько",
            "participant_type": "child", "parent_telegram_id": "12345",
            "parent_phone": "", "status": "new", "trial_date": "2026-06-01",
            "trial_group_id": "", "trial_present": "", "source": "bot",
            "notes": "", "created_at": "", "updated_at": ""
        }
        ld = Lead.from_row(row)
        assert ld.participant_type == ParticipantType.CHILD
        assert ld.is_adult is False
        assert ld.trial_date == date(2026, 6, 1)
        assert ld.trial_present is None
        assert ld.display_name.startswith("Дитина")

    def test_adult_lead(self):
        row = {
            "lead_id": "ld2", "child_name": "Дорослий", "parent_name": "Дорослий",
            "participant_type": "adult", "parent_telegram_id": "99999",
            "parent_phone": "+380501112233", "status": "trial_scheduled",
            "trial_date": "", "trial_group_id": "", "trial_present": "",
            "source": "google_form", "notes": "", "created_at": "", "updated_at": ""
        }
        ld = Lead.from_row(row)
        assert ld.participant_type == ParticipantType.ADULT
        assert ld.is_adult is True
        assert ld.source == "google_form"
        assert ld.display_name == "Дорослий"

    def test_trial_present_true(self):
        row = {
            "lead_id": "ld3", "child_name": "X", "parent_name": "Y",
            "participant_type": "child", "parent_telegram_id": "",
            "parent_phone": "", "status": "trial_done",
            "trial_date": "", "trial_group_id": "", "trial_present": "true",
            "source": "bot", "notes": "", "created_at": "", "updated_at": ""
        }
        ld = Lead.from_row(row)
        assert ld.trial_present is True

    def test_trial_present_false(self):
        row = {
            "lead_id": "ld4", "child_name": "X", "parent_name": "Y",
            "participant_type": "child", "parent_telegram_id": "",
            "parent_phone": "", "status": "trial_done",
            "trial_date": "", "trial_group_id": "", "trial_present": "false",
            "source": "bot", "notes": "", "created_at": "", "updated_at": ""
        }
        ld = Lead.from_row(row)
        assert ld.trial_present is False

    def test_invalid_status_defaults(self):
        row = {
            "lead_id": "x", "child_name": "X", "parent_name": "Y",
            "participant_type": "child", "parent_telegram_id": "",
            "parent_phone": "", "status": "BAD_STATUS",
            "trial_date": "", "trial_group_id": "", "trial_present": "",
            "source": "", "notes": "", "created_at": "", "updated_at": ""
        }
        ld = Lead.from_row(row)
        assert ld.status == LeadStatus.NEW


# ── FormResponse ──────────────────────────────────────────────────────────────

class TestFormResponse:

    def test_basic_from_row(self):
        row = {
            "response_id": "r1",
            "submitted_at": "2026-05-23 10:00:00",
            "participant_type": "child",
            "child_name": "Маленький",
            "parent_name": "Великий",
            "parent_phone": "+38050",
            "trial_date": "2026-06-01",
            "notes": "",
            "processed": "false",
        }
        fr = FormResponse.from_row(row)
        assert fr.response_id == "r1"
        assert fr.participant_type == "child"
        assert fr.trial_date == date(2026, 6, 1)
        assert fr.processed is False

    def test_processed_true(self):
        row = {
            "response_id": "r2", "submitted_at": "", "participant_type": "adult",
            "child_name": "", "parent_name": "", "parent_phone": "",
            "trial_date": "", "notes": "", "processed": "true"
        }
        fr = FormResponse.from_row(row)
        assert fr.processed is True


# ── AttendanceRecord ──────────────────────────────────────────────────────────

class TestAttendanceRecord:

    def test_from_row_basic(self):
        row = {
            "record_id": "r1", "group_id": "g1",
            "lesson_date": "2026-05-23", "member_id": "m1",
            "status": "present", "marked_by": "329214126",
            "marked_at": "2026-05-23 18:30:00", "notes": ""
        }
        r = AttendanceRecord.from_row(row)
        assert r.status == AttendanceStatus.PRESENT
        assert r.marked_by == 329214126
        assert r.lesson_date == date(2026, 5, 23)

    def test_empty_cells(self):
        row = {k: "" for k in [
            "record_id", "group_id", "lesson_date", "member_id",
            "status", "marked_by", "marked_at", "notes"
        ]}
        r = AttendanceRecord.from_row(row)
        assert r.status == AttendanceStatus.ABSENT  # default
        assert r.marked_by is None
