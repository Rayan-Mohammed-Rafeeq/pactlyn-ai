from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from pactlyn.storage.models import MemoryRecord, ModelConfiguration
from pactlyn.vectorstore.collections import COLLECTION_COMMITMENTS, COLLECTION_KNOWLEDGE


@dataclass(frozen=True)
class EmbeddingModelState:
    provider: str
    model_name: str
    dimension: int | None
    reindex_required: bool


def activate_embedding_model(session: Session, vectors: object, model_name: str) -> EmbeddingModelState:
    """Activate one embedding model and invalidate only derived vector state.

    SQLite memory/source records remain canonical. If the configured model
    changes, old vectors are removed from Qdrant and all live records become
    pending reindex work so incompatible vectors can never be mixed.
    """
    provider = "ollama-embedding"
    current = session.scalar(
        select(ModelConfiguration).where(
            ModelConfiguration.provider == provider,
            ModelConfiguration.enabled.is_(True),
        )
    )
    reindex_required = False
    if current is None:
        current = ModelConfiguration(provider=provider, model_name=model_name, enabled=True)
        session.add(current)
    elif current.model_name != model_name:
        reindex_required = True
        current.enabled = False
        replacement = ModelConfiguration(provider=provider, model_name=model_name, enabled=True)
        session.add(replacement)
        for record in session.scalars(
            select(MemoryRecord).where(MemoryRecord.deleted_at.is_(None))
        ):
            record.indexed = False
        for collection in (COLLECTION_COMMITMENTS, COLLECTION_KNOWLEDGE):
            reset = getattr(vectors, "reset", None)
            if reset:
                reset(collection)
        current = replacement
    session.commit()
    return EmbeddingModelState(
        provider=provider,
        model_name=current.model_name,
        dimension=current.embedding_dimension,
        reindex_required=reindex_required,
    )


def record_embedding_dimension(session: Session, model_name: str, dimension: int) -> None:
    config = session.scalar(
        select(ModelConfiguration).where(
            ModelConfiguration.provider == "ollama-embedding",
            ModelConfiguration.model_name == model_name,
            ModelConfiguration.enabled.is_(True),
        )
    )
    if config is None:
        return
    if config.embedding_dimension is not None and config.embedding_dimension != dimension:
        raise ValueError(
            f"Embedding dimension changed from {config.embedding_dimension} to {dimension}; reindex is required"
        )
    config.embedding_dimension = dimension
    session.commit()


class DeterministicTestEmbedding:
    """Deterministic embedding for tests and development without Ollama.

    Production semantic indexing should use ``OllamaProvider.embed``. This
    implementation is intentionally namespaced as a test/development adapter.
    """

    model_name = "deterministic-test"
    dimension = 64

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimension
            for token in text.lower().split():
                digest = hashlib.sha256(token.encode()).digest()
                index = int.from_bytes(digest[:2], "big") % self.dimension
                vector[index] += 1.0 if digest[2] % 2 else -1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors
