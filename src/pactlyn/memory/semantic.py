from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import cast

from sqlalchemy.orm import Session

from pactlyn.llm.interfaces import EmbeddingProvider
from pactlyn.memory.graph import GraphRecord, KnowledgeGraphRepository
from pactlyn.vectorstore.collections import COLLECTION_COMMITMENTS, COLLECTION_KNOWLEDGE
from pactlyn.vectorstore.interface import VectorStore


@dataclass(frozen=True)
class SemanticMemoryHit:
    """One canonical memory found through the local vector index."""

    memory_id: str
    content: str
    source: str
    score: float
    node_id: str
    related_label: str


class SemanticMemorySearch:
    """Discover related canonical memories without creating graph edges.

    Qdrant is an optional discovery aid. The returned memory records still
    come from SQLite, and the graph itself is built only from canonical rows
    and their typed relationships.
    """

    def __init__(
        self,
        session: Session,
        vectors: VectorStore,
        embedder: object,
        *,
        timeout: float = 8.0,
    ):
        self.session = session
        self.vectors = vectors
        self.embedder = embedder
        self.timeout = timeout

    async def search(self, query: str, *, limit: int = 8) -> tuple[SemanticMemoryHit, ...]:
        cleaned = query.strip()
        if not cleaned:
            return ()
        embedder = cast(EmbeddingProvider, self.embedder)
        embeddings = await asyncio.wait_for(
            embedder.embed([cleaned]),
            timeout=self.timeout,
        )
        if not embeddings or not embeddings[0]:
            return ()
        vector = embeddings[0]
        raw_hits = [
            *self.vectors.search(
                COLLECTION_COMMITMENTS,
                vector,
                limit=max(limit * 2, 10),
            ),
            *self.vectors.search(
                COLLECTION_KNOWLEDGE,
                vector,
                limit=max(limit * 2, 10),
            ),
        ]
        if not raw_hits:
            return ()

        graph = KnowledgeGraphRepository(self.session).build()
        records_by_id = {record.id: record for record in graph.records}
        records_by_source = {
            (record.source_type, record.source_id.split(":chunk:", 1)[0]): record
            for record in graph.records
        }
        found: dict[str, SemanticMemoryHit] = {}
        for hit in sorted(raw_hits, key=lambda item: item.score, reverse=True):
            payload = hit.payload
            memory_id = str(payload.get("memory_id") or hit.id)
            record = records_by_id.get(memory_id)
            if record is None:
                source_type = str(payload.get("source_type") or "")
                source_id = str(payload.get("source_id") or "").split(":chunk:", 1)[0]
                record = records_by_source.get((source_type, source_id))
            if (
                record is None
                or record.related_node_id is None
                or graph.node(record.related_node_id) is None
            ):
                continue
            if record.id in found:
                continue
            found[record.id] = self._hit(record, float(hit.score))
            if len(found) >= limit:
                break
        return tuple(found.values())

    @staticmethod
    def _hit(record: GraphRecord, score: float) -> SemanticMemoryHit:
        return SemanticMemoryHit(
            memory_id=record.id,
            content=record.content,
            source=record.source,
            score=score,
            node_id=record.related_node_id or "",
            related_label=record.related_label,
        )
