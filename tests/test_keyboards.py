from pathlib import Path

from app import keyboards as kb


def _callbacks(markup):
    return [
        button.callback_data
        for row in markup.keyboard
        for button in row
        if getattr(button, "callback_data", None)
    ]


def _urls(markup):
    return [
        button.url
        for row in markup.keyboard
        for button in row
        if getattr(button, "url", None)
    ]


def test_owner_main_menu_keeps_daily_portal_flow_clean():
    callbacks = _callbacks(kb.main_menu_owner())

    assert callbacks == [
        "menu:attendance",
        "menu:registration",
        "menu:birthdays",
        "menu:formsync",
        "menu:members",
        "ops:menu",
        "menu:ownerhelp",
    ]
    assert "menu:payments" not in callbacks
    assert "menu:leads" not in callbacks
    assert "menu:events" not in callbacks
    assert "menu:templates" not in callbacks
    assert "menu:settings" not in callbacks


def test_parent_and_guest_menus_keep_registration_separate_from_trial():
    parent_callbacks = _callbacks(kb.main_menu_parent())
    guest_callbacks = _callbacks(kb.main_menu_guest())

    assert parent_callbacks == [
        "menu:registration",
        "menu:my_attendance",
        "menu:schedule",
        "menu:contact",
    ]
    assert guest_callbacks == [
        "menu:trial_request",
        "menu:registration",
        "menu:schedule",
        "menu:contact",
    ]
    assert "menu:my_payment" not in parent_callbacks
    assert "menu:events" not in parent_callbacks + guest_callbacks


def test_portal_buttons_open_only_the_requested_form():
    registration = kb.registration_portal_menu("https://forms.example/member")
    trial = kb.trial_portal_menu("https://forms.example/trial")

    assert _urls(registration) == ["https://forms.example/member"]
    assert _callbacks(registration) == ["menu:back"]
    assert _urls(trial) == ["https://forms.example/trial"]
    assert _callbacks(trial) == ["menu:back"]


def test_payment_edit_button_uses_working_owner_flow():
    callbacks = _callbacks(kb.payments_menu())

    assert "ops:set_payment" in callbacks
    assert "pay:edit" not in callbacks


def test_owner_operations_menu_hides_freeze_subscription():
    callbacks = _callbacks(kb.owner_operations_menu())

    assert "ops:freeze_subscription" not in callbacks


def test_events_menu_only_exposes_ready_public_flow():
    callbacks = _callbacks(kb.events_menu())

    assert callbacks == ["evt:list", "menu:back"]


def test_settings_callbacks_have_router_handler():
    source = Path("app/bot.py").read_text(encoding="utf-8")

    assert 'data.startswith("set:")' in source
    assert "def _handle_settings" in source
