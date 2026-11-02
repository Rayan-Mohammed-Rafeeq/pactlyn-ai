from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pactlyn.core.commitments import CommitmentExtractor, CommitmentService
from pactlyn.storage.models import CommitmentStatus, CommitmentType


def test_waiting_for_capture_requires_follow_up_confirmation():
    result = CommitmentExtractor().extract("I'm waiting for the placement coordinator to send my interview details.")
    candidate = result.candidates[0]
    assert candidate.type == CommitmentType.WAITING_FOR
    assert candidate.needs_confirmation is True
    assert candidate.person is not None


def test_relative_deadline_is_parsed_and_persisted(session):
    now = datetime(2026, 11, 2, 10, tzinfo=UTC)
    result = CommitmentExtractor().extract("I need to submit my assignment by Friday", now=now)
    candidate = result.candidates[0]
    assert candidate.due_at == datetime(2026, 11, 6, 17, tzinfo=UTC)
    commitment = CommitmentService(session).create(candidate, confirmed=True)
    session.commit()
    assert commitment.status == CommitmentStatus.ACTIVE
    assert CommitmentService(session).get(commitment.id) is not None


def test_duplicate_reminder_schedule_is_deduplicated(session):
    result = CommitmentExtractor().extract("Finish the report tomorrow", now=datetime.now(UTC))
    service = CommitmentService(session)
    commitment = service.create(result.candidates[0], confirmed=True)
    first = service.schedule_reminder(commitment.id, datetime.now(UTC) + timedelta(hours=1))
    second = service.schedule_reminder(commitment.id, first.scheduled_at)
    assert first.id == second.id
