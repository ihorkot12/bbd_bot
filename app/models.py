"""
models.py — dataclasses та enum для всіх сутностей Black Bear Dojo.

Підтримує:
- participant_type: child / adult
- Дані батьків/опікунів: обов'язкові для child, опціональні для adult
- registration_source: google_form / bot / manual
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import List, Optional


# ── Enums ─────────────────────────────────────────────────────────────────────

class Role(str, Enum):
    GUEST   = "guest"
    LEAD    = "lead"
    PARENT  = "parent"
    COACH   = "coach"
    ADMIN   = "admin"
    OWNER   = "owner"


class ParticipantType(str, Enum):
    CHILD = "child"   # дитина — потрібні дані батьків/опікунів
    ADULT = "adult"   # дорослий — дані батьків опціональні


class RegistrationSource(str, Enum):
    GOOGLE_FORM = "google_form"
    BOT         = "bot"
    MANUAL      = "manual"


class PaymentStatus(str, Enum):
    PAID     = "paid"
    PARTIAL  = "partial"
    UNPAID   = "unpaid"
    PROMISED = "promised"
    OVERDUE  = "overdue"
    FROZEN   = "frozen"


class LeadStatus(str, Enum):
    NEW              = "new"
    TRIAL_SCHEDULED  = "trial_scheduled"
    TRIAL_DONE       = "trial_done"
    CONVERTED        = "converted"
    DECLINED         = "declined"
    RESCHEDULED      = "rescheduled"


class AttendanceStatus(str, Enum):
    PRESENT = "present"
    ABSENT  = "absent"
    EXCUSED = "excused"


class EventStatus(str, Enum):
    PLANNED   = "planned"
    ANNOUNCED = "announced"
    DONE      = "done"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    OPEN        = "open"
    IN_PROGRESS = "in_progress"
    DONE        = "done"
    CANCELLED   = "cancelled"


class ReminderType(str, Enum):
    PAYMENT    = "payment"
    ATTENDANCE = "attendance"
    TRIAL      = "trial"
    INACTIVITY = "inactivity"
    EVENT      = "event"
    DIGEST     = "digest"
    CUSTOM     = "custom"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class UserRole:
    """Рядок таблиці users_roles."""
    telegram_id: int
    username:    Optional[str]
    full_name:   str
    role:        Role
    active:      bool            = True
    notes:       Optional[str]   = None
    created_at:  Optional[datetime] = None

    @classmethod
    def from_row(cls, row: dict) -> "UserRole":
        return cls(
            telegram_id=int(row.get("telegram_id") or 0),
            username=row.get("username") or None,
            full_name=row.get("full_name") or "",
            role=_safe_enum(Role, row.get("role"), Role.GUEST),
            active=_truthy(row.get("active", "true")),
            notes=row.get("notes") or None,
            created_at=_parse_dt(row.get("created_at")),
        )


@dataclass
class Member:
    """
    Рядок таблиці members.

    participant_type:
        child — дитина; parent_telegram_id / parent_name обов'язкові.
        adult — дорослий учасник; parent_* опціональні.
    """
    member_id:           str
    full_name:           str
    birth_date:          Optional[date]
    participant_type:    ParticipantType      = ParticipantType.CHILD
    parent_telegram_id:  Optional[int]        = None
    parent_name:         Optional[str]        = None
    parent_phone:        Optional[str]        = None
    parent_email:        Optional[str]        = None
    parent_telegram_username: Optional[str]   = None
    parent_viber:        Optional[str]        = None
    preferred_contact_channel: Optional[str]  = None
    group_id:            Optional[str]        = None
    active:              bool                 = True
    belt:                Optional[str]        = None
    join_date:           Optional[date]       = None
    birthday_greeting_enabled: bool           = False
    birthday_public_name: Optional[str]       = None
    birthday_last_greeted_year: Optional[int] = None
    photo_video_consent: Optional[str]        = None
    registration_source: str                  = RegistrationSource.BOT.value
    notes:               Optional[str]        = None

    @property
    def is_adult(self) -> bool:
        return self.participant_type == ParticipantType.ADULT

    @property
    def contact_telegram_id(self) -> Optional[int]:
        """Telegram ID для зв'язку: для дитини — батько, для дорослого — сам учасник (якщо є)."""
        return self.parent_telegram_id

    @classmethod
    def from_row(cls, row: dict) -> "Member":
        return cls(
            member_id=row.get("member_id") or "",
            full_name=row.get("full_name") or "",
            birth_date=_parse_date(row.get("birth_date")),
            participant_type=_safe_enum(
                ParticipantType, row.get("participant_type"), ParticipantType.CHILD
            ),
            parent_telegram_id=_int_or_none(row.get("parent_telegram_id")),
            parent_name=row.get("parent_name") or None,
            parent_phone=row.get("parent_phone") or None,
            parent_email=row.get("parent_email") or None,
            parent_telegram_username=row.get("parent_telegram_username") or None,
            parent_viber=row.get("parent_viber") or None,
            preferred_contact_channel=row.get("preferred_contact_channel") or None,
            group_id=row.get("group_id") or None,
            active=_truthy(row.get("active", "true")),
            belt=row.get("belt") or None,
            join_date=_parse_date(row.get("join_date")),
            birthday_greeting_enabled=_truthy(row.get("birthday_greeting_enabled", "false")),
            birthday_public_name=row.get("birthday_public_name") or None,
            birthday_last_greeted_year=_int_or_none(row.get("birthday_last_greeted_year")),
            photo_video_consent=row.get("photo_video_consent") or None,
            registration_source=row.get("registration_source") or RegistrationSource.BOT.value,
            notes=row.get("notes") or None,
        )


@dataclass
class Payment:
    """Рядок таблиці payments."""
    payment_id:    str
    member_id:     str
    period:        str            # "2025-07"
    status:        PaymentStatus
    amount_due:    float          = 0.0
    amount_paid:   float          = 0.0
    promised_date: Optional[date] = None
    paid_date:     Optional[date] = None
    notes:         Optional[str]  = None
    updated_at:    Optional[datetime] = None

    @property
    def is_reminder_exempt(self) -> bool:
        return self.status in (PaymentStatus.PAID, PaymentStatus.FROZEN)

    @property
    def balance(self) -> float:
        return round(self.amount_due - self.amount_paid, 2)

    @classmethod
    def from_row(cls, row: dict) -> "Payment":
        return cls(
            payment_id=row.get("payment_id") or "",
            member_id=row.get("member_id") or "",
            period=row.get("period") or row.get("month") or "",
            status=_safe_enum(PaymentStatus, row.get("status") or row.get("payment_status"), PaymentStatus.UNPAID),
            amount_due=_float_or(row.get("amount_due") or row.get("amount"), 0.0),
            amount_paid=_float_or(row.get("amount_paid"), 0.0),
            promised_date=_parse_date(row.get("promised_date")),
            paid_date=_parse_date(row.get("paid_date")),
            notes=row.get("notes") or None,
            updated_at=_parse_dt(row.get("updated_at")),
        )


@dataclass
class Group:
    """Рядок таблиці groups."""
    group_id:                 str
    name:                     str
    coach_telegram_id:        Optional[int]
    schedule:                 str
    attendance_reminder_time: Optional[str]   # "HH:MM"
    attendance_deadline_time: Optional[str]   # "HH:MM"
    active:                   bool            = True
    notes:                    Optional[str]   = None

    @classmethod
    def from_row(cls, row: dict) -> "Group":
        return cls(
            group_id=row.get("group_id") or "",
            name=row.get("name") or row.get("group_name") or "",
            coach_telegram_id=_int_or_none(row.get("coach_telegram_id")),
            schedule=row.get("schedule") or "",
            attendance_reminder_time=row.get("attendance_reminder_time") or None,
            attendance_deadline_time=row.get("attendance_deadline_time") or None,
            active=_truthy(row.get("active", "true")),
            notes=row.get("notes") or None,
        )


@dataclass
class AttendanceRecord:
    """Рядок таблиці attendance."""
    record_id:   str
    group_id:    str
    lesson_date: date
    member_id:   str
    status:      AttendanceStatus
    marked_by:   Optional[int]      = None
    marked_at:   Optional[datetime] = None
    notes:       Optional[str]      = None

    @classmethod
    def from_row(cls, row: dict) -> "AttendanceRecord":
        return cls(
            record_id=row.get("record_id") or "",
            group_id=row.get("group_id") or "",
            lesson_date=_parse_date(row.get("lesson_date")) or date.today(),
            member_id=row.get("member_id") or "",
            status=_safe_enum(AttendanceStatus, row.get("status"), AttendanceStatus.ABSENT),
            marked_by=_int_or_none(row.get("marked_by")),
            marked_at=_parse_dt(row.get("marked_at")),
            notes=row.get("notes") or None,
        )


@dataclass
class Lead:
    """
    Рядок таблиці leads.

    participant_type:
        child — реєструє батько для дитини
        adult — доросла людина реєструється сама
    """
    lead_id:           str
    child_name:        str            # ім'я учасника (дитини або дорослого)
    parent_name:       str            # ім'я батька/опікуна або самого дорослого
    participant_type:  ParticipantType        = ParticipantType.CHILD
    parent_telegram_id: Optional[int]        = None
    parent_phone:      Optional[str]          = None
    status:            LeadStatus             = LeadStatus.NEW
    trial_date:        Optional[date]         = None
    trial_group_id:    Optional[str]          = None
    trial_present:     Optional[bool]         = None
    source:            str                    = RegistrationSource.BOT.value
    notes:             Optional[str]          = None
    created_at:        Optional[datetime]     = None
    updated_at:        Optional[datetime]     = None

    @property
    def is_adult(self) -> bool:
        return self.participant_type == ParticipantType.ADULT

    @property
    def display_name(self) -> str:
        """Відображуване ім'я для повідомлень."""
        if self.is_adult:
            return self.child_name
        return f"{self.child_name} (батьки: {self.parent_name})"

    @classmethod
    def from_row(cls, row: dict) -> "Lead":
        tp = row.get("trial_present")
        return cls(
            lead_id=row.get("lead_id") or "",
            child_name=row.get("child_name") or "",
            parent_name=row.get("parent_name") or "",
            participant_type=_safe_enum(
                ParticipantType, row.get("participant_type"), ParticipantType.CHILD
            ),
            parent_telegram_id=_int_or_none(row.get("parent_telegram_id")),
            parent_phone=row.get("parent_phone") or None,
            status=_safe_enum(LeadStatus, row.get("status"), LeadStatus.NEW),
            trial_date=_parse_date(row.get("trial_date")),
            trial_group_id=row.get("trial_group_id") or None,
            trial_present=(
                None if not tp or str(tp).strip() == ""
                else str(tp).lower() in ("true", "1", "так", "yes")
            ),
            source=row.get("source") or RegistrationSource.BOT.value,
            notes=row.get("notes") or None,
            created_at=_parse_dt(row.get("created_at")),
            updated_at=_parse_dt(row.get("updated_at")),
        )


@dataclass
class FormResponse:
    """
    Рядок таблиці form_responses — сирі відповіді з Google Form.
    Обробляються FormPollerService та конвертуються у Lead.
    """
    response_id:       str
    submitted_at:      Optional[datetime]
    participant_type:  str               = "child"
    child_name:        str               = ""
    parent_name:       str               = ""
    parent_phone:      str               = ""
    trial_date:        Optional[date]    = None
    notes:             str               = ""
    processed:         bool              = False

    @classmethod
    def from_row(cls, row: dict) -> "FormResponse":
        return cls(
            response_id=row.get("response_id") or "",
            submitted_at=_parse_dt(row.get("submitted_at")),
            participant_type=row.get("participant_type") or "child",
            child_name=row.get("child_name") or "",
            parent_name=row.get("parent_name") or "",
            parent_phone=row.get("parent_phone") or "",
            trial_date=_parse_date(row.get("trial_date")),
            notes=row.get("notes") or "",
            processed=_truthy(row.get("processed", "false")),
        )


@dataclass
class Event:
    """Рядок таблиці events."""
    event_id:      str
    title:         str
    event_date:    Optional[date]
    description:   Optional[str]
    status:        EventStatus        = EventStatus.PLANNED
    audience:      Optional[str]      = None
    reminder_sent: bool               = False
    created_by:    Optional[int]      = None
    created_at:    Optional[datetime] = None

    @classmethod
    def from_row(cls, row: dict) -> "Event":
        return cls(
            event_id=row.get("event_id") or "",
            title=row.get("title") or "",
            event_date=_parse_date(row.get("event_date")),
            description=row.get("description") or None,
            status=_safe_enum(EventStatus, row.get("status"), EventStatus.PLANNED),
            audience=row.get("audience") or None,
            reminder_sent=_truthy(row.get("reminder_sent", "false")),
            created_by=_int_or_none(row.get("created_by")),
            created_at=_parse_dt(row.get("created_at")),
        )


@dataclass
class MessageTemplate:
    """Рядок таблиці message_templates."""
    template_id: str
    name:        str
    text:        str
    variables:   Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> "MessageTemplate":
        return cls(
            template_id=row.get("template_id") or "",
            name=row.get("name") or "",
            text=row.get("text") or "",
            variables=row.get("variables") or None,
        )


@dataclass
class Task:
    """Рядок таблиці tasks."""
    task_id:     str
    title:       str
    assigned_to: Optional[int]
    status:      TaskStatus        = TaskStatus.OPEN
    due_date:    Optional[date]    = None
    notes:       Optional[str]     = None
    created_at:  Optional[datetime] = None

    @classmethod
    def from_row(cls, row: dict) -> "Task":
        return cls(
            task_id=row.get("task_id") or "",
            title=row.get("title") or "",
            assigned_to=_int_or_none(row.get("assigned_to")),
            status=_safe_enum(TaskStatus, row.get("status"), TaskStatus.OPEN),
            due_date=_parse_date(row.get("due_date")),
            notes=row.get("notes") or None,
            created_at=_parse_dt(row.get("created_at")),
        )


@dataclass
class ReminderLog:
    """Рядок таблиці reminders_log."""
    log_id:          str
    reminder_type:   ReminderType
    target_id:       str
    sent_to:         int
    sent_at:         datetime
    message_preview: Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> "ReminderLog":
        return cls(
            log_id=row.get("log_id") or "",
            reminder_type=_safe_enum(ReminderType, row.get("reminder_type"), ReminderType.CUSTOM),
            target_id=row.get("target_id") or "",
            sent_to=int(row.get("sent_to") or 0),
            sent_at=_parse_dt(row.get("sent_at")) or datetime.now(),
            message_preview=row.get("message_preview") or None,
        )


@dataclass
class AuditLog:
    """Рядок таблиці audit_log."""
    log_id:       str
    action:       str
    performed_by: int
    entity_type:  str
    entity_id:    str
    details:      Optional[str]     = None
    timestamp:    Optional[datetime] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_enum(enum_cls, value, default):
    """Конвертує рядок у enum; повертає default при помилці."""
    try:
        if value and str(value).strip():
            return enum_cls(str(value).strip())
    except ValueError:
        pass
    return default


def _parse_date(value: object) -> Optional[date]:
    if not value or str(value).strip() == "":
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_dt(value: object) -> Optional[datetime]:
    if not value or str(value).strip() == "":
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _int_or_none(value: object) -> Optional[int]:
    try:
        v = str(value).strip()
        return int(float(v)) if v else None
    except (ValueError, TypeError):
        return None


def _float_or(value: object, default: float) -> float:
    try:
        v = str(value).strip()
        return float(v) if v else default
    except (ValueError, TypeError):
        return default


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in ("true", "1", "так", "yes", "y")
