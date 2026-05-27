"""
tests/test_leads.py — unit-тести воронки лідів.
"""
import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, patch
from app.models import Lead, LeadStatus, ParticipantType, RegistrationSource
from app.repositories.stub import build_stub_repositories
from app.services.leads import LeadService, _parse_date_flexible


@pytest.fixture
def repos():
    return build_stub_repositories()


@pytest.fixture
def mock_notifications():
    n = MagicMock()
    n.send.return_value = True
    n.send_to_owner.return_value = True
    return n


@pytest.fixture
def mock_templates():
    t = MagicMock()
    t.render.return_value = "Тестовий шаблон"
    return t


@pytest.fixture
def svc(repos, mock_notifications, mock_templates):
    return LeadService(
        leads=repos.leads,
        members=repos.members,
        notifications=mock_notifications,
        templates=mock_templates,
        owner_chat_id=329214126,
        club_address="Київ, вул. Тестова, 1",
        club_phone="+380500000000",
    )


class TestCreateLead:

    def test_create_child_lead(self, svc, repos):
        lead = svc.create_lead(
            child_name="Тест Дитина",
            parent_name="Тест Батько",
            participant_type=ParticipantType.CHILD,
            parent_telegram_id=12345,
            source="bot",
        )
        assert lead.lead_id != ""
        assert lead.child_name == "Тест Дитина"
        assert lead.participant_type == ParticipantType.CHILD
        assert lead.is_adult is False
        assert lead.status == LeadStatus.NEW
        # Перевіряємо що збережено у repo
        stored = repos.leads.get_by_id(lead.lead_id)
        assert stored is not None
        assert stored.child_name == "Тест Дитина"

    def test_create_adult_lead(self, svc, repos):
        lead = svc.create_lead(
            child_name="Дорослий Учасник",
            parent_name="Дорослий Учасник",
            participant_type=ParticipantType.ADULT,
            parent_telegram_id=99999,
            source="google_form",
        )
        assert lead.is_adult is True
        assert lead.participant_type == ParticipantType.ADULT
        assert lead.source == "google_form"

    def test_create_lead_with_trial_date(self, svc, repos):
        trial = date(2026, 6, 10)
        lead = svc.create_lead(
            child_name="X", parent_name="Y",
            trial_date=trial,
        )
        assert lead.status == LeadStatus.TRIAL_SCHEDULED
        assert lead.trial_date == trial

    def test_create_lead_no_trial_date(self, svc, repos):
        lead = svc.create_lead(child_name="X", parent_name="Y")
        assert lead.status == LeadStatus.NEW
        assert lead.trial_date is None

    def test_create_lead_from_form(self, svc, repos):
        form_data = {
            "participant_type": "child",
            "child_name": "Форма Дитина",
            "parent_name": "Форма Батько",
            "parent_phone": "+380671234567",
            "trial_date": "2026-06-15",
        }
        lead = svc.create_lead_from_form(form_data)
        assert lead.source == RegistrationSource.GOOGLE_FORM.value
        assert lead.child_name == "Форма Дитина"
        assert lead.trial_date == date(2026, 6, 15)
        assert lead.participant_type == ParticipantType.CHILD

    def test_create_adult_from_form(self, svc, repos):
        form_data = {
            "participant_type": "adult",
            "child_name": "Дорослий",
            "parent_name": "",
            "parent_phone": "+380501234567",
        }
        lead = svc.create_lead_from_form(form_data)
        assert lead.participant_type == ParticipantType.ADULT


class TestTrialOutcomes:

    def test_mark_trial_present(self, svc, repos):
        lead = svc.create_lead("X", "Y", participant_type=ParticipantType.CHILD)
        result = svc.mark_trial_present(lead.lead_id)
        assert result is not None
        assert result.trial_present is True
        assert result.status == LeadStatus.TRIAL_DONE

    def test_mark_trial_absent(self, svc, repos):
        lead = svc.create_lead("X", "Y")
        result = svc.mark_trial_absent(lead.lead_id)
        assert result.trial_present is False
        assert result.status == LeadStatus.TRIAL_DONE

    def test_reschedule_trial(self, svc, repos):
        lead = svc.create_lead("X", "Y", trial_date=date(2026, 6, 1))
        new_date = date(2026, 6, 15)
        result = svc.reschedule_trial(lead.lead_id, new_date)
        assert result.trial_date == new_date
        assert result.status == LeadStatus.RESCHEDULED

    def test_mark_nonexistent_lead(self, svc):
        result = svc.mark_trial_present("nonexistent_id")
        assert result is None

    def test_undo_trial_decision(self, svc, repos):
        lead = svc.create_lead("X", "Y", trial_date=date(2026, 6, 1))
        svc.mark_trial_absent(lead.lead_id)
        reverted = svc.undo_last_trial_decision(lead.lead_id)
        assert reverted is not None
        assert reverted.trial_present is None
        assert reverted.status == LeadStatus.TRIAL_SCHEDULED

    def test_convert_child_to_member(self, svc, repos):
        lead = svc.create_lead(
            child_name="Нова Дитина",
            parent_name="Батько",
            participant_type=ParticipantType.CHILD,
            parent_telegram_id=12345,
        )
        member = svc.convert_to_member(lead.lead_id, "g1", 329214126)
        assert member is not None
        assert member.full_name == "Нова Дитина"
        assert member.participant_type == ParticipantType.CHILD
        # Лід → converted
        updated_lead = repos.leads.get_by_id(lead.lead_id)
        assert updated_lead.status == LeadStatus.CONVERTED

    def test_convert_adult_to_member(self, svc, repos):
        lead = svc.create_lead(
            child_name="Дорослий",
            parent_name="Дорослий",
            participant_type=ParticipantType.ADULT,
            parent_telegram_id=99999,
        )
        member = svc.convert_to_member(lead.lead_id, "g1", 329214126)
        assert member.participant_type == ParticipantType.ADULT
        assert member.parent_telegram_id is None  # дорослий — без батьків


class TestParseDateFlexible:
    def test_iso(self):
        assert _parse_date_flexible("2026-06-01") == date(2026, 6, 1)

    def test_dot(self):
        assert _parse_date_flexible("01.06.2026") == date(2026, 6, 1)

    def test_none(self):
        assert _parse_date_flexible(None) is None

    def test_empty(self):
        assert _parse_date_flexible("") is None

    def test_invalid(self):
        assert _parse_date_flexible("abc") is None
