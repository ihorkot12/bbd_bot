"""
services/form_poller.py — опитування відповідей Google Form та конвертація у ліди.

Підтримує два режими:
  1. Polling через Google Forms API (потребує service account з доступом до форми)
  2. Fallback: читання аркуша form_responses у Sheets (якщо форма linked до Sheets)

Нові відповіді автоматично стають лідами з source="google_form".
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from app.models import (
    FormResponse,
    Lead,
    LeadStatus,
    ParticipantType,
    RegistrationSource,
)
from app.repositories.base import ILeadRepository
from app.services.leads import LeadService

log = logging.getLogger(__name__)

# Назва аркуша з відповідями форми (якщо прив'язано до Sheets)
FORM_RESPONSES_SHEET = "form_responses"


class FormPollerService:
    """
    Опитує нові відповіді Google Form і конвертує їх у ліди.

    Режими роботи:
      - sheets_fallback=True  → читає аркуш form_responses (простіше, рекомендовано)
      - sheets_fallback=False → намагається Google Forms API (потребує додаткових дозволів)
    """

    def __init__(
        self,
        lead_service: LeadService,
        leads_repo: ILeadRepository,
        sheets_client=None,          # gspread.Client або None
        spreadsheet_id: str = "",
        form_id: str = "",
        sheets_fallback: bool = True,
    ) -> None:
        self._lead_service = lead_service
        self._leads_repo   = leads_repo
        self._sheets_client = sheets_client
        self._spreadsheet_id = spreadsheet_id
        self._form_id        = form_id
        self._sheets_fallback = sheets_fallback
        self._last_processed: Optional[str] = None  # response_id

    def poll_and_process(self) -> int:
        """
        Опитує нові відповіді та обробляє їх.
        Повертає кількість нових лідів.
        """
        if self._sheets_fallback:
            return self._poll_from_sheets()
        else:
            return self._poll_from_forms_api()

    # ── Sheets fallback (рекомендований режим) ────────────────────────────────

    def _poll_from_sheets(self) -> int:
        """
        Читає аркуш form_responses, знаходить необроблені рядки (processed != true).
        Очікує колонки: response_id, submitted_at, participant_type,
                        child_name, parent_name, parent_phone, trial_date,
                        notes, processed
        """
        if not self._sheets_client:
            log.debug("FormPoller: sheets_client не налаштований, пропускаємо")
            return 0

        try:
            ss = self._sheets_client.open_by_key(self._spreadsheet_id)
            ws = ss.worksheet(FORM_RESPONSES_SHEET)
            records = ws.get_all_records(empty2zero=False, default_blank="")
        except Exception as e:
            log.warning("FormPoller: не вдалося прочитати '%s': %s", FORM_RESPONSES_SHEET, e)
            return 0

        new_leads = 0
        headers = ws.row_values(1)

        for i, row in enumerate(records, start=2):
            normalized = {k: str(v).strip() for k, v in row.items()}
            if normalized.get("processed", "").lower() in ("true", "1", "так"):
                continue

            try:
                fr = FormResponse.from_row(normalized)
                lead = self._convert_form_response(fr)
                if lead:
                    new_leads += 1
                    log.info(
                        "FormPoller: новий лід з форми — %s (response_id=%s)",
                        lead.child_name, fr.response_id
                    )
                    # Позначаємо рядок як оброблений
                    if "processed" in headers:
                        col_idx = headers.index("processed") + 1
                        ws.update_cell(i, col_idx, "true")
            except Exception as e:
                log.error("FormPoller: помилка обробки рядка %d: %s", i, e)

        return new_leads

    def _convert_form_response(self, fr: FormResponse) -> Optional[Lead]:
        """Конвертує FormResponse у Lead."""
        if not fr.child_name and not fr.parent_name:
            log.warning("FormPoller: порожній рядок response_id=%s, пропускаємо", fr.response_id)
            return None

        pt_raw = (fr.participant_type or "child").lower().strip()
        try:
            pt = ParticipantType(pt_raw)
        except ValueError:
            pt = ParticipantType.CHILD

        # Ім'я учасника: для дорослого child_name може бути їх власним ім'ям
        participant_name = fr.child_name or fr.parent_name
        contact_name = fr.parent_name if pt == ParticipantType.CHILD else fr.child_name

        lead = Lead(
            lead_id=str(uuid.uuid4())[:8],
            child_name=participant_name,
            parent_name=contact_name,
            participant_type=pt,
            parent_telegram_id=None,  # не відомий при реєстрації через форму
            parent_phone=fr.parent_phone or None,
            status=LeadStatus.TRIAL_SCHEDULED if fr.trial_date else LeadStatus.NEW,
            trial_date=fr.trial_date,
            trial_group_id=None,
            source=RegistrationSource.GOOGLE_FORM.value,
            notes=fr.notes or None,
            created_at=fr.submitted_at or datetime.now(),
        )
        self._leads_repo.add(lead)
        return lead

    # ── Google Forms API (потребує Forms API scope) ───────────────────────────

    def _poll_from_forms_api(self) -> int:
        """
        Опитування через Google Forms API.
        Потребує додаткового scope: https://www.googleapis.com/auth/forms.responses.readonly
        """
        try:
            from googleapiclient.discovery import build as _build
        except ImportError:
            log.warning("FormPoller: google-api-python-client не встановлено")
            return 0

        if not self._sheets_client or not self._form_id:
            return 0

        try:
            # Використовуємо credentials з gspread client
            creds = self._sheets_client.auth
            service = _build("forms", "v1", credentials=creds)
            resp = service.forms().responses().list(formId=self._form_id).execute()
            responses = resp.get("responses", [])
        except Exception as e:
            log.warning("FormPoller: Forms API помилка: %s", e)
            return 0

        new_leads = 0
        for response in responses:
            response_id = response.get("responseId", "")
            if response_id == self._last_processed:
                break

            # Парсимо відповіді (структура залежить від форми)
            answers = response.get("answers", {})
            form_data = self._parse_api_response(response_id, answers, response.get("createTime"))
            lead = self._convert_form_response(form_data)
            if lead:
                new_leads += 1

        if responses:
            self._last_processed = responses[0].get("responseId")

        return new_leads

    def _parse_api_response(
        self, response_id: str, answers: dict, create_time: Optional[str]
    ) -> FormResponse:
        """
        Парсить відповіді Forms API у FormResponse.
        Ключі answers: {questionId: {textAnswers: {answers: [{value: ...}]}}}
        """
        def _get_answer(qid: str) -> str:
            entry = answers.get(qid, {})
            texts = entry.get("textAnswers", {}).get("answers", [])
            return texts[0].get("value", "") if texts else ""

        if self._form_id == "1cgQPkWnNQwvnvtTc4GNUCXBjfedOBvnLe5jGXFD5ZiI":
            # Окрема коротка форма пробного тренування
            participant_type_raw = _get_answer("295cc80f") or "child"
            child_name           = _get_answer("72412f95")
            adult_name           = child_name
            parent_name          = _get_answer("1ed65a8a")
            parent_phone         = _get_answer("3fd02dd7")
            messenger            = _get_answer("0cb5b875")
            preferred_group      = ""
            preferred_trial_date = _get_answer("3325529b")
            medical_notes        = ""
            consent              = ""
            extra_comment        = _get_answer("7a40342a")
        else:
            # Повна реєстраційна форма
            # REGISTRATION_FORM_ID=1rdsZwpIY93fdXtd5e8-hnfn9Si7bt0fNtmKlfLlZCO8
            participant_type_raw = _get_answer("5a974455") or "child"
            child_name           = _get_answer("3880213e")
            adult_name           = _get_answer("3e5908f3")
            parent_name          = _get_answer("17737a30")
            parent_phone         = _get_answer("76f9440b")
            messenger            = _get_answer("4cf9a624")
            preferred_group      = _get_answer("512879c4")
            preferred_trial_date = _get_answer("41836858")
            medical_notes        = _get_answer("4f54eb4d")
            consent              = _get_answer("70c247da")
            extra_comment        = _get_answer("235a65db")

        pt_normalized = participant_type_raw.lower().strip()
        if pt_normalized in {"дорослий", "adult", "доросла", "взрослый"}:
            participant_type = "adult"
            child_name = adult_name or child_name
        else:
            participant_type = "child"

        trial_date = None
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                if preferred_trial_date:
                    trial_date = datetime.strptime(preferred_trial_date.strip(), fmt).date()
                break
            except ValueError:
                pass

        notes_parts = []
        if preferred_group:
            notes_parts.append(f"Бажана група/напрям: {preferred_group}")
        if preferred_trial_date:
            notes_parts.append(f"Бажана дата пробного: {preferred_trial_date}")
        if messenger:
            notes_parts.append(f"Telegram/Viber: {messenger}")
        if medical_notes:
            notes_parts.append(f"Медичні/організаційні примітки: {medical_notes}")
        if consent:
            notes_parts.append(f"Згода на обробку даних: {consent}")
        if extra_comment:
            notes_parts.append(f"Коментар: {extra_comment}")

        submitted_at = None
        if create_time:
            try:
                submitted_at = datetime.strptime(create_time[:19], "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                pass

        return FormResponse(
            response_id=response_id,
            submitted_at=submitted_at,
            participant_type=participant_type,
            child_name=child_name,
            parent_name=parent_name,
            parent_phone=parent_phone,
            trial_date=trial_date,
            notes=" | ".join(notes_parts),
            processed=False,
        )
