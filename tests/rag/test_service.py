from __future__ import annotations

import pytest

from pactlyn.llm.gateway import LLMGateway
from pactlyn.memory.service import MemoryService
from pactlyn.rag.embeddings import DeterministicTestEmbedding
from pactlyn.rag.retrieval import HybridRetriever
from pactlyn.rag.service import RAGService
from pactlyn.storage.models import MemoryKind
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore


class LocalAnswerProvider:
    name = "test-local"
    is_local = True

    async def available(self):
        return True

    async def complete(self, messages, *, json_schema=None):
        assert "local evidence" in messages[0]["content"]
        assert "source:semantic/note-1" in messages[1]["content"]
        return "The local record says Rahul owes a proposal update [source:semantic/note-1]."

    async def stream(self, messages):
        yield ""

    async def list_models(self):
        return ["test-local"]


@pytest.mark.asyncio
async def test_rag_answer_cites_local_evidence(tmp_path, session):
    vectors = LocalQdrantStore(tmp_path / "qdrant")
    memory = MemoryService(session, vectors, DeterministicTestEmbedding())
    await memory.remember(
        "Rahul owes a proposal update",
        kind=MemoryKind.SEMANTIC,
        source_type="semantic",
        source_id="note-1",
        verified=True,
    )
    session.commit()
    service = RAGService(
        session,
        LLMGateway(LocalAnswerProvider()),
        HybridRetriever(session, vectors, DeterministicTestEmbedding()),
    )
    answer = await service.answer("What does Rahul owe?")
    assert answer.used_local_model is True
    assert "source:semantic/note-1" in answer.answer
    unknown = await service.answer("What did the bank promise about the mortgage?")
    assert unknown.abstained is True
    assert "enough local evidence" in unknown.answer
    vectors.close()


class UncitedProvider(LocalAnswerProvider):
    async def complete(self, messages, *, json_schema=None):
        return "Rahul owes a proposal update."


@pytest.mark.asyncio
async def test_rag_abstains_when_provider_omits_or_forges_citations(tmp_path, session):
    vectors = LocalQdrantStore(tmp_path / "qdrant")
    memory = MemoryService(session, vectors, DeterministicTestEmbedding())
    await memory.remember(
        "Rahul owes a proposal update",
        kind=MemoryKind.SEMANTIC,
        source_type="semantic",
        source_id="note-1",
        verified=True,
    )
    session.commit()
    service = RAGService(
        session,
        LLMGateway(UncitedProvider()),
        HybridRetriever(session, vectors, DeterministicTestEmbedding()),
    )
    answer = await service.answer("What does Rahul owe?")
    assert answer.abstained is True
    assert "cited answer" in answer.answer
    vectors.close()
