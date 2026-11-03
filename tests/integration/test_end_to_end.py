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
from pactlyn.storage.models import CommitmentStatus, MemoryKind
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
