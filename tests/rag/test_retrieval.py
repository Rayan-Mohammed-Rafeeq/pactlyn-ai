from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pactlyn.core.commitments import CommitmentCandidate, CommitmentService
from pactlyn.memory.service import MemoryService
from pactlyn.rag.embeddings import DeterministicTestEmbedding
from pactlyn.rag.ingestion import IngestionService, SourceChunker
from pactlyn.rag.retrieval import HybridRetriever
from pactlyn.storage.models import MemoryKind
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore


@pytest.mark.asyncio
async def test_email_ingestion_preserves_headers_and_hybrid_retrieval(tmp_path, session):
    store = LocalQdrantStore(tmp_path / "qdrant")
    embedder = DeterministicTestEmbedding()
    memory = MemoryService(session, store, embedder)
    document = SourceChunker.email(
        source_id="message-1",
        sender="rahul@example.com",
        recipients=["me@example.com"],
        subject="Project proposal review",
        body="Rahul will review the proposal by Friday.",
        timestamp=datetime(2026, 11, 2, tzinfo=UTC),
        message_id="<message-1>",
        thread_id="thread-1",
    )
    records = await IngestionService(memory).ingest(document)
    CommitmentService(session).create(
        CommitmentCandidate(
            title="Follow up on proposal",
            description="Ask Rahul about the project proposal review",
            person="Rahul",
            needs_confirmation=False,
        ),
        confirmed=True,
    )
    session.commit()
    evidence = await HybridRetriever(session, store, embedder).search("proposal review Rahul", limit=5)
    assert records
    assert any("Rahul" in item.content for item in evidence)
    assert any(item.source_id.startswith("message-1:chunk:") for item in evidence)
    store.close()


@pytest.mark.asyncio
async def test_hybrid_retrieval_sanitizes_punctuation_in_fts_queries(tmp_path, session):
    store = LocalQdrantStore(tmp_path / "qdrant")
    embedder = DeterministicTestEmbedding()
    memory = MemoryService(session, store, embedder)
    await memory.remember(
        "Follow-up with Rahul about the project",
        kind=MemoryKind.SEMANTIC,
        source_type="note",
        source_id="note-follow-up",
    )
    session.commit()
    evidence = await HybridRetriever(session, store, embedder).search("follow-up Rahul", limit=5)
    assert evidence
    store.close()


@pytest.mark.asyncio
async def test_retrieval_modes_and_reranking_preserve_provenance(tmp_path, session):
    store = LocalQdrantStore(tmp_path / "qdrant")
    embedder = DeterministicTestEmbedding()
    memory = MemoryService(session, store, embedder)
    await memory.remember("Professor approves the research design before report submission", kind=MemoryKind.SEMANTIC, source_type="note", source_id="approval-note", verified=True)
    session.commit()
    retriever = HybridRetriever(session, store, embedder)
    for mode in ("dense", "fts5", "hybrid", "rrf"):
        evidence = await retriever.search("research design approval", mode=mode, limit=3)
        assert evidence
        assert all(item.source_id == "approval-note" for item in evidence[:1])
    reranked = await retriever.search("research design approval", mode="hybrid", rerank=True, limit=3)
    assert reranked and reranked[0].source_id == "approval-note"
    store.close()
