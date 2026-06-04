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

    token = attendance_callbacks[0].split(":")[2]
    assert kb.resolve_attendance_callback(token) == (
        "toggle",
        group_id,
        "2026-06-04",
        member_id,
    )


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

    token = attendance_callbacks[0].split(":")[2]
    assert kb.resolve_attendance_callback(token) == (
        "pickg",
        "mark",
        group.group_id,
        "2026-06-04",
    )
