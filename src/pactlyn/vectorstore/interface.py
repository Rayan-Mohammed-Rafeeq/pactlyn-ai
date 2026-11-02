from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class VectorHit(BaseModel):
    id: str
    score: float
    payload: dict[str, object]


class VectorStore(Protocol):
    def upsert(self, collection: str, point_id: str, vector: list[float], payload: dict[str, object]) -> None: ...

    def search(self, collection: str, vector: list[float], limit: int = 5, query_filter: dict[str, object] | None = None) -> list[VectorHit]: ...

    def delete(self, collection: str, point_id: str) -> None: ...

    def reset(self, collection: str) -> None: ...
