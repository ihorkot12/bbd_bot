"""
tests/test_templates.py — unit-тести рендерингу шаблонів.
"""
import pytest
from app.services.templates import TemplateService, DEFAULT_TEMPLATES
from app.models import MessageTemplate
from app.repositories.stub import _StubTemplateRepo


@pytest.fixture
def empty_repo():
    return _StubTemplateRepo()


@pytest.fixture
def svc(empty_repo):
    return TemplateService(empty_repo)


class TestTemplateServiceDefaults:

    def test_get_known_default(self, svc):
        text = svc.get("payment_reminder")
        assert text != ""
        assert "Black Bear Dojo" in text or "{" in text

    def test_get_unknown_returns_empty(self, svc):
        text = svc.get("nonexistent_template_xyz")
        assert text == ""

    def test_render_with_variables(self, svc):
        result = svc.render(
            "payment_reminder",
            parent_name="Тестовий Батько",
            period="Травень 2026",
            amount_due=1500,
            amount_paid=0,
            balance=1500,
            status="❌ Не сплачено",
        )
        assert "Тестовий Батько" in result

    def test_render_missing_variable_returns_template(self, svc):
        # Якщо змінна відсутня — повертає нерендерений текст без падіння
        result = svc.render("payment_reminder")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_render_unknown_template(self, svc):
        result = svc.render("no_such_template")
        assert "no_such_template" in result

    def test_list_names_contains_defaults(self, svc):
        names = svc.list_names()
        assert "payment_reminder" in names
        assert "trial_confirmation" in names
        assert "attendance_coach_reminder" in names
        assert "daily_digest_header" in names

    def test_invalidate_cache(self, svc):
        # Заповнюємо кеш
        svc.get("payment_reminder")
        svc.get("trial_confirmation")
        svc.invalidate_cache()
        assert svc._cache == {}

    def test_all_defaults_renderable(self, svc):
        """Перевіряємо що жоден шаблон не кидає виняток при рендері."""
        for name in DEFAULT_TEMPLATES:
            result = svc.render(name)  # без змінних → може повернути незаповнений текст
            assert isinstance(result, str)


class TestTemplateServiceFromRepo:

    def test_custom_template_overrides_default(self, empty_repo):
        custom = MessageTemplate(
            template_id="t1",
            name="payment_reminder",
            text="CUSTOM: Сплатіть {amount_due} грн!",
            variables="amount_due",
        )
        empty_repo.upsert(custom)
        svc = TemplateService(empty_repo)
        result = svc.render("payment_reminder", amount_due=999)
        assert "CUSTOM" in result
        assert "999" in result

    def test_repo_template_cached(self, empty_repo):
        custom = MessageTemplate(
            template_id="t2", name="my_template",
            text="Cached: {val}", variables="val"
        )
        empty_repo.upsert(custom)
        svc = TemplateService(empty_repo)
        svc.get("my_template")  # перший виклик — читає з repo, кешує
        # Видаляємо з repo, але кеш все ще є
        empty_repo._data.pop("my_template", None)
        result = svc.get("my_template")
        assert result == "Cached: {val}"


class TestDefaultTemplatesCoverage:
    """Перевіряємо покриття ключових шаблонів."""

    @pytest.mark.parametrize("name", [
        "payment_reminder",
        "payment_overdue",
        "payment_partial",
        "trial_confirmation",
        "trial_reminder",
        "trial_day_reminder",
        "after_trial_owner",
        "attendance_coach_reminder",
        "attendance_unclosed_alert",
        "inactivity_7_days",
        "inactivity_14_days",
        "inactivity_21_days",
        "info_address",
        "info_schedule",
        "info_price",
        "info_contact",
        "info_first_visit",
        "event_announcement",
        "event_reminder",
    ])
    def test_template_exists(self, name):
        assert name in DEFAULT_TEMPLATES
        assert len(DEFAULT_TEMPLATES[name]) > 10, f"Шаблон '{name}' занадто короткий"
