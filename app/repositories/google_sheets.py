"""
repositories/google_sheets.py — Google Sheets gateway.

Реалізує всі репозиторії через Google Sheets API.
Стійкий до порожніх клітинок, відсутніх рядків, зайвих пробілів.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Lazy import Google libs (щоб тести без credentials не падали) ─────────────
try:
    import gspread
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    _GSPREAD_AVAILABLE = True
except ImportError:
    _GSPREAD_AVAILABLE = False
    log.warning("gspread не встановлено — Google Sheets репозиторій недоступний.")

from app.models import (
    AttendanceRecord,
    AttendanceStatus,
    AuditLog,
    Event,
    EventStatus,
    Group,
    Lead,
    LeadStatus,
    Member,
    MessageTemplate,
    Payment,
    PaymentStatus,
    ReminderLog,
    ReminderType,
    Role,
    Task,
    TaskStatus,
    UserRole,
)

# ── Назви аркушів та їхні заголовки ──────────────────────────────────────────

SHEET_HEADERS: Dict[str, List[str]] = {
    "users_roles": [
        "telegram_id", "username", "full_name", "role", "active", "notes", "created_at"
    ],
    "members": [
        "member_id", "participant_type", "child_full_name", "adult_full_name", "full_name",
        "birth_date", "birthday_month_day", "birthday_greeting_enabled",
        "birthday_public_name", "birthday_last_greeted_year", "photo_video_consent",
        "age", "group_name", "group_id", "parent_full_name", "parent_name",
        "parent_phone", "parent_email", "parent_telegram_username", "parent_viber",
        "preferred_contact_channel", "parent_telegram_id", "emergency_contact",
        "school_class_or_occupation", "previous_sport_experience", "training_goal",
        "active", "belt", "join_date", "trial_date", "membership_status",
        "last_attendance_date", "attendance_risk_flag", "payment_risk_flag", "notes"
    ],
    "payments": [
        "payment_id", "member_id", "period", "status",
        "amount_due", "amount_paid", "promised_date", "paid_date", "notes", "updated_at"
    ],
    "groups": [
        "group_id", "name", "coach_telegram_id", "schedule",
        "attendance_reminder_time", "attendance_deadline_time", "active", "notes"
    ],
    "attendance": [
        "record_id", "group_id", "lesson_date", "member_id",
        "status", "marked_by", "marked_at", "notes"
    ],
    "leads": [
        "lead_id", "child_name", "parent_name", "parent_telegram_id",
        "parent_phone", "status", "trial_date", "trial_group_id",
        "trial_present", "source", "notes", "created_at", "updated_at"
    ],
    "events": [
        "event_id", "title", "event_date", "description",
        "status", "audience", "reminder_sent", "created_by", "created_at"
    ],
    "message_templates": [
        "template_id", "name", "text", "variables"
    ],
    "tasks": [
        "task_id", "title", "assigned_to", "status", "due_date", "notes", "created_at"
    ],
    "reminders_log": [
        "log_id", "reminder_type", "target_id", "sent_to", "sent_at", "message_preview"
    ],
    "audit_log": [
        "log_id", "action", "performed_by", "entity_type", "entity_id", "details", "timestamp"
    ],
    "announcements": [
        "announcement_id", "title", "text", "audience", "sent_at", "sent_by"
    ],
    "settings": [
        "key", "value", "description", "updated_at"
    ],
}

_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/forms.responses.readonly",
]


# ── Базовий клас SheetRepository ─────────────────────────────────────────────

class SheetRepository:
    """
    Базовий клас з допоміжними методами читання/запису.
    Використовує gspread з кешуванням аркушів.
    """

    def __init__(self, client: "gspread.Client", spreadsheet_id: str) -> None:
        self._client = client
        self._spreadsheet_id = spreadsheet_id
        self._spreadsheet: Optional["gspread.Spreadsheet"] = None
        self._sheet_cache: Dict[str, "gspread.Worksheet"] = {}

    def _get_spreadsheet(self) -> "gspread.Spreadsheet":
        if self._spreadsheet is None:
            self._spreadsheet = self._client.open_by_key(self._spreadsheet_id)
        return self._spreadsheet

    def _get_sheet(self, name: str) -> "gspread.Worksheet":
        if name not in self._sheet_cache:
            self._sheet_cache[name] = self._get_spreadsheet().worksheet(name)
        return self._sheet_cache[name]

    @staticmethod
    def _normalize_cell(value: object) -> str:
        return str(value).strip()

    def _sheet_headers(self, sheet_name: str) -> List[str]:
        return [self._normalize_cell(h) for h in self._get_sheet(sheet_name).row_values(1)]

    @staticmethod
    def _first_header_positions(headers: List[str]) -> Dict[str, int]:
        positions: Dict[str, int] = {}
        duplicates: set[str] = set()
        for idx, header in enumerate(headers):
            if not header:
                continue
            if header in positions:
                duplicates.add(header)
                continue
            positions[header] = idx
        if duplicates:
            log.warning(
                "Duplicate Google Sheet headers ignored after first occurrence: %s",
                ", ".join(sorted(duplicates)),
            )
        return positions

    def _all_records(self, sheet_name: str) -> List[Dict[str, str]]:
        """
        Повертає всі рядки як список dict.
        Порожні клітинки → пустий рядок "".
        """
        try:
            ws = self._get_sheet(sheet_name)
            values = ws.get_all_values()
            if not values:
                return []
            headers = [self._normalize_cell(h) for h in values[0]]
            positions = self._first_header_positions(headers)
            records: List[Dict[str, str]] = []
            for values_row in values[1:]:
                if not any(self._normalize_cell(cell) for cell in values_row):
                    continue
                row: Dict[str, str] = {}
                for header, col_idx in positions.items():
                    row[header] = (
                        self._normalize_cell(values_row[col_idx])
                        if col_idx < len(values_row)
                        else ""
                    )
                records.append(row)
            return records
        except Exception as e:
            log.error("Помилка читання аркуша '%s': %s", sheet_name, e)
            raise

    @staticmethod
    def _normalize_row(row: dict) -> Dict[str, str]:
        """Конвертує всі значення у рядки, обрізає пробіли."""
        return {k: str(v).strip() for k, v in row.items()}

    def _find_row_index(self, sheet_name: str, col: str, value: str) -> Optional[int]:
        """
        Шукає рядок за значенням у колонці.
        Повертає 1-based індекс рядка (включно із заголовком = рядок 1).
        """
        ws = self._get_sheet(sheet_name)
        values = ws.get_all_values()
        if not values:
            return None
        headers = [self._normalize_cell(h) for h in values[0]]
        positions = self._first_header_positions(headers)
        col_idx = positions.get(col)
        if col_idx is None:
            return None
        for i, row in enumerate(values[1:], start=2):  # data starts at row 2
            cell_value = row[col_idx] if col_idx < len(row) else ""
            if self._normalize_cell(cell_value) == value:
                return i
        return None

    def _update_row(self, sheet_name: str, row_idx: int, data: Dict[str, str]) -> None:
        """Оновлює окремі клітинки у рядку за іменами колонок."""
        ws = self._get_sheet(sheet_name)
        positions = self._first_header_positions(self._sheet_headers(sheet_name))
        cells = []
        for col_name, val in data.items():
            col_idx = positions.get(col_name)
            if col_idx is None:
                log.warning("Колонка '%s' не знайдена в аркуші '%s'", col_name, sheet_name)
                continue
            cells.append(gspread.Cell(row_idx, col_idx + 1, str(val)))
        if cells:
            ws.update_cells(cells)

    def _append_row(self, sheet_name: str, values: List[str]) -> None:
        """Додає новий рядок у кінець аркуша."""
        ws = self._get_sheet(sheet_name)
        ws.append_row(values, value_input_option="RAW")

    def _upsert(self, sheet_name: str, pk_col: str, pk_val: str,
                row_dict: Dict[str, str]) -> None:
        """
        Якщо запис з pk_val вже є — оновлює.
        Якщо ні — додає новий рядок.
        """
        headers = [h for h in self._sheet_headers(sheet_name) if h] or SHEET_HEADERS.get(
            sheet_name,
            list(row_dict.keys()),
        )
        row_idx = self._find_row_index(sheet_name, pk_col, pk_val)
        if row_idx is not None:
            self._update_row(sheet_name, row_idx, row_dict)
        else:
            ordered = [row_dict.get(h, "") for h in headers]
            self._append_row(sheet_name, ordered)


# ── Реалізації репозиторіїв ───────────────────────────────────────────────────

class GsUserRoleRepository(SheetRepository):
    SHEET = "users_roles"

    def get_all(self) -> List[UserRole]:
        return [UserRole.from_row(r) for r in self._all_records(self.SHEET)]

    def get_by_telegram_id(self, telegram_id: int) -> Optional[UserRole]:
        for r in self._all_records(self.SHEET):
            if r.get("telegram_id") == str(telegram_id):
                return UserRole.from_row(r)
        return None

    def upsert(self, user_role: UserRole) -> None:
        data = {
            "telegram_id": str(user_role.telegram_id),
            "username": user_role.username or "",
            "full_name": user_role.full_name,
            "role": user_role.role.value,
            "active": "true" if user_role.active else "false",
            "notes": user_role.notes or "",
            "created_at": str(user_role.created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        }
        self._upsert(self.SHEET, "telegram_id", str(user_role.telegram_id), data)


class GsMemberRepository(SheetRepository):
    SHEET = "members"

    def get_all(self) -> List[Member]:
        return [Member.from_row(r) for r in self._all_records(self.SHEET)]

    def get_active(self) -> List[Member]:
        return [m for m in self.get_all() if m.active]

    def get_by_id(self, member_id: str) -> Optional[Member]:
        for r in self._all_records(self.SHEET):
            if r.get("member_id") == member_id:
                return Member.from_row(r)
        return None

    def get_by_group(self, group_id: str) -> List[Member]:
        return [m for m in self.get_all() if m.group_id == group_id and m.active]

    def add(self, member: Member) -> None:
        if not member.member_id:
            member.member_id = str(uuid.uuid4())[:8]
        self.upsert(member)

    def upsert(self, member: Member) -> None:
        data = {
            "member_id": member.member_id,
            "participant_type": member.participant_type.value,
            "child_full_name": member.full_name if member.participant_type.value == "child" else "",
            "adult_full_name": member.full_name if member.participant_type.value == "adult" else "",
            "full_name": member.full_name,
            "birth_date": str(member.birth_date or ""),
            "birthday_month_day": member.birth_date.strftime("%m-%d") if member.birth_date else "",
            "birthday_greeting_enabled": "true" if member.birthday_greeting_enabled else "false",
            "birthday_public_name": member.birthday_public_name or "",
            "birthday_last_greeted_year": str(member.birthday_last_greeted_year or ""),
            "photo_video_consent": member.photo_video_consent or "",
            "parent_telegram_id": str(member.parent_telegram_id or ""),
            "parent_full_name": member.parent_name or "",
            "parent_name": member.parent_name or "",
            "group_id": member.group_id or "",
            "active": "true" if member.active else "false",
            "belt": member.belt or "",
            "join_date": str(member.join_date or ""),
            "parent_phone": member.parent_phone or "",
            "parent_email": member.parent_email or "",
            "parent_telegram_username": member.parent_telegram_username or "",
            "parent_viber": member.parent_viber or "",
            "preferred_contact_channel": member.preferred_contact_channel or "",
            "notes": member.notes or "",
        }
        self._upsert(self.SHEET, "member_id", member.member_id, data)


class GsPaymentRepository(SheetRepository):
    SHEET = "payments"

    def get_all(self) -> List[Payment]:
        return [Payment.from_row(r) for r in self._all_records(self.SHEET)]

    def get_by_member(self, member_id: str) -> List[Payment]:
        return [p for p in self.get_all() if p.member_id == member_id]

    def get_by_period(self, period: str) -> List[Payment]:
        return [p for p in self.get_all() if p.period == period]

    def get_by_status(self, status: PaymentStatus) -> List[Payment]:
        return [p for p in self.get_all() if p.status == status]

    def get_current_period_payments(self) -> List[Payment]:
        period = datetime.now().strftime("%Y-%m")
        return self.get_by_period(period)

    def add(self, payment: Payment) -> None:
        if not payment.payment_id:
            payment.payment_id = str(uuid.uuid4())[:8]
        self.upsert(payment)

    def upsert(self, payment: Payment) -> None:
        data = {
            "payment_id": payment.payment_id,
            "member_id": payment.member_id,
            "period": payment.period,
            "status": payment.status.value,
            "amount_due": str(payment.amount_due),
            "amount_paid": str(payment.amount_paid),
            "promised_date": str(payment.promised_date or ""),
            "paid_date": str(payment.paid_date or ""),
            "notes": payment.notes or "",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._upsert(self.SHEET, "payment_id", payment.payment_id, data)


class GsGroupRepository(SheetRepository):
    SHEET = "groups"

    def get_all(self) -> List[Group]:
        return [Group.from_row(r) for r in self._all_records(self.SHEET)]

    def get_active(self) -> List[Group]:
        return [g for g in self.get_all() if g.active]

    def get_by_id(self, group_id: str) -> Optional[Group]:
        for r in self._all_records(self.SHEET):
            if r.get("group_id") == group_id:
                return Group.from_row(r)
        return None

    def get_by_coach(self, coach_telegram_id: int) -> List[Group]:
        return [g for g in self.get_all() if g.coach_telegram_id == coach_telegram_id]

    def upsert(self, group: Group) -> None:
        data = {
            "group_id": group.group_id,
            "name": group.name,
            "coach_telegram_id": str(group.coach_telegram_id or ""),
            "schedule": group.schedule,
            "attendance_reminder_time": group.attendance_reminder_time or "",
            "attendance_deadline_time": group.attendance_deadline_time or "",
            "active": "true" if group.active else "false",
            "notes": group.notes or "",
        }
        self._upsert(self.SHEET, "group_id", group.group_id, data)


class GsAttendanceRepository(SheetRepository):
    SHEET = "attendance"

    def _uses_legacy_headers(self) -> bool:
        headers = self._sheet_headers(self.SHEET)
        return "record_id" not in headers and "date" in headers

    def get_all(self) -> List[AttendanceRecord]:
        rows = self._all_records(self.SHEET)
        if self._uses_legacy_headers():
            rows = [
                {
                    "record_id": row.get("date", ""),
                    "group_id": row.get("lesson_time", ""),
                    "lesson_date": row.get("group_name", ""),
                    "member_id": row.get("member_id", ""),
                    "status": row.get("participant_full_name", ""),
                    "marked_by": row.get("status", ""),
                    "marked_at": row.get("coach_telegram_id", ""),
                    "notes": row.get("coach_name", ""),
                }
                for row in rows
            ]
        return [AttendanceRecord.from_row(r) for r in rows]

    def get_by_date(self, lesson_date: date) -> List[AttendanceRecord]:
        return [r for r in self.get_all() if r.lesson_date == lesson_date]

    def get_by_group_date(self, group_id: str, lesson_date: date) -> List[AttendanceRecord]:
        return [
            r for r in self.get_all()
            if r.group_id == group_id and r.lesson_date == lesson_date
        ]

    def get_by_member(self, member_id: str) -> List[AttendanceRecord]:
        return [r for r in self.get_all() if r.member_id == member_id]

    def get_member_last_n_days(self, member_id: str, days: int) -> List[AttendanceRecord]:
        cutoff = date.today() - timedelta(days=days)
        return [
            r for r in self.get_by_member(member_id)
            if r.lesson_date >= cutoff
        ]

    def add(self, record: AttendanceRecord) -> None:
        if not record.record_id:
            record.record_id = str(uuid.uuid4())[:8]
        self.upsert(record)

    def delete(self, record_id: str) -> None:
        pk_col = "date" if self._uses_legacy_headers() else "record_id"
        row_idx = self._find_row_index(self.SHEET, pk_col, record_id)
        if row_idx is not None:
            self._get_sheet(self.SHEET).delete_rows(row_idx)

    def upsert(self, record: AttendanceRecord) -> None:
        data = {
            "record_id": record.record_id,
            "group_id": record.group_id,
            "lesson_date": str(record.lesson_date),
            "member_id": record.member_id,
            "status": record.status.value,
            "marked_by": str(record.marked_by or ""),
            "marked_at": str(record.marked_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "notes": record.notes or "",
        }
        if self._uses_legacy_headers():
            legacy_data = {
                "date": data["record_id"],
                "lesson_time": data["group_id"],
                "group_name": data["lesson_date"],
                "member_id": data["member_id"],
                "participant_full_name": data["status"],
                "status": data["marked_by"],
                "coach_telegram_id": data["marked_at"],
                "coach_name": data["notes"],
            }
            self._upsert(self.SHEET, "date", record.record_id, legacy_data)
            return
        self._upsert(self.SHEET, "record_id", record.record_id, data)


class GsLeadRepository(SheetRepository):
    SHEET = "leads"

    def get_all(self) -> List[Lead]:
        return [Lead.from_row(r) for r in self._all_records(self.SHEET)]

    def get_by_id(self, lead_id: str) -> Optional[Lead]:
        for r in self._all_records(self.SHEET):
            if r.get("lead_id") == lead_id:
                return Lead.from_row(r)
        return None

    def get_by_status(self, status: LeadStatus) -> List[Lead]:
        return [ld for ld in self.get_all() if ld.status == status]

    def get_trials_on_date(self, trial_date: date) -> List[Lead]:
        return [ld for ld in self.get_all() if ld.trial_date == trial_date]

    def add(self, lead: Lead) -> None:
        if not lead.lead_id:
            lead.lead_id = str(uuid.uuid4())[:8]
        if not lead.created_at:
            lead.created_at = datetime.now()
        self.upsert(lead)

    def upsert(self, lead: Lead) -> None:
        data = {
            "lead_id": lead.lead_id,
            "child_name": lead.child_name,
            "parent_name": lead.parent_name,
            "parent_telegram_id": str(lead.parent_telegram_id or ""),
            "parent_phone": lead.parent_phone or "",
            "status": lead.status.value,
            "trial_date": str(lead.trial_date or ""),
            "trial_group_id": lead.trial_group_id or "",
            "trial_present": ("" if lead.trial_present is None
                              else ("true" if lead.trial_present else "false")),
            "source": lead.source or "",
            "notes": lead.notes or "",
            "created_at": str(lead.created_at or ""),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._upsert(self.SHEET, "lead_id", lead.lead_id, data)


class GsEventRepository(SheetRepository):
    SHEET = "events"

    def get_all(self) -> List[Event]:
        return [Event.from_row(r) for r in self._all_records(self.SHEET)]

    def get_by_id(self, event_id: str) -> Optional[Event]:
        for r in self._all_records(self.SHEET):
            if r.get("event_id") == event_id:
                return Event.from_row(r)
        return None

    def get_upcoming(self, days: int = 7) -> List[Event]:
        today = date.today()
        cutoff = today + timedelta(days=days)
        return [
            e for e in self.get_all()
            if e.event_date and today <= e.event_date <= cutoff
               and e.status not in (EventStatus.DONE, EventStatus.CANCELLED)
        ]

    def get_today(self) -> List[Event]:
        today = date.today()
        return [e for e in self.get_all() if e.event_date == today]

    def add(self, event: Event) -> None:
        if not event.event_id:
            event.event_id = str(uuid.uuid4())[:8]
        self.upsert(event)

    def upsert(self, event: Event) -> None:
        data = {
            "event_id": event.event_id,
            "title": event.title,
            "event_date": str(event.event_date or ""),
            "description": event.description or "",
            "status": event.status.value,
            "audience": event.audience or "",
            "reminder_sent": "true" if event.reminder_sent else "false",
            "created_by": str(event.created_by or ""),
            "created_at": str(event.created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        }
        self._upsert(self.SHEET, "event_id", event.event_id, data)


class GsMessageTemplateRepository(SheetRepository):
    SHEET = "message_templates"

    def _uses_legacy_headers(self) -> bool:
        headers = self._sheet_headers(self.SHEET)
        return "name" not in headers and "template_key" in headers and "body" in headers

    @staticmethod
    def _from_legacy_row(row: Dict[str, str]) -> MessageTemplate:
        return MessageTemplate(
            template_id=row.get("template_key", ""),
            name=row.get("template_key", ""),
            text=row.get("body", ""),
            variables=row.get("variables") or None,
        )

    def _row_for_template(self, template: MessageTemplate) -> Dict[str, str]:
        if self._uses_legacy_headers():
            return {
                "template_key": template.name,
                "language": "uk",
                "audience": "",
                "title": template.name,
                "body": template.text,
                "variables": template.variables or "",
                "enabled": "TRUE",
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
        return {
            "template_id": template.template_id or str(uuid.uuid4())[:8],
            "name": template.name,
            "text": template.text,
            "variables": template.variables or "",
        }

    def get_all(self) -> List[MessageTemplate]:
        rows = self._all_records(self.SHEET)
        if self._uses_legacy_headers():
            return [
                self._from_legacy_row(r)
                for r in rows
                if r.get("template_key") and r.get("body")
            ]
        return [MessageTemplate.from_row(r) for r in rows]

    def get_by_name(self, name: str) -> Optional[MessageTemplate]:
        rows = self._all_records(self.SHEET)
        if self._uses_legacy_headers():
            for r in rows:
                if r.get("template_key") == name and r.get("body"):
                    return self._from_legacy_row(r)
            return None
        for r in rows:
            if r.get("name") == name:
                return MessageTemplate.from_row(r)
        return None

    def upsert(self, template: MessageTemplate) -> None:
        data = self._row_for_template(template)
        pk_col = "template_key" if self._uses_legacy_headers() else "name"
        self._upsert(self.SHEET, pk_col, template.name, data)

    def append_many(self, templates: List[MessageTemplate]) -> None:
        if not templates:
            return
        headers = [h for h in self._sheet_headers(self.SHEET) if h] or SHEET_HEADERS[self.SHEET]
        rows = []
        for template in templates:
            data = self._row_for_template(template)
            rows.append([data.get(h, "") for h in headers])
        self._get_sheet(self.SHEET).append_rows(rows, value_input_option="USER_ENTERED")


class GsTaskRepository(SheetRepository):
    SHEET = "tasks"

    def get_all(self) -> List[Task]:
        return [Task.from_row(r) for r in self._all_records(self.SHEET)]

    def get_open(self) -> List[Task]:
        return [t for t in self.get_all() if t.status == TaskStatus.OPEN]

    def add(self, task: Task) -> None:
        if not task.task_id:
            task.task_id = str(uuid.uuid4())[:8]
        self.upsert(task)

    def upsert(self, task: Task) -> None:
        data = {
            "task_id": task.task_id,
            "title": task.title,
            "assigned_to": str(task.assigned_to or ""),
            "status": task.status.value,
            "due_date": str(task.due_date or ""),
            "notes": task.notes or "",
            "created_at": str(task.created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        }
        self._upsert(self.SHEET, "task_id", task.task_id, data)


class GsReminderLogRepository(SheetRepository):
    SHEET = "reminders_log"

    def add(self, log_entry: ReminderLog) -> None:
        headers = SHEET_HEADERS[self.SHEET]
        row = [
            log_entry.log_id or str(uuid.uuid4())[:8],
            log_entry.reminder_type.value,
            log_entry.target_id,
            str(log_entry.sent_to),
            str(log_entry.sent_at),
            (log_entry.message_preview or "")[:200],
        ]
        self._append_row(self.SHEET, row)

    def get_recent(self, target_id: str, reminder_type: ReminderType,
                   hours: int = 24) -> List[ReminderLog]:
        cutoff = datetime.now() - timedelta(hours=hours)
        result = []
        for r in self._all_records(self.SHEET):
            if r.get("target_id") == target_id and r.get("reminder_type") == reminder_type.value:
                rl = ReminderLog.from_row(r)
                if rl.sent_at >= cutoff:
                    result.append(rl)
        return result


class GsAuditLogRepository(SheetRepository):
    SHEET = "audit_log"

    def add(self, log_entry: AuditLog) -> None:
        row = [
            log_entry.log_id or str(uuid.uuid4())[:8],
            log_entry.action,
            str(log_entry.performed_by),
            log_entry.entity_type,
            log_entry.entity_id,
            log_entry.details or "",
            str(log_entry.timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ]
        self._append_row(self.SHEET, row)


# ── Фабрика ───────────────────────────────────────────────────────────────────

def build_google_sheets_client(credentials_file: str) -> "gspread.Client":
    """
    Авторизується та повертає gspread.Client.
    Кидає RuntimeError якщо gspread недоступний або credentials неправильні.
    """
    if not _GSPREAD_AVAILABLE:
        raise RuntimeError(
            "gspread не встановлено. Виконайте: pip install gspread google-auth"
        )
    try:
        creds = ServiceAccountCredentials.from_service_account_file(
            credentials_file, scopes=_SCOPES
        )
        return gspread.authorize(creds)
    except FileNotFoundError:
        raise RuntimeError(
            f"Файл облікових даних Google не знайдено: '{credentials_file}'.\n"
            f"Вкажіть правильний шлях у GOOGLE_CREDENTIALS_FILE у .env"
        )
    except Exception as e:
        raise RuntimeError(f"Помилка авторизації Google Sheets: {e}") from e


def build_repositories(credentials_file: str, spreadsheet_id: str):
    """
    Будує повний набір Google Sheets репозиторіїв.
    Імпортуємо Repositories тут щоб уникнути циклічного імпорту.
    """
    from app.repositories.base import Repositories

    client = build_google_sheets_client(credentials_file)

    return Repositories(
        users=GsUserRoleRepository(client, spreadsheet_id),
        members=GsMemberRepository(client, spreadsheet_id),
        payments=GsPaymentRepository(client, spreadsheet_id),
        groups=GsGroupRepository(client, spreadsheet_id),
        attendance=GsAttendanceRepository(client, spreadsheet_id),
        leads=GsLeadRepository(client, spreadsheet_id),
        events=GsEventRepository(client, spreadsheet_id),
        templates=GsMessageTemplateRepository(client, spreadsheet_id),
        tasks=GsTaskRepository(client, spreadsheet_id),
        reminder_log=GsReminderLogRepository(client, spreadsheet_id),
        audit_log=GsAuditLogRepository(client, spreadsheet_id),
    )
