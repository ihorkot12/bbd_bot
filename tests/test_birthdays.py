from datetime import date
from unittest.mock import MagicMock

from app import keyboards as kb
from app.main import _notify_owner_about_todays_birthdays_after_form_sync
from app.models import Member, ParticipantType
from app.repositories.stub import build_stub_repositories
from app.services.birthdays import BirthdayService


def _build_service():
    repos = build_stub_repositories()
    notifications = MagicMock()
    templates = MagicMock()
    return repos, BirthdayService(
        members=repos.members,
        users=repos.users,
        notifications=notifications,
        templates=templates,
        owner_chat_id=329214126,
    )


def _callback_data(markup):
    return [
        button.callback_data
        for row in markup.keyboard
        for button in row
        if button.callback_data
    ]


def test_upcoming_birthdays_are_sorted_and_limited():
    repos, svc = _build_service()
    repos.members.upsert(
        Member(
            member_id="m_later",
            full_name="Later Kid",
            birth_date=date(2016, 6, 20),
            participant_type=ParticipantType.CHILD,
            active=True,
        )
    )
    repos.members.upsert(
        Member(
            member_id="m_today",
            full_name="Today Kid",
            birth_date=date(2016, 6, 8),
            participant_type=ParticipantType.CHILD,
            active=True,
        )
    )
    repos.members.upsert(
        Member(
            member_id="m_outside",
            full_name="Outside Kid",
            birth_date=date(2016, 7, 10),
            participant_type=ParticipantType.CHILD,
            active=True,
        )
    )

    upcoming = svc.upcoming_birthdays(days=14, today=date(2026, 6, 8))

    assert [(member.member_id, days_until) for member, _, days_until in upcoming] == [
        ("m_today", 0),
        ("m_later", 12),
    ]


def test_upcoming_birthdays_wrap_across_new_year():
    repos, svc = _build_service()
    repos.members.upsert(
        Member(
            member_id="m_new_year",
            full_name="New Year Kid",
            birth_date=date(2016, 1, 3),
            participant_type=ParticipantType.CHILD,
            active=True,
        )
    )

    upcoming = svc.upcoming_birthdays(days=7, today=date(2026, 12, 30))

    assert len(upcoming) == 1
    assert upcoming[0][1] == date(2027, 1, 3)
    assert upcoming[0][2] == 4


def test_coverage_stats_counts_missing_and_disabled_birthdays():
    repos, svc = _build_service()
    repos.members.upsert(
        Member(
            member_id="m_enabled",
            full_name="Enabled Kid",
            birth_date=date(2016, 6, 8),
            participant_type=ParticipantType.CHILD,
            birthday_greeting_enabled=True,
            active=True,
        )
    )
    repos.members.upsert(
        Member(
            member_id="m_disabled",
            full_name="Disabled Kid",
            birth_date=date(2016, 6, 9),
            participant_type=ParticipantType.CHILD,
            birthday_greeting_enabled=False,
            active=True,
        )
    )
    repos.members.upsert(
        Member(
            member_id="m_missing",
            full_name="Missing Date Kid",
            birth_date=None,
            participant_type=ParticipantType.CHILD,
            active=True,
        )
    )

    stats = svc.coverage_stats()

    assert stats["total"] == 3
    assert stats["with_birth_date"] == 2
    assert stats["enabled"] == 1
    assert [member.member_id for member in stats["missing_birth"]] == ["m_missing"]
    assert [member.member_id for member in stats["disabled"]] == ["m_disabled"]


def test_birthdays_menu_has_explicit_send_action():
    callbacks = _callback_data(kb.birthdays_menu())

    assert callbacks == [
        "bd:today",
        "bd:upcoming",
        "bd:coverage",
        "bd:send",
        "menu:back",
    ]


def test_form_sync_notifies_owner_when_today_has_enabled_birthdays():
    notifications = MagicMock()
    birthday_svc = MagicMock()
    birthday_svc.todays_birthdays.return_value = [
        Member(
            member_id="m_today",
            full_name="Today Kid",
            birth_date=date(2016, 6, 10),
            participant_type=ParticipantType.CHILD,
            birthday_greeting_enabled=True,
            active=True,
        ),
        Member(
            member_id="m_disabled",
            full_name="Disabled Kid",
            birth_date=date(2016, 6, 10),
            participant_type=ParticipantType.CHILD,
            birthday_greeting_enabled=False,
            active=True,
        ),
    ]

    _notify_owner_about_todays_birthdays_after_form_sync(
        birthday_svc=birthday_svc,
        notifications=notifications,
        owner_chat_id=329214126,
        imported_count=2,
    )

    notifications.send_to_owner.assert_called_once()
    args = notifications.send_to_owner.call_args.args
    assert args[0] == 329214126
    assert "Today Kid" in args[1]
    assert "Disabled Kid" not in args[1]
    assert "Імпортовано нових записів: <b>2</b>" in args[1]


def test_form_sync_does_not_notify_without_enabled_birthdays():
    notifications = MagicMock()
    birthday_svc = MagicMock()
    birthday_svc.todays_birthdays.return_value = [
        Member(
            member_id="m_disabled",
            full_name="Disabled Kid",
            birth_date=date(2016, 6, 10),
            participant_type=ParticipantType.CHILD,
            birthday_greeting_enabled=False,
            active=True,
        )
    ]

    _notify_owner_about_todays_birthdays_after_form_sync(
        birthday_svc=birthday_svc,
        notifications=notifications,
        owner_chat_id=329214126,
        imported_count=1,
    )

    notifications.send_to_owner.assert_not_called()
