"""Exercise graph validation, audit persistence, and deletion consistency."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from pactlyn.core.commitments import (
    CaptureResult,
    CommitmentCandidate,
    CommitmentRelationshipCandidate,
    CommitmentService,
)
from pactlyn.storage.database import create_session_factory, init_database, make_engine
from pactlyn.storage.models import CommitmentRelationshipReview, CommitmentRelationshipType

REPORT = Path(__file__).parent / "reports" / "graph-integrity-0.8.json"


def main() -> None:
    checks: dict[str, bool] = {}
    invalid = CaptureResult(
        candidates=[CommitmentCandidate(title="A"), CommitmentCandidate(title="B")],
        relationships=[
            CommitmentRelationshipCandidate(source_index=0, target_index=0, relationship=CommitmentRelationshipType.DEPENDS_ON, evidence="A requires A"),
            CommitmentRelationshipCandidate(source_index=2, target_index=0, relationship=CommitmentRelationshipType.RELATED_TO, evidence="missing"),
        ],
    )
    checks["events_preserved_after_rejection"] = len(invalid.candidates) == 2
    checks["rejected_edges_explained"] = len(invalid.rejected_relationships) == 2 and all(item.rejection_reason for item in invalid.rejected_relationships)
    cycle = CaptureResult(
        candidates=[CommitmentCandidate(title="A"), CommitmentCandidate(title="B")],
        relationships=[
            CommitmentRelationshipCandidate(source_index=0, target_index=1, relationship=CommitmentRelationshipType.DEPENDS_ON),
            CommitmentRelationshipCandidate(source_index=1, target_index=0, relationship=CommitmentRelationshipType.DEPENDS_ON),
        ],
    )
    checks["dependency_cycle_detected"] = any("cycle" in warning.casefold() for warning in cycle.relationship_warnings)
    with tempfile.TemporaryDirectory(prefix="pactlyn-graph-08-") as directory:
        engine = make_engine(f"sqlite:///{Path(directory) / 'graph.sqlite3'}")
        init_database(engine)
        session = create_session_factory(engine)()
        service = CommitmentService(session)
        commitments = service.create_many(invalid.candidates, [], rejected_relationships=invalid.rejected_relationships, source="graph-0.8")
        valid = service.create_many(
            [CommitmentCandidate(title="Prerequisite", needs_confirmation=False), CommitmentCandidate(title="Action", needs_confirmation=False)],
            [CommitmentRelationshipCandidate(source_index=1, target_index=0, relationship=CommitmentRelationshipType.DEPENDS_ON, evidence="Action requires prerequisite", confidence=0.91)],
            source="graph-0.8",
        )
        session.commit()
        persisted = service.related(valid[1].id)[0][0]
        checks["valid_edge_evidence_persisted"] = persisted.evidence == "Action requires prerequisite" and persisted.confidence == 0.91
        checks["rejected_edge_audit_persisted"] = session.query(CommitmentRelationshipReview).count() == 2
        session.delete(commitments[0])
        session.commit()
        checks["edge_deletion_consistent"] = bool(service.related(valid[1].id)) and session.query(CommitmentRelationshipReview).count() == 2 and all(
            item.source_commitment_id is None or item.target_commitment_id is None
            for item in session.query(CommitmentRelationshipReview).all()
        )
        session.close()
        engine.dispose()
    payload = {
        "schema_version": "graph-integrity-0.8-v1",
        "checks": checks,
        "passed": sum(checks.values()),
        "denominator": len(checks),
        "known_limitation": "Relationship review records preserve rejected indexes and evidence; unresolved endpoints remain nullable by design.",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
