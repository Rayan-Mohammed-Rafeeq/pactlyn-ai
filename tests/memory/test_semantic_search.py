from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.orm import Session

from pactlyn.memory.semantic import SemanticMemorySearch
from pactlyn.rag.embeddings import DeterministicTestEmbedding
from pactlyn.storage.models import (
    Commitment,
    CommitmentStatus,
    Contact,
    MemoryKind,
    MemoryRecord,
)
from pactlyn.vectorstore.collections import COLLECTION_COMMITMENTS
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore


def test_semantic_search_returns_canonical_memory_and_related_node(
    session: Session,
    tmp_path: Path,
) -> None:
    contact = Contact(name="Professor", email="prof@example.edu")
    commitment = Commitment(
        title="Submit final report",
        status=CommitmentStatus.ACTIVE,
        person="Professor",
        contact_email="prof@example.edu",
        responsibility="USER_WAITING_FOR",
    )
    session.add_all([contact, commitment])
    session.flush()
    memory = MemoryRecord(
        kind=MemoryKind.EPISODIC,
        content="The professor wants the final report by Friday.",
        source_type="commitment",
        source_id=commitment.id,
    )
    session.add(memory)
    session.commit()

    vectors = LocalQdrantStore(tmp_path / "qdrant")
    try:
        embedder = DeterministicTestEmbedding()
        vector = asyncio.run(embedder.embed([memory.content]))[0]
        vectors.upsert(
            COLLECTION_COMMITMENTS,
            memory.id,
            vector,
            {
                "memory_id": memory.id,
                "source_type": "commitment",
                "source_id": commitment.id,
                "content": memory.content,
            },
        )
        hits = asyncio.run(
            SemanticMemorySearch(session, vectors, embedder).search(
                "The professor wants the final report by Friday."
            )
        )
    finally:
        vectors.close()

    assert len(hits) == 1
    assert hits[0].memory_id == memory.id
    assert hits[0].node_id == f"commitment:{commitment.id}"
    assert hits[0].content == memory.content
    assert hits[0].related_label == "Submit final report"


def test_semantic_search_returns_empty_without_vector_hits(
    session: Session,
    tmp_path: Path,
) -> None:
    session.add(
        MemoryRecord(
            kind=MemoryKind.SEMANTIC,
            content="A memory that has not been indexed yet.",
            source_type="note",
            source_id="note-1",
        )
    )
    session.commit()
    vectors = LocalQdrantStore(tmp_path / "qdrant-empty")
    try:
        hits = asyncio.run(
            SemanticMemorySearch(
                session,
                vectors,
                DeterministicTestEmbedding(),
            ).search("unindexed memory")
        )
    finally:
        vectors.close()
    assert hits == ()
