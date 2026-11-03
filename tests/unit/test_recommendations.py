from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from pactlyn.core.commitments import (
    CommitmentCandidate,
    CommitmentRelationshipCandidate,
    CommitmentService,
)
from pactlyn.core.recommendations import RecommendationEngine
from pactlyn.storage.models import CommitmentRelationshipType, CommitmentStatus, CommitmentType


def test_recommendation_explains_blocked_dependency(session: Session) -> None:
    service = CommitmentService(session)
    approval, report = service.create_many(
        [
            CommitmentCandidate(title="Get approval", needs_confirmation=False),
            CommitmentCandidate(title="Submit report", needs_confirmation=False),
        ],
        [
            CommitmentRelationshipCandidate(
                source_index=1,
                target_index=0,
                relationship=CommitmentRelationshipType.DEPENDS_ON,
            ),
        ],
    )
    session.commit()
    suggestions = RecommendationEngine(session).recommend()
    assert suggestions
    assert suggestions[0].commitment_ids == (report.id, approval.id)
    assert "depends" in suggestions[0].explanation


def test_recommendation_suggests_follow_up_for_due_waiting_commitment(session: Session) -> None:
    service = CommitmentService(session)
    candidate = CommitmentCandidate(
        title="Wait for HR",
        type=CommitmentType.WAITING_FOR,
        needs_confirmation=False,
        due_at=datetime.now(UTC) - timedelta(days=1),
    )
    commitment = service.create(candidate, confirmed=True)
    session.commit()
    assert commitment.status == CommitmentStatus.WAITING
    suggestions = RecommendationEngine(session).recommend()
    assert any("Follow up" in suggestion.title for suggestion in suggestions)


def test_conditional_follow_up_waits_for_response(session: Session) -> None:
    service = CommitmentService(session)
    waiting, follow_up = service.create_many(
        [
            CommitmentCandidate(
                title="Wait for Rahul",
                type=CommitmentType.WAITING_FOR,
                needs_confirmation=False,
            ),
            CommitmentCandidate(
                title="Call Rahul if needed",
                type=CommitmentType.FOLLOW_UP,
                condition="if Rahul does not reply",
                needs_confirmation=False,
            ),
        ],
        [
            CommitmentRelationshipCandidate(
                source_index=1,
                target_index=0,
                relationship=CommitmentRelationshipType.RESPONSE_REQUIRED_FROM,
            )
        ],
    )
    session.commit()
    held = RecommendationEngine(session).recommend()
    assert any("held" in suggestion.title for suggestion in held)

    waiting.status = CommitmentStatus.RESPONSE_RECEIVED
    session.commit()
    ready = RecommendationEngine(session).recommend()
    assert any(
        suggestion.title == f"Now possible: {follow_up.title}"
        for suggestion in ready
    )
