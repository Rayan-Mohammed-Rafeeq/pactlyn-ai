from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from pactlyn.core.commitments import CommitmentExtractor, CommitmentService
from pactlyn.core.scheduler import ReminderScheduler
from pactlyn.email.interfaces import SendResult
from pactlyn.email.service import EmailService
from pactlyn.memory.service import MemoryService
from pactlyn.rag.embeddings import DeterministicTestEmbedding
from pactlyn.rag.retrieval import HybridRetriever
from pactlyn.storage.models import CommitmentRelationshipType, CommitmentStatus, MemoryKind
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore


class FakeProvider:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def send(self, request: object) -> SendResult:
        self.requests.append(request)
        return SendResult(provider_id="e2e-provider-1", state="sent")

    async def status(self, provider_id: str) -> str:
        return "delivered"

    async def list_received(self, cursor: str | None = None) -> tuple[list[dict[str, object]], str | None]:
        return [], cursor

    async def get_received(self, message_id: str) -> dict[str, object]:
        return {"id": message_id}


@pytest.mark.asyncio
async def test_capture_review_persist_index_remind_retrieve_and_approve_email(tmp_path: Path, session: Session) -> None:
    now = datetime(2026, 11, 2, 10, tzinfo=UTC)
    source = "I need to complete my assignment tomorrow and email Rahul the application on Tuesday."
    extraction = CommitmentExtractor().extract(source, now=now)
    assert len(extraction.candidates) == 2

    vectors = LocalQdrantStore(tmp_path / "qdrant")
    memory = MemoryService(session, vectors, DeterministicTestEmbedding())
    commitments = CommitmentService(session).create_many(
        extraction.candidates,
        extraction.relationships,
        source="integration",
    )
    for candidate, commitment in zip(extraction.candidates, commitments, strict=True):
        await memory.remember(
            candidate.evidence,
            kind=MemoryKind.EPISODIC,
            source_type="commitment",
            source_id=commitment.id,
            verified=True,
        )
    session.commit()
    assert all(commitment.id for commitment in commitments)
    assert vectors.search("commitment_memories", (await DeterministicTestEmbedding().embed([source]))[0])

    due = commitments[0].due_at
    assert due is not None
    reminder = commitments[0].reminders[0] if commitments[0].reminders else CommitmentService(session).schedule_reminder(commitments[0].id, due - timedelta(hours=1))
    session.commit()
    delivered: list[str] = []
    ReminderScheduler(session, notify=lambda _title, body: delivered.append(body)).evaluate(now=due)
    assert delivered
    assert reminder.delivered_at is not None

    retriever = HybridRetriever(session, vectors, DeterministicTestEmbedding())
    evidence = await retriever.search("assignment application", limit=5, collection="commitment_memories")
    assert evidence

    provider = FakeProvider()
    email = EmailService(session, provider)
    draft = email.draft(
        sender="me@example.com",
        recipients=["rahul@example.com"],
        subject="Application",
        body_text="Please review the application.",
        commitment_id=commitments[1].id,
    )
    session.commit()
    email.approve(draft.id)
    sent = await email.process_queue()
    assert sent and len(provider.requests) == 1
    assert commitments[1].status not in {CommitmentStatus.COMPLETED, CommitmentStatus.CANCELLED}
    vectors.close()


def test_conditional_multi_person_and_correction_graphs(session: Session) -> None:
    extractor = CommitmentExtractor()

    conditional = extractor.extract(
        "If Rahul doesn't send the document by Friday, I will call Rahul on Monday.",
        now=datetime(2026, 11, 2, 10, tzinfo=UTC),
    )
    assert len(conditional.candidates) == 2
    assert conditional.candidates[0].responsibility == "USER_WAITING_FOR"
    assert conditional.candidates[1].responsibility == "CONDITIONALLY_EXECUTES"
    assert conditional.candidates[1].condition
    assert any(
        relation.relationship == CommitmentRelationshipType.RESPONSE_REQUIRED_FROM
        for relation in conditional.relationships
    )

    workflow = extractor.extract("Email Rahul, call Maya, and contact Aisha next week.")
    assert len(workflow.candidates) == 3
    persisted = CommitmentService(session).create_many(workflow.candidates, workflow.relationships, source="integration-0.7")
    assert [item.event_id for item in persisted] == ["event-1", "event-2", "event-3"]
    assert persisted[1].actor == "user"
    assert persisted[2].source_span

    correction = extractor.extract(
        "I said I would call Rahul Friday, but correction: I will email Rahul Monday instead."
    )
    assert len(correction.candidates) == 2
    assert correction.candidates[0].extraction_status == "cancelled"
    assert correction.relationships[0].relationship == CommitmentRelationshipType.SUPERSEDES
    corrected = CommitmentService(session).create_many(correction.candidates, correction.relationships, source="integration-0.7")
    assert corrected[0].status == CommitmentStatus.CANCELLED
    assert corrected[1].status != CommitmentStatus.CANCELLED


def test_invalid_relationships_preserve_events_and_explain_warnings() -> None:
    from pactlyn.core.commitments import (
        CaptureResult,
        CommitmentCandidate,
        CommitmentRelationshipCandidate,
    )

    result = CaptureResult(
        candidates=[CommitmentCandidate(title="First"), CommitmentCandidate(title="Second")],
        relationships=[
            CommitmentRelationshipCandidate(
                source_index=1,
                target_index=0,
                relationship=CommitmentRelationshipType.FOLLOWED_BY,
            ),
            CommitmentRelationshipCandidate(
                source_index=0,
                target_index=1,
                relationship=CommitmentRelationshipType.DEPENDS_ON,
                source_event_id="missing",
            ),
        ],
    )
    assert len(result.candidates) == 2
    assert not result.relationships
    assert any("FOLLOWED_BY" in warning for warning in result.relationship_warnings)
    assert any("unresolved source" in warning for warning in result.relationship_warnings)


def test_relationship_reasoning_handles_approval_history_and_tentative_actions() -> None:
    extractor = CommitmentExtractor()
    approval = extractor.extract("My professor needs to approve the design before I submit the final report.")
    assert len(approval.candidates) == 2
    assert approval.relationships[0].relationship.value == "DEPENDS_ON"
    assert approval.relationships[0].source_index == 1
    assert approval.relationships[0].target_index == 0

    history = extractor.extract("Rahul sent me the proposal yesterday, and I forwarded it today.")
    assert len(history.candidates) == 2
    assert all(candidate.extraction_status == "completed" for candidate in history.candidates)
    assert all(candidate.due_at is None for candidate in history.candidates)

    tentative = extractor.extract("I might contact HR next week, but I haven't decided yet.")
    assert tentative.candidates
    assert tentative.candidates[0].needs_confirmation is True
