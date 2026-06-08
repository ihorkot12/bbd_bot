"""
repositories/stub.py — In-memory заглушки репозиторіїв для dry-run та тестів.

Повністю ізольовані від Google Sheets.
Не потребують жодних credentials.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from app.models import (
    AttendanceRecord,
    AuditLog,
    Event,
    Group,
    Lead,
    LeadStatus,
    Member,
    MessageTemplate,
    Payment,
    PaymentStatus,
    ReminderLog,
    ReminderType,
    Task,
    UserRole,
)
from app.repositories.base import Repositories


class _StubUserRoleRepo:
    def __init__(self): self._data: Dict[int, UserRole] = {}

    def get_all(self) -> List[UserRole]: return list(self._data.values())

    def get_by_telegram_id(self, telegram_id: int) -> Optional[UserRole]:
        return self._data.get(telegram_id)

    def upsert(self, user_role: UserRole) -> None:
        self._data[user_role.telegram_id] = user_role


class _StubMemberRepo:
    def __init__(self): self._data: Dict[str, Member] = {}

    def get_all(self) -> List[Member]: return list(self._data.values())
    def get_active(self) -> List[Member]: return [m for m in self._data.values() if m.active]
    def get_by_id(self, member_id: str) -> Optional[Member]: return self._data.get(member_id)
    def get_by_group(self, group_id: str) -> List[Member]:
        return [m for m in self._data.values() if m.group_id == group_id and m.active]
    def add(self, member: Member) -> None:
        if not member.member_id: member.member_id = str(uuid.uuid4())[:8]
        self._data[member.member_id] = member
    def upsert(self, member: Member) -> None: self._data[member.member_id] = member


class _StubPaymentRepo:
    def __init__(self): self._data: Dict[str, Payment] = {}

    def get_all(self) -> List[Payment]: return list(self._data.values())
    def get_by_member(self, member_id: str) -> List[Payment]:
        return [p for p in self._data.values() if p.member_id == member_id]
    def get_by_period(self, period: str) -> List[Payment]:
        return [p for p in self._data.values() if p.period == period]
    def get_by_status(self, status: PaymentStatus) -> List[Payment]:
        return [p for p in self._data.values() if p.status == status]
    def get_current_period_payments(self) -> List[Payment]:
        return self.get_by_period(datetime.now().strftime("%Y-%m"))
    def add(self, payment: Payment) -> None:
        if not payment.payment_id: payment.payment_id = str(uuid.uuid4())[:8]
        self._data[payment.payment_id] = payment
    def upsert(self, payment: Payment) -> None: self._data[payment.payment_id] = payment


class _StubGroupRepo:
    def __init__(self): self._data: Dict[str, Group] = {}

    def get_all(self) -> List[Group]: return list(self._data.values())
    def get_active(self) -> List[Group]: return [g for g in self._data.values() if g.active]
    def get_by_id(self, group_id: str) -> Optional[Group]: return self._data.get(group_id)
    def get_by_coach(self, coach_telegram_id: int) -> List[Group]:
        return [g for g in self._data.values() if g.coach_telegram_id == coach_telegram_id]
    def upsert(self, group: Group) -> None: self._data[group.group_id] = group


class _StubAttendanceRepo:
    def __init__(self): self._data: Dict[str, AttendanceRecord] = {}

    def get_all(self) -> List[AttendanceRecord]: return list(self._data.values())
    def get_by_date(self, lesson_date: date) -> List[AttendanceRecord]:
        return [r for r in self._data.values() if r.lesson_date == lesson_date]
    def get_by_group_date(self, group_id: str, lesson_date: date) -> List[AttendanceRecord]:
        return [r for r in self._data.values()
                if r.group_id == group_id and r.lesson_date == lesson_date]
    def get_by_member(self, member_id: str) -> List[AttendanceRecord]:
        return [r for r in self._data.values() if r.member_id == member_id]
    def get_member_last_n_days(self, member_id: str, days: int) -> List[AttendanceRecord]:
        cutoff = date.today() - timedelta(days=days)
        return [r for r in self.get_by_member(member_id) if r.lesson_date >= cutoff]
    def add(self, record: AttendanceRecord) -> None:
        if not record.record_id: record.record_id = str(uuid.uuid4())[:8]
        self._data[record.record_id] = record
    def upsert(self, record: AttendanceRecord) -> None:
        self._data[record.record_id] = record
    def delete(self, record_id: str) -> None:
        self._data.pop(record_id, None)


class _StubLeadRepo:
    def __init__(self): self._data: Dict[str, Lead] = {}

    def get_all(self) -> List[Lead]: return list(self._data.values())
    def get_by_id(self, lead_id: str) -> Optional[Lead]: return self._data.get(lead_id)
    def get_by_status(self, status: LeadStatus) -> List[Lead]:
        return [ld for ld in self._data.values() if ld.status == status]
    def get_trials_on_date(self, trial_date: date) -> List[Lead]:
        return [ld for ld in self._data.values() if ld.trial_date == trial_date]
    def add(self, lead: Lead) -> None:
        if not lead.lead_id: lead.lead_id = str(uuid.uuid4())[:8]
        self._data[lead.lead_id] = lead
    def upsert(self, lead: Lead) -> None: self._data[lead.lead_id] = lead


class _StubEventRepo:
    def __init__(self): self._data: Dict[str, Event] = {}

    def get_all(self) -> List[Event]: return list(self._data.values())
    def get_by_id(self, event_id: str) -> Optional[Event]: return self._data.get(event_id)
    def get_upcoming(self, days: int = 7) -> List[Event]:
        today, cutoff = date.today(), date.today() + timedelta(days=days)
        return [e for e in self._data.values()
                if e.event_date and today <= e.event_date <= cutoff]
    def get_today(self) -> List[Event]:
        return [e for e in self._data.values() if e.event_date == date.today()]
    def add(self, event: Event) -> None:
        if not event.event_id: event.event_id = str(uuid.uuid4())[:8]
        self._data[event.event_id] = event
    def upsert(self, event: Event) -> None: self._data[event.event_id] = event


class _StubTemplateRepo:
    def __init__(self): self._data: Dict[str, MessageTemplate] = {}

    def get_all(self) -> List[MessageTemplate]: return list(self._data.values())
    def get_by_name(self, name: str) -> Optional[MessageTemplate]:
        return self._data.get(name)
    def upsert(self, template: MessageTemplate) -> None:
        self._data[template.name] = template


class _StubTaskRepo:
    def __init__(self): self._data: Dict[str, Task] = {}

    def get_all(self) -> List[Task]: return list(self._data.values())
    def get_open(self) -> List[Task]:
        from app.models import TaskStatus
        return [t for t in self._data.values() if t.status == TaskStatus.OPEN]
    def add(self, task: Task) -> None:
        if not task.task_id: task.task_id = str(uuid.uuid4())[:8]
        self._data[task.task_id] = task
    def upsert(self, task: Task) -> None: self._data[task.task_id] = task


class _StubReminderLogRepo:
    def __init__(self): self._data: List[ReminderLog] = []

    def add(self, log_entry: ReminderLog) -> None: self._data.append(log_entry)
    def get_recent(self, target_id: str, reminder_type: ReminderType,
                   hours: int = 24) -> List[ReminderLog]:
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            r for r in self._data
            if r.target_id == target_id
            and r.reminder_type == reminder_type
            and r.sent_at >= cutoff
        ]


class _StubAuditLogRepo:
    def __init__(self): self._data: List[AuditLog] = []
    def add(self, log_entry: AuditLog) -> None: self._data.append(log_entry)


def build_stub_repositories() -> Repositories:
    """Будує повний набір in-memory репозиторіїв."""
    return Repositories(
        users=_StubUserRoleRepo(),
        members=_StubMemberRepo(),
        payments=_StubPaymentRepo(),
        groups=_StubGroupRepo(),
        attendance=_StubAttendanceRepo(),
        leads=_StubLeadRepo(),
        events=_StubEventRepo(),
        templates=_StubTemplateRepo(),
        tasks=_StubTaskRepo(),
        reminder_log=_StubReminderLogRepo(),
        audit_log=_StubAuditLogRepo(),
    )
