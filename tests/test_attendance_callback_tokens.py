from dataclasses import dataclass

from app import keyboards as kb


@dataclass
class Group:
    group_id: str
    name: str


def _callback_data(markup):
    return [
        button.callback_data
        for row in markup.keyboard
        for button in row
        if button.callback_data
    ]


def test_attendance_member_callbacks_stay_under_telegram_limit_for_long_ids():
    group_id = "12345678-1234-1234-1234-123456789012"
    member_id = "member-12345678-1234-1234-1234-123456789012"
    markup = kb.mark_attendance_keyboard(
        group_id,
        "2026-06-04",
        [{"member_id": member_id, "full_name": "Long Id Student", "status": None}],
    )

    callbacks = _callback_data(markup)
    attendance_callbacks = [data for data in callbacks if data.startswith("att:")]

    assert attendance_callbacks
    assert all(len(data.encode("utf-8")) <= 64 for data in attendance_callbacks)

    assert (
        "att:dt:"
        f"{kb.attendance_id_token(group_id)}:"
        "2026-06-04:"
        f"{kb.attendance_id_token(member_id)}"
    ) in attendance_callbacks
    assert (
        "att:de:"
        f"{kb.attendance_id_token(group_id)}:"
        "2026-06-04:"
        f"{kb.attendance_id_token(member_id)}"
    ) in attendance_callbacks
    assert (
        "att:db:present:"
        f"{kb.attendance_id_token(group_id)}:"
        "2026-06-04"
    ) in attendance_callbacks
    assert (
        "att:db:absent:"
        f"{kb.attendance_id_token(group_id)}:"
        "2026-06-04"
    ) in attendance_callbacks
    assert (
        "att:db:excused:"
        f"{kb.attendance_id_token(group_id)}:"
        "2026-06-04"
    ) in attendance_callbacks


def test_attendance_undo_callback_uses_short_token():
    markup = kb.mark_attendance_keyboard(
        "group-12345678-1234-1234-1234-123456789012",
        "2026-06-04",
        [{"member_id": "member-1", "full_name": "Test Student", "status": "present"}],
        undo_token="abc123",
    )

    callbacks = _callback_data(markup)
    attendance_callbacks = [data for data in callbacks if data.startswith("att:")]

    assert "att:du:abc123" in attendance_callbacks
    assert all(len(data.encode("utf-8")) <= 64 for data in attendance_callbacks)


def test_attendance_status_keyboard_has_clear_and_back_callbacks_under_limit():
    group_id = "group-12345678-1234-1234-1234-123456789012"
    member_id = "member-12345678-1234-1234-1234-123456789012"
    markup = kb.attendance_status_keyboard(group_id, "2026-06-04", member_id)

    callbacks = _callback_data(markup)
    attendance_callbacks = [data for data in callbacks if data.startswith("att:")]

    assert (
        "att:ds:clear:"
        f"{kb.attendance_id_token(group_id)}:"
        "2026-06-04:"
        f"{kb.attendance_id_token(member_id)}"
    ) in attendance_callbacks
    assert (
        "att:dg:mark:"
        f"{kb.attendance_id_token(group_id)}:"
        "2026-06-04"
    ) in attendance_callbacks
    assert all(len(data.encode("utf-8")) <= 64 for data in attendance_callbacks)


def test_attendance_group_callbacks_stay_under_telegram_limit_for_long_ids():
    group = Group(
        group_id="group-12345678-1234-1234-1234-123456789012",
        name="Teen Advanced",
    )
    markup = kb.attendance_groups_keyboard([group], "mark", "2026-06-04")

    callbacks = _callback_data(markup)
    attendance_callbacks = [data for data in callbacks if data.startswith("att:")]

    assert attendance_callbacks
    assert all(len(data.encode("utf-8")) <= 64 for data in attendance_callbacks)

    assert attendance_callbacks[0] == (
        "att:dg:mark:"
        f"{kb.attendance_id_token(group.group_id)}:"
        "2026-06-04"
    )


def test_closed_journal_callbacks_stay_under_telegram_limit_for_long_ids():
    group_id = "group-12345678-1234-1234-1234-123456789012"
    markup = kb.attendance_closed_keyboard(group_id, "2026-06-04")

    callbacks = _callback_data(markup)
    attendance_callbacks = [data for data in callbacks if data.startswith("att:")]

    assert attendance_callbacks
    assert all(len(data.encode("utf-8")) <= 64 for data in attendance_callbacks)
    assert (
        "att:dg:mark:"
        f"{kb.attendance_id_token(group_id)}:"
        "2026-06-04"
    ) in attendance_callbacks
    assert (
        "att:dg:view:"
        f"{kb.attendance_id_token(group_id)}:"
        "2026-06-04"
    ) in attendance_callbacks
