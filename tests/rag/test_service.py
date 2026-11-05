from __future__ import annotations

import pytest

from pactlyn.llm.gateway import LLMGateway
from pactlyn.memory.service import MemoryService
from pactlyn.rag.embeddings import DeterministicTestEmbedding
from pactlyn.rag.retrieval import HybridRetriever
from pactlyn.rag.service import RAGService
from pactlyn.storage.models import MemoryKind
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore


class SimpleProvider:
    """Provider that answers using whatever context it receives."""
    name = "test-local"
    is_local = True

    async def available(self):
        return True

    async def complete(self, messages, *, json_schema=None):
        # Echo back something that confirms context was passed
        context = messages[1]["content"] if len(messages) > 1 else ""
        if "Rahul" in context:
            return "Rahul owes a proposal update."
        return "I don't have information about that."

    async def stream(self, messages):
        yield ""

    async def list_models(self):
        return ["test-local"]


class HallucinatedCitationProvider(SimpleProvider):
    async def complete(self, messages, *, json_schema=None):
        return "Rahul owes you [source:semantic/nonexistent-id-999]."


@pytest.mark.asyncio
async def test_rag_answers_when_evidence_exists(tmp_path, session):
    """When matching evidence is found, the LLM is called and the answer returned."""
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
        LLMGateway(SimpleProvider()),
        HybridRetriever(session, vectors, DeterministicTestEmbedding()),
    )
    answer = await service.answer("What does Rahul owe?")
    assert answer.used_local_model is True
    assert answer.abstained is False
    assert "Rahul" in answer.answer
    vectors.close()


@pytest.mark.asyncio
async def test_rag_abstains_when_no_evidence(tmp_path, session):
    """With no records at all, the service abstains without calling the LLM."""
    vectors = LocalQdrantStore(tmp_path / "qdrant")
    service = RAGService(
        session,
        LLMGateway(SimpleProvider()),
        HybridRetriever(session, vectors, DeterministicTestEmbedding()),
    )
    answer = await service.answer("What did the bank promise about the mortgage?")
    assert answer.abstained is True
    vectors.close()


@pytest.mark.asyncio
async def test_rag_abstains_when_provider_forges_citations(tmp_path, session):
    """An answer that includes a hallucinated [source:] citation is rejected."""
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
        LLMGateway(HallucinatedCitationProvider()),
        HybridRetriever(session, vectors, DeterministicTestEmbedding()),
    )
    answer = await service.answer("What does Rahul owe?")
    assert answer.abstained is True
    vectors.close()
