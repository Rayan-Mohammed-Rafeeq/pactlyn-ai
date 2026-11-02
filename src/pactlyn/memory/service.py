from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

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
        record = MemoryRecord(kind=kind, content=content, source_type=source_type, source_id=source_id, user_verified=verified, confidence=1.0 if verified else 0.6)
        self.session.add(record)
        self.session.flush()
        vectors = await self.embedder.embed([content])  # type: ignore[attr-defined]
        collection = {MemoryKind.EPISODIC: COLLECTION_COMMITMENTS, MemoryKind.SEMANTIC: COLLECTION_KNOWLEDGE, MemoryKind.PROCEDURAL: COLLECTION_KNOWLEDGE}[kind]
        self.vectors.upsert(collection, record.id, vectors[0], {"source_id": source_id, "source_type": source_type, "content": content, "memory_id": record.id})
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
