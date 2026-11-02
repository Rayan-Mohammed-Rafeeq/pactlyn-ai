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
