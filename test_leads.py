"""
tests/test_attendance.py — unit-тести логіки відвідуваності.
"""
import pytest
from datetime import date, timedelta
from app.models import AttendanceRecord, AttendanceStatus, Member, ParticipantType
from app.services.attendance import find_inactive_from_records


def make_record(
    member_id="m1",
    lesson_date=None,
    status=AttendanceStatus.PRESENT,
    group_id="g1",
) -> AttendanceRecord:
    return AttendanceRecord(
        record_id="r",
        group_id=group_id,
        lesson_date=lesson_date or date.today(),
        member_id=member_id,
        status=status,
    )


class TestFindInactiveFromRecords:
    TODAY = date(2026, 5, 23)

    def test_active_member_not_inactive(self):
        records = [make_record("m1", lesson_date=self.TODAY, status=AttendanceStatus.PRESENT)]
        result = find_inactive_from_records(records, ["m1"], 7, self.TODAY)
        assert result == []

    def test_member_absent_7_days(self):
        last_date = self.TODAY - timedelta(days=8)
        records = [make_record("m1", lesson_date=last_date, status=AttendanceStatus.PRESENT)]
        result = find_inactive_from_records(records, ["m1"], 7, self.TODAY)
        assert len(result) == 1
        assert result[0][0] == "m1"
        assert result[0][1] >= 8

    def test_member_absent_exactly_threshold(self):
        last_date = self.TODAY - timedelta(days=7)
        records = [make_record("m1", lesson_date=last_date, status=AttendanceStatus.PRESENT)]
        result = find_inactive_from_records(records, ["m1"], 7, self.TODAY)
        assert len(result) == 1

    def test_member_absent_6_days_not_inactive(self):
        last_date = self.TODAY - timedelta(days=6)
        records = [make_record("m1", lesson_date=last_date, status=AttendanceStatus.PRESENT)]
        result = find_inactive_from_records(records, ["m1"], 7, self.TODAY)
        assert result == []

    def test_member_with_no_records_is_inactive(self):
        result = find_inactive_from_records([], ["m1"], 7, self.TODAY)
        assert len(result) == 1
        assert result[0][0] == "m1"
        assert result[0][1] == 7

    def test_only_absent_records_counts_as_inactive(self):
        # Якщо всі записи — absent, member вважається неактивним
        records = [
            make_record("m1", lesson_date=self.TODAY - timedelta(days=3),
                        status=AttendanceStatus.ABSENT),
            make_record("m1", lesson_date=self.TODAY - timedelta(days=2),
                        status=AttendanceStatus.ABSENT),
        ]
        result = find_inactive_from_records(records, ["m1"], 7, self.TODAY)
        assert len(result) == 1

    def test_multiple_members_mixed(self):
        records = [
            make_record("m1", lesson_date=self.TODAY, status=AttendanceStatus.PRESENT),
            make_record("m2", lesson_date=self.TODAY - timedelta(days=10),
                        status=AttendanceStatus.PRESENT),
        ]
        result = find_inactive_from_records(records, ["m1", "m2"], 7, self.TODAY)
        assert len(result) == 1
        assert result[0][0] == "m2"

    def test_empty_member_list(self):
        result = find_inactive_from_records([], [], 7, self.TODAY)
        assert result == []

    def test_threshold_21_days(self):
        last_date = self.TODAY - timedelta(days=25)
        records = [make_record("m1", lesson_date=last_date, status=AttendanceStatus.PRESENT)]
        result_7  = find_inactive_from_records(records, ["m1"], 7, self.TODAY)
        result_14 = find_inactive_from_records(records, ["m1"], 14, self.TODAY)
        result_21 = find_inactive_from_records(records, ["m1"], 21, self.TODAY)
        assert len(result_7) == 1
        assert len(result_14) == 1
        assert len(result_21) == 1

    def test_excused_not_counted_as_present(self):
        records = [
            make_record("m1", lesson_date=self.TODAY - timedelta(days=2),
                        status=AttendanceStatus.EXCUSED),
        ]
        # Excused — не PRESENT, отже member неактивний
        result = find_inactive_from_records(records, ["m1"], 7, self.TODAY)
        assert len(result) == 1
