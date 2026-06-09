from pathlib import Path

from app import keyboards as kb


def _callbacks(markup):
    return [
        button.callback_data
        for row in markup.keyboard
        for button in row
        if getattr(button, "callback_data", None)
    ]


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
