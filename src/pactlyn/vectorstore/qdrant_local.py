from __future__ import annotations

from pathlib import Path

from qdrant_client import QdrantClient, models

from pactlyn.vectorstore.interface import VectorHit


class LocalQdrantStore:
    """Single-process, persistent Qdrant local mode for the desktop app."""

    def __init__(self, path: Path):
        self.client = QdrantClient(path=str(path))
        self._dimensions: dict[str, int] = {}

    def _ensure_collection(self, collection: str, dimension: int) -> None:
        if collection in self._dimensions:
            return
        if not self.client.collection_exists(collection):
            self.client.create_collection(collection_name=collection, vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE))
        else:
            info = self.client.get_collection(collection)
            configured = info.config.params.vectors
            if isinstance(configured, models.VectorParams) and configured.size != dimension:
                raise ValueError(f"Embedding dimension changed for {collection}; reindex is required")
        self._dimensions[collection] = dimension

    def upsert(self, collection: str, point_id: str, vector: list[float], payload: dict[str, object]) -> None:
        self._ensure_collection(collection, len(vector))
        self.client.upsert(collection_name=collection, points=[models.PointStruct(id=point_id, vector=vector, payload=payload)])

    def search(
        self,
        collection: str,
        vector: list[float],
        limit: int = 5,
        query_filter: dict[str, object] | None = None,
    ) -> list[VectorHit]:
        if not self.client.collection_exists(collection):
            return []
        filter_model = None
        if query_filter:
            scalar_filter = {key: value for key, value in query_filter.items() if isinstance(value, (str, int, bool))}
            filter_model = models.Filter(must=[models.FieldCondition(key=key, match=models.MatchValue(value=value)) for key, value in scalar_filter.items()])
        results = self.client.query_points(collection_name=collection, query=vector, query_filter=filter_model, limit=limit).points
        return [VectorHit(id=str(point.id), score=float(point.score), payload=dict(point.payload or {})) for point in results]

    def delete(self, collection: str, point_id: str) -> None:
        if self.client.collection_exists(collection):
            self.client.delete(collection_name=collection, points_selector=models.PointIdsList(points=[point_id]))

    def reset(self, collection: str) -> None:
        """Drop one local index while preserving canonical SQLite records."""
        if self.client.collection_exists(collection):
            self.client.delete_collection(collection_name=collection)
        self._dimensions.pop(collection, None)

    def dimension(self, collection: str) -> int | None:
        if not self.client.collection_exists(collection):
            return None
        configured = self.client.get_collection(collection).config.params.vectors
        return configured.size if isinstance(configured, models.VectorParams) else None

    def close(self) -> None:
        self.client.close()
