from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pactlyn.core.commitments import CommitmentCandidate, CommitmentService
from pactlyn.core.scheduler import ReminderScheduler
from pactlyn.storage.models import CommitmentType


def test_scheduler_recovers_due_reminder_and_marks_overdue(session):
    now = datetime.now(UTC)
    candidate = CommitmentCandidate(title="Send proposal", description="Send proposal", type=CommitmentType.PERSONAL_TASK, due_at=now - timedelta(hours=1), reminder_at=now - timedelta(minutes=2), needs_confirmation=False)
    service = CommitmentService(session)
    commitment = service.create(candidate, confirmed=True)
    delivered: list[tuple[str, str]] = []
    reminders = ReminderScheduler(session, lambda title, body: delivered.append((title, body))).evaluate(now)
    session.refresh(commitment)
    assert len(reminders) == 1
    assert commitment.status.value == "overdue"
    assert delivered == [("Pactlyn reminder", "Send proposal")]
    assert reminders[0].delivered_at is not None


def test_scheduler_defers_notifications_during_quiet_hours(session):
    now = datetime(2026, 11, 2, 23, tzinfo=UTC)
    candidate = CommitmentCandidate(
        title="Quiet-hours task",
        description="Quiet-hours task",
        due_at=now + timedelta(hours=1),
        reminder_at=now - timedelta(minutes=1),
        needs_confirmation=False,
    )
    CommitmentService(session).create(candidate, confirmed=True)
    delivered: list[str] = []
    reminders = ReminderScheduler(
        session,
        lambda _title, body: delivered.append(body),
        quiet_hours_start=22,
        quiet_hours_end=8,
    ).evaluate(now)
    assert reminders
    assert delivered == []
    assert reminders[0].delivered_at is None
    assert reminders[0].scheduled_at.hour == 8
