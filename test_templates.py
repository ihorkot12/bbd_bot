"""
tests/test_access.py — unit-тести ролей і дозволів.
"""
import pytest
from app.models import Role
from app.access import (
    RoleRegistry,
    can,
    has_min_role,
    role_level,
    get_registry,
    reset_registry,
    user_can,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """Скидаємо singleton реєстру перед кожним тестом."""
    reset_registry()
    yield
    reset_registry()


# ── Ієрархія ролей ────────────────────────────────────────────────────────────

class TestRoleHierarchy:

    def test_owner_is_highest(self):
        assert role_level(Role.OWNER) > role_level(Role.ADMIN)
        assert role_level(Role.ADMIN) > role_level(Role.COACH)
        assert role_level(Role.COACH) > role_level(Role.PARENT)
        assert role_level(Role.PARENT) > role_level(Role.LEAD)
        assert role_level(Role.LEAD) > role_level(Role.GUEST)

    def test_guest_is_lowest(self):
        assert role_level(Role.GUEST) == 0

    def test_has_min_role_exact(self):
        assert has_min_role(Role.COACH, Role.COACH) is True

    def test_has_min_role_above(self):
        assert has_min_role(Role.OWNER, Role.COACH) is True
        assert has_min_role(Role.ADMIN, Role.PARENT) is True

    def test_has_min_role_below(self):
        assert has_min_role(Role.GUEST, Role.COACH) is False
        assert has_min_role(Role.PARENT, Role.ADMIN) is False

    def test_guest_below_all(self):
        for role in [Role.LEAD, Role.PARENT, Role.COACH, Role.ADMIN, Role.OWNER]:
            assert has_min_role(Role.GUEST, role) is False


# ── Дозволи ───────────────────────────────────────────────────────────────────

class TestPermissions:

    def test_owner_can_edit_settings(self):
        assert can(Role.OWNER, "edit_settings") is True

    def test_admin_cannot_edit_settings(self):
        assert can(Role.ADMIN, "edit_settings") is False

    def test_coach_can_mark_attendance(self):
        assert can(Role.COACH, "mark_attendance") is True

    def test_parent_cannot_mark_attendance(self):
        assert can(Role.PARENT, "mark_attendance") is False

    def test_guest_can_create_lead(self):
        assert can(Role.GUEST, "create_lead") is True

    def test_admin_can_add_member(self):
        assert can(Role.ADMIN, "add_member") is True

    def test_coach_cannot_add_member(self):
        assert can(Role.COACH, "add_member") is False

    def test_owner_can_view_digest(self):
        assert can(Role.OWNER, "view_digest") is True

    def test_admin_cannot_view_digest(self):
        assert can(Role.ADMIN, "view_digest") is False

    def test_unknown_action_denied(self):
        assert can(Role.OWNER, "nonexistent_action") is False
        assert can(Role.GUEST, "nonexistent_action") is False

    def test_parent_can_view_own_payment(self):
        assert can(Role.PARENT, "view_own_payment") is True

    def test_guest_cannot_view_members(self):
        assert can(Role.GUEST, "view_members") is False

    def test_coach_can_view_members(self):
        assert can(Role.COACH, "view_members") is True

    def test_admin_can_send_payment_reminder(self):
        assert can(Role.ADMIN, "send_payment_reminder") is True

    def test_coach_cannot_send_payment_reminder(self):
        assert can(Role.COACH, "send_payment_reminder") is False


# ── RoleRegistry ─────────────────────────────────────────────────────────────

class TestRoleRegistry:

    def test_default_is_guest(self):
        reg = RoleRegistry()
        assert reg.get_role(99999) == Role.GUEST

    def test_set_and_get_role(self):
        reg = RoleRegistry()
        reg.set_role(12345, Role.OWNER)
        assert reg.get_role(12345) == Role.OWNER

    def test_is_owner(self):
        reg = RoleRegistry()
        reg.set_role(329214126, Role.OWNER)
        assert reg.is_owner(329214126) is True
        assert reg.is_owner(999) is False

    def test_is_coach_or_above(self):
        reg = RoleRegistry()
        reg.set_role(1, Role.COACH)
        reg.set_role(2, Role.ADMIN)
        reg.set_role(3, Role.PARENT)
        assert reg.is_coach_or_above(1) is True
        assert reg.is_coach_or_above(2) is True
        assert reg.is_coach_or_above(3) is False

    def test_is_admin_or_above(self):
        reg = RoleRegistry()
        reg.set_role(1, Role.ADMIN)
        reg.set_role(2, Role.OWNER)
        reg.set_role(3, Role.COACH)
        assert reg.is_admin_or_above(1) is True
        assert reg.is_admin_or_above(2) is True
        assert reg.is_admin_or_above(3) is False

    def test_load_from_list(self):
        from app.models import UserRole
        from datetime import datetime
        reg = RoleRegistry()
        user_roles = [
            UserRole(telegram_id=111, username="a", full_name="A", role=Role.COACH),
            UserRole(telegram_id=222, username="b", full_name="B", role=Role.PARENT),
        ]
        reg.load_from_list(user_roles)
        assert reg.get_role(111) == Role.COACH
        assert reg.get_role(222) == Role.PARENT
        assert reg.get_role(333) == Role.GUEST  # невідомий → GUEST

    def test_override_role(self):
        reg = RoleRegistry()
        reg.set_role(1, Role.GUEST)
        reg.set_role(1, Role.OWNER)
        assert reg.get_role(1) == Role.OWNER


# ── user_can (з глобальним реєстром) ─────────────────────────────────────────

class TestUserCan:

    def test_owner_can_all(self):
        reg = get_registry()
        reg.set_role(329214126, Role.OWNER)
        assert user_can(329214126, "view_digest") is True
        assert user_can(329214126, "edit_settings") is True
        assert user_can(329214126, "mark_attendance") is True

    def test_unknown_user_is_guest(self):
        # Невідомий user → GUEST → може тільки create_lead
        assert user_can(88888, "create_lead") is True
        assert user_can(88888, "mark_attendance") is False
