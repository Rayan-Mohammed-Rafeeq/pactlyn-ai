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
