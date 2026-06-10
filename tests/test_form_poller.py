import sys
import types
from datetime import date
from types import SimpleNamespace

from app.models import Member, ParticipantType
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


class _FakeWorksheet:
    def __init__(self, records, headers=None):
        self.records = records
        self.headers = headers or list(records[0].keys())
        self.updated_cells = []

    def row_values(self, row):
        assert row == 1
        return self.headers

    def get_all_records(self, empty2zero=False, default_blank=""):
        return self.records

    def update_cell(self, row, col, value):
        self.updated_cells.append((row, col, value))
        if row == 1 and col == len(self.headers) + 1:
            self.headers.append(value)


class _FakeSpreadsheet:
    def __init__(self, worksheet):
        self.worksheet_obj = worksheet

    def worksheet(self, name):
        if name != "registration_responses":
            raise RuntimeError("missing sheet")
        return self.worksheet_obj


class _FakeSheetsClient:
    def __init__(self, worksheet):
        self.worksheet = worksheet

    def open_by_key(self, spreadsheet_id):
        return _FakeSpreadsheet(self.worksheet)


class _FakeSpreadsheetMap:
    def __init__(self, worksheets):
        self.worksheets = worksheets

    def worksheet(self, name):
        if name not in self.worksheets:
            raise RuntimeError("missing sheet")
        return self.worksheets[name]


class _FakeSheetsClientMap:
    def __init__(self, worksheets):
        self.worksheets = worksheets

    def open_by_key(self, spreadsheet_id):
        return _FakeSpreadsheetMap(self.worksheets)


class _FakeMemberRepo:
    def __init__(self, members=None):
        self.members = {m.member_id: m for m in members or []}

    def get_all(self):
        return list(self.members.values())

    def add(self, member):
        self.members[member.member_id] = member

    def upsert(self, member):
        self.members[member.member_id] = member


def _registration_poller(worksheet, members_repo):
    return FormPollerService(
        lead_service=object(),
        leads_repo=object(),
        members_repo=members_repo,
        sheets_client=_FakeSheetsClient(worksheet),
        spreadsheet_id="sheet-id",
        target="members",
        sheets_fallback=True,
        response_sheet_names=("registration_responses",),
    )


def test_registration_sheet_creates_members_for_multiple_children():
    worksheet = _FakeWorksheet(
        [
            {
                "response_id": "resp-1",
                "processed": "",
                "registration_type": "Батько/мати реєструє дитину/дітей",
                "parent_full_name": "Олена Петренко",
                "parent_phone": "+380991112233",
                "parent_email": "parent@example.com",
                "birthday_greeting_consent": "Так, можна",
                "photo_video_consent": "Так",
                "child_1_full_name": "Іван Петренко",
                "child_1_birth_date": "2015-06-10",
                "child_1_training_goal": "Дисципліна",
                "child_2_full_name": "Марія Петренко",
                "child_2_birth_date": "12.07.2017",
                "child_2_medical_notes": "Без обмежень",
            }
        ]
    )
    members_repo = _FakeMemberRepo()

    processed = _registration_poller(worksheet, members_repo).poll_and_process()

    members = sorted(members_repo.get_all(), key=lambda m: m.full_name)
    assert processed == 2
    assert [m.full_name for m in members] == ["Іван Петренко", "Марія Петренко"]
    assert members[0].birth_date == date(2015, 6, 10)
    assert members[0].participant_type == ParticipantType.CHILD
    assert members[0].parent_name == "Олена Петренко"
    assert members[0].birthday_greeting_enabled is True
    assert members[0].birthday_public_name == "Іван"
    assert "Дисципліна" in members[0].notes
    assert worksheet.updated_cells[-1] == (2, worksheet.headers.index("processed") + 1, "true")


def test_registration_sheet_understands_quiz_form_child_branches():
    worksheet = _FakeWorksheet(
        [
            {
                "response_id": "resp-quiz-2",
                "processed": "",
                "👋 Хто реєструється?": "👨‍👩‍👧 Батьки реєструють дитину/дітей",
                "ПІБ батька/матері або контактної особи": "Ірина Мельник",
                "Телефон для звʼязку": "+380671112233",
                "Email батьків": "parent@example.com",
                "Основний канал звʼязку": "Telegram",
                "👧 Скільки дітей реєструєте?": "2 дитини",
                "Дитина 1 із 2 — ПІБ": "Софія Мельник",
                "Дитина 1 із 2 — дата народження": "15.08.2014",
                "Дитина 1 із 2 — головна ціль тренувань": "Дисципліна і характер",
                "Дитина 2 із 2 — ПІБ": "Марко Мельник",
                "Дитина 2 із 2 — дата народження": "2017-09-20",
                "Дитина 2 із 2 — медичні примітки": "Алергій немає",
                "Чи можна вітати учасника з днем народження в каналі батьків?": "Так, можна 🎂",
                "Поточна група або час тренувань": "Дорослі, тестова група",
            }
        ]
    )
    members_repo = _FakeMemberRepo()

    processed = _registration_poller(worksheet, members_repo).poll_and_process()

    members = sorted(members_repo.get_all(), key=lambda m: m.full_name)
    assert processed == 2
    assert [m.full_name for m in members] == ["Марко Мельник", "Софія Мельник"]
    assert members[0].birth_date == date(2017, 9, 20)
    assert members[1].birth_date == date(2014, 8, 15)
    assert members[1].preferred_contact_channel == "Telegram"
    assert members[1].birthday_greeting_enabled is True
    assert "Бажана група/час: Дорослі, тестова група" in members[1].notes


def test_registration_sheet_creates_adult_member():
    worksheet = _FakeWorksheet(
        [
            {
                "response_id": "resp-adult",
                "processed": "",
                "registration_type": "Дорослий учасник",
                "adult_full_name": "Андрій Коваленко",
                "adult_birth_date": "1991-03-05",
                "parent_phone": "+380671234567",
                "parent_email": "adult@example.com",
                "birthday_greeting_consent": "ні",
                "adult_training_goal": "Форма і витривалість",
            }
        ]
    )
    members_repo = _FakeMemberRepo()

    processed = _registration_poller(worksheet, members_repo).poll_and_process()

    member = members_repo.get_all()[0]
    assert processed == 1
    assert member.full_name == "Андрій Коваленко"
    assert member.participant_type == ParticipantType.ADULT
    assert member.birth_date == date(1991, 3, 5)
    assert member.parent_name is None
    assert member.parent_phone == "+380671234567"
    assert member.birthday_greeting_enabled is False
    assert "Форма і витривалість" in member.notes


def test_registration_sheet_updates_existing_member_instead_of_duplicate():
    existing = Member(
        member_id="mem-1",
        full_name="Іван Петренко",
        birth_date=date(2015, 6, 10),
        participant_type=ParticipantType.CHILD,
        parent_name="Олена",
        parent_phone="+380991112233",
    )
    worksheet = _FakeWorksheet(
        [
            {
                "response_id": "resp-2",
                "processed": "",
                "registration_type": "Дитина",
                "parent_full_name": "Олена Петренко",
                "parent_phone": "+380991112233",
                "parent_email": "new@example.com",
                "child_1_full_name": "Іван Петренко",
                "child_1_birth_date": "10.06.2015",
                "birthday_greeting_consent": "так",
            }
        ]
    )
    members_repo = _FakeMemberRepo([existing])

    processed = _registration_poller(worksheet, members_repo).poll_and_process()

    members = members_repo.get_all()
    assert processed == 1
    assert len(members) == 1
    assert members[0].member_id == "mem-1"
    assert members[0].parent_email == "new@example.com"
    assert members[0].birthday_greeting_enabled is True


def test_registration_poller_reads_existing_registrations_sheet_format():
    worksheet = _FakeWorksheet(
        [
            {
                "registration_id": "reg-1",
                "created_at": "2026-06-08 10:00",
                "participant_type": "child",
                "child_full_name": "Марко Іваненко",
                "birth_date": "2016-09-20",
                "birthday_greeting_enabled": "true",
                "birthday_public_name": "Марко",
                "photo_video_consent": "yes",
                "parent_full_name": "Ірина Іваненко",
                "parent_phone": "+380501112233",
                "school_class_or_occupation": "3 клас",
                "previous_sport_experience": "Плавання",
                "training_goal": "Впевненість",
                "medical_notes": "Алергій немає",
                "consent_personal_data": "так",
            }
        ]
    )
    members_repo = _FakeMemberRepo()
    svc = FormPollerService(
        lead_service=object(),
        leads_repo=object(),
        members_repo=members_repo,
        sheets_client=_FakeSheetsClientMap({"registrations": worksheet}),
        spreadsheet_id="sheet-id",
        target="members",
        sheets_fallback=True,
    )

    processed = svc.poll_and_process()

    member = members_repo.get_all()[0]
    assert processed == 1
    assert member.full_name == "Марко Іваненко"
    assert member.birth_date == date(2016, 9, 20)
    assert member.birthday_public_name == "Марко"
    assert "3 клас" in member.notes
    assert "Плавання" in member.notes
    assert "Алергій немає" in member.notes
    assert worksheet.headers[-1] == "processed"


def test_forms_api_registration_imports_member_and_skips_seen_response(monkeypatch):
    creds = object()

    form = {
        "items": [
            {"title": "Тип учасника", "questionItem": {"question": {"questionId": "q_type"}}},
            {"title": "ПІБ дитини", "questionItem": {"question": {"questionId": "q_child"}}},
            {"title": "Дата народження учасника", "questionItem": {"question": {"questionId": "q_birth"}}},
            {"title": "ПІБ батька/матері або контактної особи", "questionItem": {"question": {"questionId": "q_parent"}}},
            {"title": "Телефон для звʼязку", "questionItem": {"question": {"questionId": "q_phone"}}},
            {"title": "Email батьків / дорослого учасника", "questionItem": {"question": {"questionId": "q_email"}}},
            {"title": "Як підписувати учасника у привітанні?", "questionItem": {"question": {"questionId": "q_public_name"}}},
            {"title": "Головна ціль тренувань", "questionItem": {"question": {"questionId": "q_goal"}}},
        ]
    }
    responses_payload = {
        "responses": [
            {
                "responseId": "forms-resp-1",
                "createTime": "2026-06-09T10:00:00Z",
                "answers": {
                    "q_type": {"textAnswers": {"answers": [{"value": "Дитина"}]}},
                    "q_child": {"textAnswers": {"answers": [{"value": "Софія Мельник"}]}},
                    "q_birth": {"textAnswers": {"answers": [{"value": "2014-08-15"}]}},
                    "q_parent": {"textAnswers": {"answers": [{"value": "Олена Мельник"}]}},
                    "q_phone": {"textAnswers": {"answers": [{"value": "+380671112233"}]}},
                    "q_email": {"textAnswers": {"answers": [{"value": "parent@example.com"}]}},
                    "q_public_name": {"textAnswers": {"answers": [{"value": "Софія"}]}},
                    "q_goal": {"textAnswers": {"answers": [{"value": "Дисципліна"}]}},
                },
            }
        ]
    }

    class _Request:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class _Responses:
        def list(self, formId):
            return _Request(responses_payload)

    class _Forms:
        def get(self, formId):
            return _Request(form)

        def responses(self):
            return _Responses()

    class _Service:
        def forms(self):
            return _Forms()

    def fake_build(api_name, api_version, credentials):
        return _Service()

    _install_fake_googleapiclient(monkeypatch, fake_build)

    members_repo = _FakeMemberRepo()
    svc = FormPollerService(
        lead_service=object(),
        leads_repo=object(),
        members_repo=members_repo,
        sheets_client=SimpleNamespace(http_client=SimpleNamespace(auth=creds)),
        form_id="form-id",
        sheets_fallback=False,
        target="members",
    )

    assert svc.poll_and_process() == 1
    assert svc.poll_and_process() == 0

    member = members_repo.get_all()[0]
    assert member.full_name == "Софія Мельник"
    assert member.birth_date == date(2014, 8, 15)
    assert member.parent_name == "Олена Мельник"
    assert member.parent_phone == "+380671112233"
    assert member.parent_email == "parent@example.com"
    assert member.birthday_public_name == "Софія"
    assert "Форма: forms-resp-1" in member.notes
    assert "Дисципліна" in member.notes
