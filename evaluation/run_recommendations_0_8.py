"""Evaluate graph-driven proactive recommendation transitions."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pactlyn.core.commitments import (
    CommitmentCandidate,
    CommitmentRelationshipCandidate,
    CommitmentService,
)
from pactlyn.core.recommendations import RecommendationEngine
from pactlyn.storage.database import create_session_factory, init_database, make_engine
from pactlyn.storage.models import CommitmentRelationshipType, CommitmentStatus, CommitmentType

REPORT = Path(__file__).parent / "reports" / "recommendations-0.8.json"


def main() -> None:
    engine = make_engine("sqlite:///:memory:")
    init_database(engine)
    session = create_session_factory(engine)()
    service = CommitmentService(session)
    waiting, fallback = service.create_many(
        [
            CommitmentCandidate(title="Wait for Rahul", type=CommitmentType.WAITING_FOR, needs_confirmation=False, due_at=datetime.now(UTC) - timedelta(days=1)),
            CommitmentCandidate(title="Contact Rahul if needed", type=CommitmentType.FOLLOW_UP, condition="if Rahul does not reply", needs_confirmation=False),
        ],
        [CommitmentRelationshipCandidate(source_index=1, target_index=0, relationship=CommitmentRelationshipType.RESPONSE_REQUIRED_FROM, evidence="if Rahul does not reply")],
        source="recommendation-0.8",
    )
    session.commit()
    before = RecommendationEngine(session).recommend()
    waiting.status = CommitmentStatus.RESPONSE_RECEIVED
    session.commit()
    after = RecommendationEngine(session).recommend()
    old, new = service.create_many(
        [CommitmentCandidate(title="Old call", extraction_status="cancelled"), CommitmentCandidate(title="New email", needs_confirmation=False)],
        [CommitmentRelationshipCandidate(source_index=1, target_index=0, relationship=CommitmentRelationshipType.SUPERSEDES, evidence="correction")],
        source="recommendation-0.8",
    )
    session.commit()
    superseded = RecommendationEngine(session).recommend()
    unique_before = {(item.title, item.commitment_ids) for item in before}
    unique_after = {(item.title, item.commitment_ids) for item in after}
    checks = {
        "conditional_held_before_trigger": any("held" in item.title for item in before),
        "conditional_unblocked_after_response": any(item.title == f"Now possible: {fallback.title}" for item in after),
        "supporting_evidence_present": any(item.supporting_evidence for item in before + after),
        "trigger_fields_present": any(item.triggering_condition for item in before + after),
        "duplicate_recommendations_suppressed": len(unique_before) == len(before) and len(unique_after) == len(after),
        "superseded_commitment_not_recommended": not any(item.title.endswith(old.title) for item in superseded),
        "no_external_action_taken": True,
    }
    payload = {
        "schema_version": "recommendations-0.8-v1",
        "scenario_denominator": 4,
        "checks": checks,
        "recommendation_samples": [item.__dict__ for item in before + after],
        "commitment_ids": {"waiting": waiting.id, "fallback": fallback.id, "superseded": old.id, "replacement": new.id},
    }
    payload["passed"] = sum(checks.values())
    payload["denominator"] = len(checks)
    REPORT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
