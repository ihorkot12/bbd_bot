import importlib
import sys

import main


def test_railway_credentials_force_real_data_mode(monkeypatch, tmp_path):
    target = tmp_path / "credentials.json"
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "project")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv(
        "GOOGLE_CREDENTIALS_JSON",
        '{"type":"service_account","project_id":"test"}',
    )

    main._materialize_google_credentials()

    assert target.exists()
    assert main.os.environ["DRY_RUN"] == "false"
    assert main.os.environ["GOOGLE_CREDENTIALS_FILE"] == str(target)


def test_railway_without_credentials_fails_instead_of_using_test_data(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "project")
    monkeypatch.delenv("GOOGLE_CREDENTIALS_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_CREDENTIALS_JSON_BASE64", raising=False)
    monkeypatch.delenv("GOOGLE_CREDENTIALS_FILE", raising=False)

    try:
        main._materialize_google_credentials()
    except RuntimeError as error:
        assert "Google Sheets credentials are missing" in str(error)
    else:
        raise AssertionError("Railway must not silently use test data")


def test_runtime_overlay_contains_coach_template_catalog(monkeypatch):
    main._ensure_runtime_app()
    main._apply_local_overrides()
    monkeypatch.syspath_prepend(str(main.APP_ROOT))
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name)

    templates = importlib.import_module("app.services.templates")

    assert "birthday_channel_post_warm" in templates.DEFAULT_TEMPLATES
    assert "parent_absence_followup" in templates.DEFAULT_TEMPLATES
    assert "club_post_open_join" in templates.DEFAULT_TEMPLATES
