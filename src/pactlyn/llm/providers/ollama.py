from __future__ import annotations

import json
import math
from collections.abc import AsyncIterator

import httpx

from pactlyn.llm.interfaces import EmbeddingDimensionMismatch, EmbeddingUnavailable, LLMUnavailable


class OllamaProvider:
    name = "ollama"
    is_local = True

    def __init__(self, base_url: str, model: str, embedding_model: str, timeout: float = 600.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.model_name = embedding_model
        self.embedding_model = embedding_model
        self.timeout = timeout
        self.dimension: int | None = None

    async def available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/api/tags")
            return response.is_success
        except httpx.HTTPError:
            return False

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            return [str(model["name"]) for model in response.json().get("models", [])]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise LLMUnavailable("Ollama is not available") from exc

    async def version(self) -> str | None:
        """Return the local server version when the server exposes it."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/api/version")
                response.raise_for_status()
            version = response.json().get("version")
            return str(version) if version else None
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    async def model_details(self, model: str | None = None) -> dict[str, object]:
        """Return Ollama's local model metadata without sending user content."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{self.base_url}/api/show", json={"name": model or self.model}
                )
                response.raise_for_status()
            body = response.json()
            return body if isinstance(body, dict) else {}
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise LLMUnavailable(f"Ollama model metadata failed: {exc}") from exc

    async def complete(self, messages: list[dict[str, str]], *, json_schema: dict[str, object] | None = None) -> str:
        payload: dict[str, object] = {"model": self.model, "messages": messages, "stream": False}
        if json_schema:
            payload["format"] = json_schema
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
            return str(response.json()["message"]["content"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMUnavailable(f"Ollama completion failed: {exc}") from exc

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        payload = {"model": self.model, "messages": messages, "stream": True}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content")
                            if content:
                                yield str(content)
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMUnavailable(f"Ollama streaming failed: {exc}") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.embedding_model, "input": texts},
                )
                response.raise_for_status()
            body = response.json()
            raw_vectors = body.get("embeddings")
            if raw_vectors is None and len(texts) == 1:
                raw_vectors = [body.get("embedding")]
            if not isinstance(raw_vectors, list) or len(raw_vectors) != len(texts):
                raise EmbeddingUnavailable("Ollama returned an unexpected embedding count")
            vectors = [self._normalise_vector(vector) for vector in raw_vectors]
            dimensions = {len(vector) for vector in vectors}
            if len(dimensions) != 1:
                raise EmbeddingDimensionMismatch("Ollama returned mixed embedding dimensions")
            dimension = dimensions.pop()
            if self.dimension is not None and self.dimension != dimension:
                raise EmbeddingDimensionMismatch(
                    f"Embedding dimension changed from {self.dimension} to {dimension}"
                )
            self.dimension = dimension
            return vectors
        except EmbeddingDimensionMismatch:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError, EmbeddingUnavailable) as exc:
            raise EmbeddingUnavailable(f"Ollama embedding failed: {exc}") from exc

    @staticmethod
    def _normalise_vector(vector: object) -> list[float]:
        if not isinstance(vector, list) or not vector:
            raise EmbeddingUnavailable("Ollama returned an empty embedding")
        values = [float(value) for value in vector]
        if not all(math.isfinite(value) for value in values):
            raise EmbeddingUnavailable("Ollama returned a non-finite embedding")
        return values
