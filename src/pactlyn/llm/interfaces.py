from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    pass


class EmbeddingUnavailable(LLMUnavailable):
    """The configured local embedding model could not produce a vector."""


class EmbeddingDimensionMismatch(ValueError):
    """A provider returned vectors with incompatible dimensions."""


class LLMProvider(Protocol):
    name: str
    is_local: bool

    async def available(self) -> bool: ...

    async def list_models(self) -> list[str]: ...

    async def complete(self, messages: list[dict[str, str]], *, json_schema: dict[str, object] | None = None) -> str: ...

    def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...


class EmbeddingProvider(Protocol):
    model_name: str
    dimension: int | None

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
