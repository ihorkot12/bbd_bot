from datetime import date, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from app.models import AttendanceRecord, AttendanceStatus, Group, Member, ParticipantType
from app.repositories.stub import build_stub_repositories
from app.services.attendance import AttendanceService


def _build_service():
    repos = build_stub_repositories()
    notifications = MagicMock()
    notifications.send.return_value = True
    templates = MagicMock()
    svc = AttendanceService(
        attendance=repos.attendance,
        groups=repos.groups,
        members=repos.members,
        notifications=notifications,
        templates=templates,
        owner_chat_id=329214126,
    )
    return repos, notifications, svc


def test_pre_lesson_reminder_sent_once_for_same_offset():
    repos, notifications, svc = _build_service()
    repos.groups.upsert(
        Group(
            group_id="kids_a",
            name="Kids A",
            coach_telegram_id=111,
            schedule="ср 18:00-19:00",
            attendance_reminder_time="18:00",
            attendance_deadline_time="20:00",
            active=True,
        )
    )
    repos.members.upsert(
        Member(
            member_id="m1",
            full_name="Test Kid",
            birth_date=date(2017, 5, 1),
            participant_type=ParticipantType.CHILD,
            group_id="kids_a",
            active=True,
        )
    )

    now = datetime(2026, 5, 27, 17, 0, tzinfo=ZoneInfo("Europe/Kyiv"))  # Wednesday
    assert svc.send_pre_lesson_reminders(now=now, offsets_minutes=(60, 30)) == 1
    assert svc.send_pre_lesson_reminders(now=now, offsets_minutes=(60, 30)) == 0
    assert notifications.send.call_count == 1


def test_pre_lesson_reminder_not_sent_on_other_weekday():
    repos, notifications, svc = _build_service()
    repos.groups.upsert(
        Group(
            group_id="kids_b",
            name="Kids B",
            coach_telegram_id=222,
            schedule="ср 18:00-19:00",
            attendance_reminder_time="18:00",
            attendance_deadline_time="20:00",
            active=True,
        )
    )
    now = datetime(2026, 5, 28, 17, 0, tzinfo=ZoneInfo("Europe/Kyiv"))  # Thursday
    assert svc.send_pre_lesson_reminders(now=now, offsets_minutes=(60, 30)) == 0
    assert notifications.send.call_count == 0


def test_morning_card_sends_groups_sorted_and_deduped():
    repos, notifications, svc = _build_service()
    repos.groups.upsert(
        Group(
            group_id="g_late",
            name="Late Group",
            coach_telegram_id=333,
            schedule="ср 19:00-19:40",
            attendance_reminder_time="19:00",
            attendance_deadline_time="20:00",
            active=True,
        )
    )
    repos.groups.upsert(
        Group(
            group_id="g_early",
            name="Early Group",
            coach_telegram_id=333,
            schedule="ср 18:00-18:40",
            attendance_reminder_time="18:00",
            attendance_deadline_time="20:00",
            active=True,
        )
    )

    now = datetime(2026, 5, 27, 7, 30, tzinfo=ZoneInfo("Europe/Kyiv"))  # Wednesday
    assert svc.send_morning_coach_cards(now=now) == 1
    assert svc.send_morning_coach_cards(now=now) == 0

    sent_text = notifications.send.call_args[0][1]
    assert sent_text.index("18:00") < sent_text.index("19:00")


def test_planned_groups_for_date_returns_only_matching_day_sorted():
    repos, notifications, svc = _build_service()
    repos.groups.upsert(
        Group(
            group_id="g_late",
            name="Late Group",
            coach_telegram_id=333,
            schedule="ср 19:00-19:40",
            attendance_reminder_time="19:00",
            attendance_deadline_time="20:00",
            active=True,
        )
    )
    repos.groups.upsert(
        Group(
            group_id="g_early",
            name="Early Group",
            coach_telegram_id=333,
            schedule="ср 18:00-18:40",
            attendance_reminder_time="18:00",
            attendance_deadline_time="20:00",
            active=True,
        )
    )
    repos.groups.upsert(
        Group(
            group_id="g_other",
            name="Other Day",
            coach_telegram_id=333,
            schedule="чт 18:00-18:40",
            attendance_reminder_time="18:00",
            attendance_deadline_time="20:00",
            active=True,
        )
    )

    planned = svc.get_planned_groups_for_date(date(2026, 5, 27))  # Wednesday

    assert [item["group_id"] for item in planned] == ["g_early", "g_late"]
    assert [item["time"] for item in planned] == ["18:00", "19:00"]


def test_parent_absence_followups_only_for_multiple_absences_and_weekly_dedupe():
    repos, notifications, svc = _build_service()
    repos.groups.upsert(
        Group(
            group_id="kids_c",
            name="Kids C",
            coach_telegram_id=444,
            schedule="ср 18:00-19:00",
            attendance_reminder_time="18:00",
            attendance_deadline_time="20:00",
            active=True,
        )
    )
    repos.members.upsert(
        Member(
            member_id="m_abs",
            full_name="Absent Kid",
            birth_date=date(2016, 1, 1),
            participant_type=ParticipantType.CHILD,
            parent_telegram_id=555,
            group_id="kids_c",
            active=True,
        )
    )
    repos.attendance.add(
        AttendanceRecord(
            record_id="r1",
            group_id="kids_c",
            lesson_date=date(2026, 5, 20),
            member_id="m_abs",
            status=AttendanceStatus.ABSENT,
        )
    )
    repos.attendance.add(
        AttendanceRecord(
            record_id="r2",
            group_id="kids_c",
            lesson_date=date(2026, 5, 23),
            member_id="m_abs",
            status=AttendanceStatus.ABSENT,
        )
    )

    now = datetime(2026, 5, 27, 13, 0, tzinfo=ZoneInfo("Europe/Kyiv"))
    assert svc.send_parent_absence_followups(now=now, min_absences=2, lookback_days=21) == 1
    assert svc.send_parent_absence_followups(now=now, min_absences=2, lookback_days=21) == 0
    assert notifications.send.call_count == 1

    next_week = now + timedelta(days=7)
    assert svc.send_parent_absence_followups(now=next_week, min_absences=2, lookback_days=21) == 1


def test_absence_followup_candidates_include_only_two_plus_recent_absences():
    repos, notifications, svc = _build_service()
    repos.groups.upsert(
        Group(
            group_id="kids_d",
            name="Kids D",
            coach_telegram_id=444,
            schedule="ср 18:00-19:00",
            attendance_reminder_time="18:00",
            attendance_deadline_time="20:00",
            active=True,
        )
    )
    repos.members.upsert(
        Member(
            member_id="m_two",
            full_name="Two Absences",
            birth_date=date(2016, 1, 1),
            participant_type=ParticipantType.CHILD,
            parent_phone="+380000000001",
            group_id="kids_d",
            active=True,
        )
    )
    repos.members.upsert(
        Member(
            member_id="m_one",
            full_name="One Absence",
            birth_date=date(2016, 1, 1),
            participant_type=ParticipantType.CHILD,
            group_id="kids_d",
            active=True,
        )
    )
    today = date.today()
    repos.attendance.add(
        AttendanceRecord(
            record_id="r1",
            group_id="kids_d",
            lesson_date=today - timedelta(days=2),
            member_id="m_two",
            status=AttendanceStatus.ABSENT,
        )
    )
    repos.attendance.add(
        AttendanceRecord(
            record_id="r2",
            group_id="kids_d",
            lesson_date=today - timedelta(days=5),
            member_id="m_two",
            status=AttendanceStatus.ABSENT,
        )
    )
    repos.attendance.add(
        AttendanceRecord(
            record_id="r3",
            group_id="kids_d",
            lesson_date=today - timedelta(days=3),
            member_id="m_one",
            status=AttendanceStatus.ABSENT,
        )
    )

    candidates = svc.get_absence_followup_candidates(min_absences=2, lookback_days=21)

    assert [(member.member_id, count, group.group_id) for member, count, group in candidates] == [
        ("m_two", 2, "kids_d")
    ]
