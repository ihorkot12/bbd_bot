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
