"""
services/form_poller.py — опитування відповідей Google Form та конвертація у ліди.

Підтримує два режими:
  1. Polling через Google Forms API (потребує service account з доступом до форми)
  2. Fallback: читання аркуша form_responses у Sheets (якщо форма linked до Sheets)

Нові відповіді автоматично стають лідами з source="google_form".
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Sequence

from app.models import (
    FormResponse,
    Lead,
    LeadStatus,
    Member,
    ParticipantType,
    RegistrationSource,
)
from app.repositories.base import ILeadRepository, IMemberRepository
from app.services.leads import LeadService

log = logging.getLogger(__name__)

# Назва аркуша з відповідями форми (якщо прив'язано до Sheets)
FORM_RESPONSES_SHEET = "form_responses"
REGISTRATION_RESPONSES_SHEET = "registration_responses"
FORM_RESPONSE_SHEET_CANDIDATES = (
    REGISTRATION_RESPONSES_SHEET,
    "Form Responses 1",
    "Відповіді форми 1",
    "Ответы на форму 1",
    "registrations",
    FORM_RESPONSES_SHEET,
)
TARGET_LEADS = "leads"
TARGET_MEMBERS = "members"


@dataclass
class _RegistrationContact:
    parent_name: str = ""
    phone: str = ""
    email: str = ""
    telegram_username: str = ""
    viber: str = ""
    preferred_channel: str = ""
    emergency_contact: str = ""


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
        members_repo: Optional[IMemberRepository] = None,
        target: str = TARGET_LEADS,
        response_sheet_names: Optional[Sequence[str]] = None,
    ) -> None:
        self._lead_service = lead_service
        self._leads_repo   = leads_repo
        self._members_repo = members_repo
        self._sheets_client = sheets_client
        self._spreadsheet_id = spreadsheet_id
        self._form_id        = form_id
        self._sheets_fallback = sheets_fallback
        self._target = target
        if response_sheet_names is not None:
            self._response_sheet_names = tuple(response_sheet_names)
        elif target == TARGET_MEMBERS:
            self._response_sheet_names = FORM_RESPONSE_SHEET_CANDIDATES
        else:
            self._response_sheet_names = (FORM_RESPONSES_SHEET,)
        self._last_processed: Optional[str] = None  # response_id

    def poll_and_process(self) -> int:
        """
        Опитує нові відповіді та обробляє їх.
        Повертає кількість нових лідів.
        """
        if self._sheets_fallback:
            return self._poll_from_sheets()
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
            ws, sheet_name = self._open_response_sheet(ss)
            headers = [str(h).strip() for h in ws.row_values(1)]
            headers = self._ensure_processed_header(ws, headers)
            records = ws.get_all_records(empty2zero=False, default_blank="")
        except Exception as e:
            log.warning("FormPoller: не вдалося прочитати відповіді форми: %s", e)
            return 0

        processed_count = 0
        processed_col = self._header_index(headers, ("processed", "оброблено"))

        for i, row in enumerate(records, start=2):
            normalized = {k: str(v).strip() for k, v in row.items()}
            if _truthy_text(_first_value(normalized, ("processed", "оброблено")), default=False):
                continue

            try:
                if self._target == TARGET_MEMBERS:
                    response_id = _response_id_for_row(normalized, i)
                    created = self._convert_registration_row_to_members(normalized, response_id)
                    processed_count += created
                    log.info(
                        "FormPoller: оброблено повну реєстрацію з '%s' — %d учасн. (response_id=%s)",
                        sheet_name,
                        created,
                        response_id,
                    )
                else:
                    fr = FormResponse.from_row(normalized)
                    lead = self._convert_form_response(fr)
                    if lead:
                        processed_count += 1
                        log.info(
                            "FormPoller: новий лід з форми — %s (response_id=%s)",
                            lead.child_name, fr.response_id
                        )

                if processed_col:
                    ws.update_cell(i, processed_col, "true")
            except Exception as e:
                log.error("FormPoller: помилка обробки рядка %d: %s", i, e)

        return processed_count

    def _open_response_sheet(self, spreadsheet):
        last_error: Optional[Exception] = None
        for sheet_name in self._response_sheet_names:
            try:
                return spreadsheet.worksheet(sheet_name), sheet_name
            except Exception as e:
                last_error = e
        raise RuntimeError(
            "не знайдено аркуш відповідей форми: "
            + ", ".join(self._response_sheet_names)
        ) from last_error

    @staticmethod
    def _header_index(headers: Sequence[str], aliases: Sequence[str]) -> Optional[int]:
        normalized = {_normalize_key(header): idx + 1 for idx, header in enumerate(headers) if header}
        for alias in aliases:
            idx = normalized.get(_normalize_key(alias))
            if idx:
                return idx
        return None

    def _ensure_processed_header(self, worksheet, headers: List[str]) -> List[str]:
        if self._header_index(headers, ("processed", "оброблено")):
            return headers
        col_idx = len(headers) + 1
        worksheet.update_cell(1, col_idx, "processed")
        return [*headers, "processed"]

    def _convert_registration_row_to_members(self, row: dict, response_id: str) -> int:
        if not self._members_repo:
            log.warning("FormPoller: members_repo не налаштований для повної реєстрації")
            return 0

        members = self._members_from_registration_row(row, response_id)
        processed = 0
        for member in members:
            if self._upsert_registration_member(member):
                processed += 1
        return processed

    def _members_from_registration_row(self, row: dict, response_id: str) -> List[Member]:
        contact = _registration_contact_from_row(row)
        registration_type = _first_value(row, _ALIASES["registration_type"]).lower()
        is_adult = "adult" in registration_type or "дорос" in registration_type

        adult_name = _first_value(row, _ALIASES["adult_full_name"])
        child_names = [
            _first_value(row, _child_aliases(idx, "full_name"))
            for idx in range(1, 4)
        ]
        old_child_name = _first_value(row, _ALIASES["child_full_name"])
        has_child = any(child_names) or bool(old_child_name)
        if adult_name and not has_child:
            is_adult = True

        common = _common_registration_data(row, response_id)
        submitted_at = _first_value(row, _ALIASES["submitted_at"])
        members: List[Member] = []

        if is_adult:
            full_name = adult_name or old_child_name
            if not full_name:
                log.warning("FormPoller: повна реєстрація без ПІБ дорослого (response_id=%s)", response_id)
                return []
            birth_date = _parse_date_text(_first_value(row, _ALIASES["adult_birth_date"]) or _first_value(row, _ALIASES["birth_date"]))
            notes = _registration_notes(
                row,
                response_id=response_id,
                participant_label="Дорослий учасник",
                submitted_at=submitted_at,
                indexed_prefix=None,
            )
            members.append(
                Member(
                    member_id=str(uuid.uuid4())[:8],
                    full_name=full_name,
                    birth_date=birth_date,
                    participant_type=ParticipantType.ADULT,
                    parent_name=None,
                    parent_phone=contact.phone or None,
                    parent_email=contact.email or None,
                    parent_telegram_username=contact.telegram_username or None,
                    parent_viber=contact.viber or None,
                    preferred_contact_channel=contact.preferred_channel or None,
                    active=True,
                    join_date=date.today(),
                    birthday_greeting_enabled=common["birthday_enabled"],
                    birthday_public_name=_public_birthday_name(
                        _first_value(row, _ALIASES["adult_birthday_public_name"])
                        or _first_value(row, _ALIASES["birthday_public_name"]),
                        full_name,
                    ),
                    photo_video_consent=common["photo_video_consent"] or None,
                    registration_source=RegistrationSource.GOOGLE_FORM.value,
                    notes=notes,
                )
            )
            return members

        if old_child_name and not child_names[0]:
            child_names[0] = old_child_name

        for idx, full_name in enumerate(child_names, start=1):
            if not full_name:
                continue
            birth_date = _parse_date_text(
                _first_value(row, _child_aliases(idx, "birth_date"))
                or _first_value(row, _ALIASES["birth_date"])
            )
            notes = _registration_notes(
                row,
                response_id=response_id,
                participant_label=f"Дитина {idx}",
                submitted_at=submitted_at,
                indexed_prefix=f"child_{idx}",
            )
            members.append(
                Member(
                    member_id=str(uuid.uuid4())[:8],
                    full_name=full_name,
                    birth_date=birth_date,
                    participant_type=ParticipantType.CHILD,
                    parent_name=contact.parent_name or None,
                    parent_phone=contact.phone or None,
                    parent_email=contact.email or None,
                    parent_telegram_username=contact.telegram_username or None,
                    parent_viber=contact.viber or None,
                    preferred_contact_channel=contact.preferred_channel or None,
                    active=True,
                    join_date=date.today(),
                    birthday_greeting_enabled=common["birthday_enabled"],
                    birthday_public_name=_public_birthday_name(
                        _first_value(row, _child_aliases(idx, "birthday_public_name"))
                        or _first_value(row, _ALIASES["birthday_public_name"]),
                        full_name,
                    ),
                    photo_video_consent=common["photo_video_consent"] or None,
                    registration_source=RegistrationSource.GOOGLE_FORM.value,
                    notes=notes,
                )
            )

        if not members:
            log.warning("FormPoller: повна реєстрація без учасників (response_id=%s)", response_id)
        return members

    def _upsert_registration_member(self, incoming: Member) -> bool:
        existing = self._find_existing_member(incoming)
        if existing:
            _merge_member(existing, incoming)
            self._members_repo.upsert(existing)
            log.info("FormPoller: оновлено учасника з форми — %s (%s)", existing.full_name, existing.member_id)
            return True

        self._members_repo.add(incoming)
        log.info("FormPoller: додано учасника з форми — %s (%s)", incoming.full_name, incoming.member_id)
        return True

    def _find_existing_member(self, incoming: Member) -> Optional[Member]:
        if not self._members_repo:
            return None

        incoming_name = _normalize_name(incoming.full_name)
        incoming_phone = _normalize_phone(incoming.parent_phone or "")
        for member in self._members_repo.get_all():
            if _normalize_name(member.full_name) != incoming_name:
                continue
            if incoming.birth_date and member.birth_date and incoming.birth_date == member.birth_date:
                return member
            member_phone = _normalize_phone(member.parent_phone or "")
            if incoming_phone and member_phone and incoming_phone == member_phone:
                return member
        return None

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
            creds = self._get_forms_credentials()
            if creds is None:
                log.info(
                    "FormPoller: credentials для Forms API недоступні, пробуємо Sheets fallback"
                )
                return self._poll_from_sheets()

            service = _build("forms", "v1", credentials=creds)
            if self._target == TARGET_MEMBERS:
                return self._poll_member_registrations_from_forms_api(service)
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

    def _poll_member_registrations_from_forms_api(self, service) -> int:
        try:
            form = service.forms().get(formId=self._form_id).execute()
            question_titles = _question_titles_from_form(form)
            resp = service.forms().responses().list(formId=self._form_id).execute()
            responses = resp.get("responses", [])
        except Exception as e:
            log.warning("FormPoller: не вдалося прочитати повну реєстрацію через Forms API: %s", e)
            return self._poll_from_sheets()

        processed = 0
        for response in responses:
            response_id = response.get("responseId", "")
            if not response_id or self._registration_response_seen(response_id):
                continue

            row = _registration_row_from_api_response(response, question_titles)
            created = self._convert_registration_row_to_members(row, response_id)
            if created:
                processed += created
                log.info(
                    "FormPoller: Forms API імпортовано повну реєстрацію — %d учасн. (response_id=%s)",
                    created,
                    response_id,
                )

        return processed

    def _registration_response_seen(self, response_id: str) -> bool:
        if not self._members_repo or not response_id:
            return False
        marker = f"Форма: {response_id}"
        for member in self._members_repo.get_all():
            if marker in (member.notes or ""):
                return True
        return False

    def _get_forms_credentials(self):
        """Повертає google-auth credentials із різних версій gspread.Client."""
        if not self._sheets_client:
            return None

        candidates = [self._sheets_client]
        http_client = getattr(self._sheets_client, "http_client", None)
        if http_client is not None:
            candidates.append(http_client)
            session = getattr(http_client, "session", None)
            if session is not None:
                candidates.append(session)

        session = getattr(self._sheets_client, "session", None)
        if session is not None:
            candidates.append(session)

        for obj in candidates:
            for attr in ("auth", "credentials", "creds"):
                creds = getattr(obj, attr, None)
                if creds is not None:
                    return creds
        return None

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


_ALIASES = {
    "response_id": (
        "response_id",
        "registration_id",
        "Response ID",
        "ID відповіді",
        "Номер відповіді",
    ),
    "submitted_at": (
        "submitted_at",
        "created_at",
        "Timestamp",
        "Позначка часу",
        "Відмітка часу",
        "Дата заповнення",
        "Час заповнення",
    ),
    "registration_type": (
        "registration_type",
        "participant_type",
        "Хто реєструється?",
        "Тип учасника",
        "Кого реєструєте?",
        "Хто заповнює форму?",
        "Формат реєстрації",
    ),
    "parent_full_name": (
        "parent_full_name",
        "parent_name",
        "ПІБ батька/матері або контактної особи",
        "ПІБ батька/матері",
        "ПІБ контактної особи",
        "Контактна особа",
    ),
    "parent_phone": (
        "parent_phone",
        "Телефон для звʼязку",
        "Телефон для зв'язку",
        "Телефон",
        "Номер телефону",
        "Контактний телефон",
        "Телефон батьків",
        "Телефон контактної особи",
    ),
    "parent_email": (
        "parent_email",
        "Email батьків / дорослого учасника",
        "Email батьків",
        "Email",
        "Електронна пошта",
        "Пошта",
    ),
    "parent_telegram_username": (
        "parent_telegram_username",
        "Telegram",
        "Telegram username",
        "Нік у Telegram",
        "Telegram/Viber",
    ),
    "parent_viber": (
        "parent_viber",
        "Viber контакт",
        "Viber",
    ),
    "preferred_contact_channel": (
        "preferred_contact_channel",
        "Основний канал зв'язку",
        "Основний канал звʼязку",
        "Зручний канал зв'язку",
        "Зручний канал звʼязку",
        "Канал зв'язку",
        "Канал звʼязку",
    ),
    "emergency_contact": (
        "emergency_contact",
        "Резервний телефон / друга контактна особа",
        "Екстрений контакт",
        "Кому дзвонити у разі потреби",
        "Додатковий телефон на випадок форс-мажору",
    ),
    "child_full_name": (
        "child_name",
        "child_full_name",
        "ПІБ дитини",
        "Прізвище та ім'я дитини",
        "Прізвище та імʼя дитини",
    ),
    "adult_full_name": (
        "adult_full_name",
        "ПІБ дорослого учасника",
        "Прізвище та ім'я дорослого учасника",
        "ПІБ учасника (для дорослого)",
    ),
    "birth_date": (
        "birth_date",
        "Дата народження учасника",
        "Дата народження",
    ),
    "adult_birth_date": (
        "adult_birth_date",
        "Дата народження дорослого учасника",
        "Дата народження учасника",
        "Дата народження",
    ),
    "adult_birthday_public_name": (
        "adult_birthday_public_name",
        "Як підписати дорослого у привітанні з ДН",
        "Ім'я для привітання дорослого",
        "Імʼя для привітання дорослого",
    ),
    "preferred_group": (
        "preferred_group",
        "Поточна група або час тренувань",
        "Поточна група",
        "Поточний час тренувань",
        "Бажана група",
        "Група",
        "Бажана група або напрям",
        "Зручні дні/час тренувань",
        "Бажана група/напрям",
    ),
    "birthday_greeting_consent": (
        "birthday_greeting_consent",
        "birthday_greeting_enabled",
        "Чи можна вітати учасника з днем народження в каналі батьків?",
        "Чи можна вітати з днем народження?",
        "Вітати з днем народження в каналі батьків?",
        "Згода на привітання з ДН",
    ),
    "photo_video_consent": (
        "photo_video_consent",
        "Згода на фото/відео",
        "Чи можна використовувати фото/відео з тренувань?",
        "Згода на фото та відео",
    ),
    "data_processing_consent": (
        "data_processing_consent",
        "consent_personal_data",
        "Згода на обробку персональних даних",
        "Згода на обробку даних",
    ),
    "notes": (
        "notes",
        "Коментар",
        "Додатковий коментар",
        "Що тренеру важливо знати?",
    ),
    "school_class_or_occupation": (
        "school_class_or_occupation",
        "Школа/клас або рід занять",
        "Школа/клас",
        "Рід занять",
    ),
    "previous_sport_experience": (
        "previous_sport_experience",
        "Попередній спортивний досвід",
        "Досвід спорту",
    ),
    "training_goal": (
        "training_goal",
        "Головна ціль тренувань",
        "Мета тренувань",
        "Що хочете отримати від тренувань?",
    ),
    "medical_notes": (
        "medical_notes",
        "Важливі медичні або організаційні примітки",
        "Медичні примітки",
        "Здоров'я/обмеження",
        "Здоровʼя/обмеження",
    ),
    "preferred_trial_date": (
        "preferred_trial_date",
        "Бажана дата пробного",
        "Бажана дата першого тренування",
        "Бажана дата першого тренування / старту в групі",
        "Бажана дата старту в групі",
    ),
    "birthday_public_name": (
        "birthday_public_name",
        "Як підписувати учасника у привітанні?",
        "Як підписувати учасника у привітанні з ДН?",
        "Ім'я для привітання",
        "Імʼя для привітання",
    ),
}

_CHILD_FIELD_ALIASES = {
    "full_name": ("ПІБ", "ПІБ дитини", "Прізвище та ім'я", "Прізвище та імʼя"),
    "birth_date": ("Дата народження", "ДН"),
    "school_class": ("Школа/клас", "Клас", "Вік/клас"),
    "previous_sport_experience": ("Попередній спортивний досвід", "Досвід спорту"),
    "training_goal": ("Мета тренувань", "Головна ціль тренувань", "Що хочете отримати від тренувань?"),
    "medical_notes": ("Медичні примітки", "Здоров'я/обмеження", "Здоровʼя/обмеження"),
    "birthday_public_name": ("Ім'я для привітання", "Імʼя для привітання", "Як підписати у привітанні з ДН"),
}

_ADULT_NOTE_ALIASES = {
    "school_class": (
        "adult_occupation",
        "school_class_or_occupation",
        "Рід занять дорослого учасника",
        "Рід занять",
    ),
    "previous_sport_experience": (
        "adult_previous_sport_experience",
        "previous_sport_experience",
        "Попередній спортивний досвід дорослого учасника",
        "Попередній спортивний досвід",
    ),
    "training_goal": (
        "adult_training_goal",
        "training_goal",
        "Мета тренувань дорослого учасника",
        "Головна ціль тренувань",
        "Мета тренувань",
    ),
    "medical_notes": (
        "adult_medical_notes",
        "medical_notes",
        "Медичні примітки дорослого учасника",
        "Медичні примітки",
        "Здоров'я/обмеження",
        "Здоровʼя/обмеження",
    ),
}


def _question_titles_from_form(form: dict) -> dict[str, str]:
    titles: dict[str, str] = {}
    for item in form.get("items", []):
        title = str(item.get("title", "")).strip()
        question = item.get("questionItem", {}).get("question", {})
        question_id = str(question.get("questionId", "")).strip()
        if question_id and title:
            titles[question_id] = title
    return titles


def _registration_row_from_api_response(response: dict, question_titles: dict[str, str]) -> dict[str, str]:
    response_id = str(response.get("responseId", "")).strip()
    created_at = str(response.get("createTime", "")).strip()
    row = {
        "response_id": response_id,
        "registration_id": response_id,
        "submitted_at": created_at,
        "created_at": created_at,
        "source": "google_form",
        "form_type": "full_registration",
    }
    for question_id, answer in response.get("answers", {}).items():
        title = question_titles.get(question_id, question_id)
        value = _api_answer_text(answer)
        if title and value:
            row[title] = value
    return row


def _api_answer_text(answer: dict) -> str:
    text_answers = answer.get("textAnswers", {}).get("answers", [])
    values = [str(item.get("value", "")).strip() for item in text_answers]
    return "; ".join(value for value in values if value)


def _normalize_key(value: object) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("’", "'").replace("ʼ", "'").replace("`", "'")
    text = re.sub(r"[^0-9a-zа-яіїєґ'\-]+", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _first_value(row: dict, aliases: Sequence[str]) -> str:
    normalized = {
        _normalize_key(key): str(value).strip()
        for key, value in row.items()
        if str(value).strip()
    }
    for alias in aliases:
        value = normalized.get(_normalize_key(alias))
        if value:
            return value
    for alias in aliases:
        alias_key = _normalize_key(alias)
        if len(alias_key) < 8:
            continue
        for key, value in normalized.items():
            if alias_key in key:
                return value
    return ""


def _child_aliases(index: int, field: str) -> tuple[str, ...]:
    base = (
        f"child_{index}_{field}",
        f"child{index}_{field}",
        f"Дитина {index}: {_CHILD_FIELD_ALIASES[field][0]}",
        f"Дитина {index} - {_CHILD_FIELD_ALIASES[field][0]}",
        f"Дитина {index} — {_CHILD_FIELD_ALIASES[field][0]}",
    )
    expanded = []
    for label in _CHILD_FIELD_ALIASES[field]:
        expanded.extend(
            (
                f"Дитина {index}: {label}",
                f"Дитина {index} - {label}",
                f"Дитина {index} — {label}",
                f"{label} дитини {index}",
            )
        )
        for total in (2, 3):
            expanded.extend(
                (
                    f"Дитина {index} із {total}: {label}",
                    f"Дитина {index} із {total} - {label}",
                    f"Дитина {index} із {total} — {label}",
                    f"{label} дитини {index} із {total}",
                )
            )
    return (*base, *expanded)


def _registration_contact_from_row(row: dict) -> _RegistrationContact:
    return _RegistrationContact(
        parent_name=_first_value(row, _ALIASES["parent_full_name"]),
        phone=_first_value(row, _ALIASES["parent_phone"]),
        email=_first_value(row, _ALIASES["parent_email"]),
        telegram_username=_first_value(row, _ALIASES["parent_telegram_username"]),
        viber=_first_value(row, _ALIASES["parent_viber"]),
        preferred_channel=_first_value(row, _ALIASES["preferred_contact_channel"]),
        emergency_contact=_first_value(row, _ALIASES["emergency_contact"]),
    )


def _common_registration_data(row: dict, response_id: str) -> dict:
    birthday_consent = _first_value(row, _ALIASES["birthday_greeting_consent"])
    return {
        "response_id": response_id,
        "birthday_enabled": _truthy_text(birthday_consent, default=True),
        "photo_video_consent": _first_value(row, _ALIASES["photo_video_consent"]),
    }


def _registration_notes(
    row: dict,
    *,
    response_id: str,
    participant_label: str,
    submitted_at: str,
    indexed_prefix: Optional[str],
) -> str:
    parts = [f"Форма: {response_id}", f"Учасник у формі: {participant_label}"]
    if submitted_at:
        parts.append(f"Заповнено: {submitted_at}")

    if indexed_prefix:
        idx = indexed_prefix.split("_")[-1]
        _append_note(parts, "Школа/клас", _first_value(row, _child_aliases(int(idx), "school_class")) or _first_value(row, _ALIASES["school_class_or_occupation"]))
        _append_note(parts, "Досвід спорту", _first_value(row, _child_aliases(int(idx), "previous_sport_experience")) or _first_value(row, _ALIASES["previous_sport_experience"]))
        _append_note(parts, "Мета тренувань", _first_value(row, _child_aliases(int(idx), "training_goal")) or _first_value(row, _ALIASES["training_goal"]))
        _append_note(parts, "Медичні примітки", _first_value(row, _child_aliases(int(idx), "medical_notes")) or _first_value(row, _ALIASES["medical_notes"]))
    else:
        _append_note(parts, "Рід занять", _first_value(row, _ADULT_NOTE_ALIASES["school_class"]))
        _append_note(parts, "Досвід спорту", _first_value(row, _ADULT_NOTE_ALIASES["previous_sport_experience"]))
        _append_note(parts, "Мета тренувань", _first_value(row, _ADULT_NOTE_ALIASES["training_goal"]))
        _append_note(parts, "Медичні примітки", _first_value(row, _ADULT_NOTE_ALIASES["medical_notes"]))

    contact = _registration_contact_from_row(row)
    _append_note(parts, "Екстрений контакт", contact.emergency_contact)
    _append_note(parts, "Поточна група/час", _first_value(row, _ALIASES["preferred_group"]))
    _append_note(parts, "Дата з форми", _first_value(row, _ALIASES["preferred_trial_date"]))
    _append_note(parts, "Згода на обробку даних", _first_value(row, _ALIASES["data_processing_consent"]))
    _append_note(parts, "Коментар", _first_value(row, _ALIASES["notes"]))
    return " | ".join(parts)


def _append_note(parts: List[str], label: str, value: str) -> None:
    if value:
        parts.append(f"{label}: {value}")


def _response_id_for_row(row: dict, row_index: int) -> str:
    return _first_value(row, _ALIASES["response_id"]) or f"sheet-row-{row_index}"


def _truthy_text(value: object, default: bool = False) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return default
    negative = ("ні", "no", "false", "0", "не можна", "не згод")
    positive = ("так", "yes", "true", "1", "можна", "згод", "дозвол")
    if any(token in text for token in negative):
        return False
    if any(token in text for token in positive):
        return True
    return default


def _parse_date_text(value: object) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _public_birthday_name(value: str, full_name: str) -> str:
    if value:
        return value.strip()
    parts = [part for part in full_name.split() if part.strip()]
    return parts[0] if parts else full_name


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _normalize_phone(value: str) -> str:
    return re.sub(r"\D+", "", value or "")


def _merge_member(existing: Member, incoming: Member) -> None:
    existing.full_name = incoming.full_name or existing.full_name
    existing.birth_date = incoming.birth_date or existing.birth_date
    existing.participant_type = incoming.participant_type or existing.participant_type
    existing.parent_name = incoming.parent_name or existing.parent_name
    existing.parent_phone = incoming.parent_phone or existing.parent_phone
    existing.parent_email = incoming.parent_email or existing.parent_email
    existing.parent_telegram_username = incoming.parent_telegram_username or existing.parent_telegram_username
    existing.parent_viber = incoming.parent_viber or existing.parent_viber
    existing.preferred_contact_channel = incoming.preferred_contact_channel or existing.preferred_contact_channel
    existing.active = True
    existing.join_date = existing.join_date or incoming.join_date
    existing.birthday_greeting_enabled = incoming.birthday_greeting_enabled
    existing.birthday_public_name = incoming.birthday_public_name or existing.birthday_public_name
    existing.photo_video_consent = incoming.photo_video_consent or existing.photo_video_consent
    existing.registration_source = incoming.registration_source or existing.registration_source
    existing.notes = _merge_notes(existing.notes, incoming.notes)


def _merge_notes(existing: Optional[str], incoming: Optional[str]) -> Optional[str]:
    if not incoming:
        return existing
    if not existing:
        return incoming
    if incoming in existing:
        return existing
    return f"{existing}\n{incoming}"
