from __future__ import annotations

import pytest

from pactlyn.memory.service import MemoryService
from pactlyn.rag.embeddings import DeterministicTestEmbedding
from pactlyn.storage.models import MemoryKind
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore


@pytest.mark.asyncio
async def test_qdrant_and_memory_persist(tmp_path, session):
    store = LocalQdrantStore(tmp_path / "qdrant")
    memory_service = MemoryService(session, store, DeterministicTestEmbedding())
    record = await memory_service.remember("Rahul reviews project proposals", kind=MemoryKind.SEMANTIC, source_type="note", source_id="note-1")
    session.commit()
    hits = store.search("personal_knowledge", (await DeterministicTestEmbedding().embed(["Rahul project"]))[0])
    assert hits and hits[0].payload["memory_id"] == record.id
    store.close()


@pytest.mark.asyncio
async def test_memory_deletion_removes_qdrant_point(tmp_path, session):
    store = LocalQdrantStore(tmp_path / "qdrant")
    service = MemoryService(session, store, DeterministicTestEmbedding())
    record = await service.remember("Delete this private note", kind=MemoryKind.SEMANTIC, source_type="note", source_id="delete-me")
    session.commit()
    vector = (await DeterministicTestEmbedding().embed([record.content]))[0]
    assert store.search("personal_knowledge", vector)
    service.delete(record.id)
    assert not store.search("personal_knowledge", vector)
    store.close()


@pytest.mark.asyncio
async def test_memory_source_is_not_indexed_twice(tmp_path, session):
    store = LocalQdrantStore(tmp_path / "qdrant")
    service = MemoryService(session, store, DeterministicTestEmbedding())
    first = await service.remember(
        "Same source", kind=MemoryKind.SEMANTIC, source_type="note", source_id="same-source"
    )
    second = await service.remember(
        "Same source", kind=MemoryKind.SEMANTIC, source_type="note", source_id="same-source"
    )
    assert first.id == second.id
    assert len(service.list()) == 1
    store.close()
