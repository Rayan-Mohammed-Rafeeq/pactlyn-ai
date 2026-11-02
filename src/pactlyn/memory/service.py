from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from pactlyn.llm.interfaces import LLMUnavailable
from pactlyn.rag.embeddings import record_embedding_dimension
from pactlyn.storage.models import MemoryKind, MemoryRecord
from pactlyn.vectorstore.collections import (
    COLLECTION_COMMITMENTS,
    COLLECTION_KNOWLEDGE,
)
from pactlyn.vectorstore.interface import VectorStore


class MemoryService:
    def __init__(self, session: Session, vectors: VectorStore, embedder: object):
        self.session = session
        self.vectors = vectors
        self.embedder = embedder

    async def remember(self, content: str, *, kind: MemoryKind, source_type: str, source_id: str, verified: bool = False) -> MemoryRecord:
        existing = self.session.scalar(
            select(MemoryRecord).where(
                MemoryRecord.deleted_at.is_(None),
                MemoryRecord.source_type == source_type,
                MemoryRecord.source_id == source_id,
                MemoryRecord.content == content,
            )
        )
        if existing:
            return existing
        record = MemoryRecord(kind=kind, content=content, source_type=source_type, source_id=source_id, user_verified=verified, confidence=1.0 if verified else 0.6)
        self.session.add(record)
        self.session.flush()
        collection = {MemoryKind.EPISODIC: COLLECTION_COMMITMENTS, MemoryKind.SEMANTIC: COLLECTION_KNOWLEDGE, MemoryKind.PROCEDURAL: COLLECTION_KNOWLEDGE}[kind]
        try:
            vectors = await self.embedder.embed([content])  # type: ignore[attr-defined]
            if len(vectors) != 1 or not vectors[0]:
                raise ValueError("Embedding provider returned no vector")
            configured_dimension = getattr(self.embedder, "dimension", None)
            if configured_dimension is not None and len(vectors[0]) != configured_dimension:
                raise ValueError(
                    f"Embedding dimension {len(vectors[0])} does not match provider dimension {configured_dimension}"
                )
            model_name = getattr(self.embedder, "model_name", None)
            if model_name:
                record_embedding_dimension(self.session, str(model_name), len(vectors[0]))
            self.vectors.upsert(collection, record.id, vectors[0], {"source_id": source_id, "source_type": source_type, "content": content, "memory_id": record.id})
            record.indexed = True
        except LLMUnavailable:
            # Structured memory remains durable; callers can reindex it once
            # the local embedding model is available again.
            record.indexed = False
        return record

    def list(self, *, kind: MemoryKind | None = None) -> list[MemoryRecord]:
        query = select(MemoryRecord).where(MemoryRecord.deleted_at.is_(None)).order_by(MemoryRecord.created_at.desc())
        if kind:
            query = query.where(MemoryRecord.kind == kind)
        return list(self.session.scalars(query))

    def delete(self, memory_id: str) -> None:
        record = self.session.get(MemoryRecord, memory_id)
        if not record:
            return
        record.deleted_at = datetime.utcnow()
        collection = {MemoryKind.EPISODIC: COLLECTION_COMMITMENTS, MemoryKind.SEMANTIC: COLLECTION_KNOWLEDGE, MemoryKind.PROCEDURAL: COLLECTION_KNOWLEDGE}[record.kind]
        self.vectors.delete(collection, memory_id)
        self.session.commit()

    async def reindex_pending(self) -> int:
        records = list(
            self.session.scalars(
                select(MemoryRecord).where(
                    MemoryRecord.deleted_at.is_(None), MemoryRecord.indexed.is_(False)
                )
            )
        )
        count = 0
        for record in records:
            vectors = await self.embedder.embed([record.content])  # type: ignore[attr-defined]
            if len(vectors) != 1 or not vectors[0]:
                raise ValueError("Embedding provider returned no vector")
            model_name = getattr(self.embedder, "model_name", None)
            if model_name:
                record_embedding_dimension(self.session, str(model_name), len(vectors[0]))
            collection = {
                MemoryKind.EPISODIC: COLLECTION_COMMITMENTS,
                MemoryKind.SEMANTIC: COLLECTION_KNOWLEDGE,
                MemoryKind.PROCEDURAL: COLLECTION_KNOWLEDGE,
            }[record.kind]
            self.vectors.upsert(collection, record.id, vectors[0], {"source_id": record.source_id, "source_type": record.source_type, "content": record.content, "memory_id": record.id})
            record.indexed = True
            count += 1
        self.session.commit()
        return count
