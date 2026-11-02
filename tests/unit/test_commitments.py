from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from pactlyn.core.commitments import CommitmentCandidate, CommitmentExtractor, CommitmentService
from pactlyn.storage.models import CommitmentStatus, CommitmentType


def test_waiting_for_capture_requires_follow_up_confirmation():
    result = CommitmentExtractor().extract("I'm waiting for the placement coordinator to send my interview details.")
    candidate = result.candidates[0]
    assert candidate.type == CommitmentType.WAITING_FOR
    assert candidate.needs_confirmation is True
    assert candidate.person is not None


def test_waiting_for_named_person_does_not_include_following_verb():
    result = CommitmentExtractor().extract(
        "I'm waiting for Rahul to send me the project proposal by Friday."
    )
    assert result.candidates[0].person == "Rahul"


def test_relative_dates_are_timezone_aware_and_reproducible():
    now = datetime(2026, 11, 2, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
    result = CommitmentExtractor().extract("Finish it in three days", now=now, timezone_name="Asia/Kolkata")
    assert result.candidates[0].due_at == datetime(2026, 11, 5, 11, 30, tzinfo=UTC)

    end_of_week = CommitmentExtractor().extract(
        "Submit by end of this week", now=now, timezone_name="Asia/Kolkata"
    )
    assert end_of_week.candidates[0].due_at == datetime(2026, 11, 6, 11, 30, tzinfo=UTC)


def test_relative_deadline_is_parsed_and_persisted(session):
    now = datetime(2026, 11, 2, 10, tzinfo=UTC)
    result = CommitmentExtractor().extract("I need to submit my assignment by Friday", now=now)
    candidate = result.candidates[0]
    assert candidate.due_at == datetime(2026, 11, 6, 17, tzinfo=UTC)
    commitment = CommitmentService(session).create(candidate, confirmed=True)
    session.commit()
    assert commitment.status == CommitmentStatus.ACTIVE
    assert CommitmentService(session).get(commitment.id) is not None


def test_relative_deadline_uses_configured_timezone():
    now = datetime(2026, 11, 2, 18, tzinfo=UTC)
    result = CommitmentExtractor().extract(
        "Finish the assignment tomorrow",
        now=now,
        timezone_name="Asia/Kolkata",
    )
    assert result.candidates[0].due_at == datetime(2026, 11, 3, 11, 30, tzinfo=UTC)


def test_duplicate_reminder_schedule_is_deduplicated(session):
    result = CommitmentExtractor().extract("Finish the report tomorrow", now=datetime.now(UTC))
    service = CommitmentService(session)
    commitment = service.create(result.candidates[0], confirmed=True)
    first = service.schedule_reminder(commitment.id, datetime.now(UTC) + timedelta(hours=1))
    second = service.schedule_reminder(commitment.id, first.scheduled_at)
    assert first.id == second.id


def test_existing_contact_email_is_associated(session):
    from pactlyn.storage.models import Contact

    session.add(Contact(name="Rahul", email="rahul@example.com"))
    session.flush()
    candidate = CommitmentCandidate(
        title="Ask Rahul",
        description="Ask Rahul for an update",
        person="Rahul",
        needs_confirmation=False,
    )
    commitment = CommitmentService(session).create(candidate, confirmed=True)
    assert commitment.contact_email == "rahul@example.com"
