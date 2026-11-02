from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from pactlyn.vectorstore.interface import VectorStore


@dataclass(frozen=True)
class Evidence:
    source_type: str
    source_id: str
    content: str
    score: float


class HybridRetriever:
    def __init__(self, session: Session, vectors: VectorStore, embedder: object):
        self.session = session
        self.vectors = vectors
        self.embedder = embedder

    async def search(self, query: str, *, limit: int = 5, collection: str = "personal_knowledge") -> list[Evidence]:
        vectors = await self.embedder.embed([query])  # type: ignore[attr-defined]
        semantic = self.vectors.search(collection, vectors[0], limit=limit)
        tokens = re.findall(r"[A-Za-z0-9_]+", query)
        fts_query = " OR ".join(f'"{token}"' for token in tokens) or '""'
        keyword = self.session.execute(text("SELECT commitment_id, title, description, person FROM commitment_fts WHERE commitment_fts MATCH :query LIMIT :limit"), {"query": fts_query, "limit": limit}).mappings().all()
        scores: dict[str, tuple[float, str, str, str]] = {}
        # Reciprocal rank fusion keeps either retrieval path useful.
        for rank, hit in enumerate(semantic, start=1):
            source_id = str(hit.payload.get("source_id", hit.id))
            scores[source_id] = (1 / (60 + rank), str(hit.payload.get("source_type", "memory")), str(hit.payload.get("content", "")), source_id)
        for rank, row in enumerate(keyword, start=1):
            source_id = str(row["commitment_id"])
            prior = scores.get(source_id)
            scores[source_id] = ((prior[0] if prior else 0) + 1 / (60 + rank), "commitment", str(row["description"]), source_id)
        return [Evidence(source_type=value[1], source_id=value[3], content=value[2], score=value[0]) for value in sorted(scores.values(), reverse=True)[:limit]]
