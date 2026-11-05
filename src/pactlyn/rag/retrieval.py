from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from pactlyn.vectorstore.collections import (
    COLLECTION_COMMITMENTS,
    COLLECTION_KNOWLEDGE,
    COLLECTION_PERSONAL_FACTS,
)
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

    async def search(
        self,
        query: str,
        *,
        limit: int = 5,
        collection: str = "personal_knowledge",
        metadata_filter: dict[str, object] | None = None,
        mode: str = "hybrid",
        rerank: bool = False,
    ) -> list[Evidence]:
        semantic = []
        if mode in {"dense", "hybrid", "rrf"}:
            vectors = await self.embedder.embed([query])  # type: ignore[attr-defined]
            # Search all relevant collections and merge.
            for col in (COLLECTION_KNOWLEDGE, COLLECTION_COMMITMENTS, COLLECTION_PERSONAL_FACTS):
                hits = self.vectors.search(col, vectors[0], limit=max(limit, 10), query_filter=metadata_filter)
                semantic.extend(hits)
        keyword = self._keyword_hits(query, limit=max(limit, 10)) if mode in {"fts5", "hybrid", "rrf"} else []
        scores: dict[str, dict[str, Any]] = {}
        if mode == "dense":
            for _rank, hit in enumerate(semantic, start=1):
                self._add_candidate(scores, str(hit.payload.get("source_id", hit.id)), str(hit.payload.get("source_type", "memory")), str(hit.payload.get("content", "")), float(hit.score))
        elif mode == "fts5":
            for rank, row in enumerate(keyword, start=1):
                self._add_candidate(scores, str(row["source_id"]), str(row["source_type"]), str(row["content"]), 1 / (60 + rank))
        else:
            # Both hybrid variants use reciprocal rank fusion; rrf is named
            # explicitly so evaluation can distinguish the configuration.
            for rank, hit in enumerate(sorted(semantic, key=lambda h: h.score, reverse=True), start=1):
                self._add_candidate(scores, str(hit.payload.get("source_id", hit.id)), str(hit.payload.get("source_type", "memory")), str(hit.payload.get("content", "")), 1 / (60 + rank))
            for rank, row in enumerate(keyword, start=1):
                self._add_candidate(scores, str(row["source_id"]), str(row["source_type"]), str(row["content"]), 1 / (60 + rank))
        if rerank:
            query_terms = set(re.findall(r"[A-Za-z0-9_]+", query.casefold()))
            for value in scores.values():
                content_terms = set(re.findall(r"[A-Za-z0-9_]+", str(value["content"]).casefold()))
                overlap = len(query_terms & content_terms) / max(len(query_terms), 1)
                value["score"] = float(value["score"]) + overlap * 0.25 + (0.1 if query.casefold() in str(value["content"]).casefold() else 0.0)
        ranked = sorted(scores.values(), key=lambda value: float(value["score"]), reverse=True)
        return [Evidence(source_type=str(value["source_type"]), source_id=str(value["source_id"]), content=str(value["content"]), score=float(value["score"])) for value in ranked[:limit]]

    def _keyword_hits(self, query: str, *, limit: int) -> list[dict[str, object]]:
        tokens = re.findall(r"[A-Za-z0-9_]+", query)
        fts_query = " OR ".join(f'"{token}"' for token in tokens) or '""'
        rows = list(self.session.execute(
            text("SELECT commitment_id AS source_id, 'commitment' AS source_type, description AS content FROM commitment_fts WHERE commitment_fts MATCH :query LIMIT :limit"),
            {"query": fts_query, "limit": limit},
        ).mappings().all())
        existing = {str(row["source_id"]) for row in rows}
        # Personal-fact FTS search
        pf_rows = list(self.session.execute(
            text(
                "SELECT fact_id AS source_id, 'personal_fact' AS source_type, "
                "display_value AS content FROM personal_fact_fts "
                "WHERE personal_fact_fts MATCH :query LIMIT :limit"
            ),
            {"query": fts_query, "limit": limit},
        ).mappings().all())
        for row in pf_rows:
            if str(row["source_id"]) not in existing:
                rows.append(row)
                existing.add(str(row["source_id"]))
        # General memory_records LIKE scan (fallback)
        for row in self.session.execute(
            text("SELECT source_id, source_type, content FROM memory_records WHERE deleted_at IS NULL AND content LIKE :pattern LIMIT :limit"),
            {"pattern": f"%{tokens[0] if tokens else query}%", "limit": limit},
        ).mappings().all():
            if str(row["source_id"]) not in existing:
                rows.append(row)
        return [dict(row) for row in rows]

    @staticmethod
    def _add_candidate(scores: dict[str, dict[str, Any]], source_id: str, source_type: str, content: str, score: float) -> None:
        if source_id not in scores:
            scores[source_id] = {"source_id": source_id, "source_type": source_type, "content": content, "score": 0.0}
        scores[source_id]["score"] = float(scores[source_id]["score"]) + score
        if not scores[source_id]["content"]:
            scores[source_id]["content"] = content
