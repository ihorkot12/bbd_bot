import sys
import types
from types import SimpleNamespace

from app.services.form_poller import FormPollerService


def _install_fake_googleapiclient(monkeypatch, build_func):
    pkg = types.ModuleType("googleapiclient")
    discovery = types.ModuleType("googleapiclient.discovery")
    discovery.build = build_func
    pkg.discovery = discovery
    monkeypatch.setitem(sys.modules, "googleapiclient", pkg)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)


def test_get_forms_credentials_from_gspread_v6_http_client():
    creds = object()
    sheets_client = SimpleNamespace(http_client=SimpleNamespace(auth=creds))
    svc = FormPollerService(
        lead_service=object(),
        leads_repo=object(),
        sheets_client=sheets_client,
        form_id="form-id",
        sheets_fallback=False,
    )

    assert svc._get_forms_credentials() is creds


def test_forms_api_uses_http_client_credentials(monkeypatch):
    creds = object()
    called = {}

    class _Request:
        def execute(self):
            return {"responses": []}

    class _Responses:
        def list(self, formId):
            called["form_id"] = formId
            return _Request()

    class _Forms:
        def responses(self):
            return _Responses()

    class _Service:
        def forms(self):
            return _Forms()

    def fake_build(api_name, api_version, credentials):
        called["api_name"] = api_name
        called["api_version"] = api_version
        called["credentials"] = credentials
        return _Service()

    _install_fake_googleapiclient(monkeypatch, fake_build)

    sheets_client = SimpleNamespace(http_client=SimpleNamespace(auth=creds))
    svc = FormPollerService(
        lead_service=object(),
        leads_repo=object(),
        sheets_client=sheets_client,
        form_id="form-id",
        sheets_fallback=False,
    )

    assert svc._poll_from_forms_api() == 0
    assert called == {
        "api_name": "forms",
        "api_version": "v1",
        "credentials": creds,
        "form_id": "form-id",
    }


def test_forms_api_without_credentials_falls_back_to_sheets(monkeypatch):
    def fake_build(*args, **kwargs):
        raise AssertionError("Forms API should not be built without credentials")

    _install_fake_googleapiclient(monkeypatch, fake_build)

    svc = FormPollerService(
        lead_service=object(),
        leads_repo=object(),
        sheets_client=SimpleNamespace(),
        form_id="form-id",
        sheets_fallback=False,
    )
    monkeypatch.setattr(svc, "_poll_from_sheets", lambda: 3)

    assert svc._poll_from_forms_api() == 3
