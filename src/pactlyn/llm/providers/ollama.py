from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from pactlyn.llm.interfaces import LLMUnavailable


class OllamaProvider:
    name = "ollama"
    is_local = True

    def __init__(self, base_url: str, model: str, embedding_model: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.embedding_model = embedding_model
        self.timeout = timeout

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
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                vectors: list[list[float]] = []
                for text in texts:
                    response = await client.post(f"{self.base_url}/api/embed", json={"model": self.embedding_model, "input": text})
                    response.raise_for_status()
                    body = response.json()
                    vector = body.get("embeddings", [body.get("embedding")])[0]
                    vectors.append([float(value) for value in vector])
            return vectors
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise LLMUnavailable(f"Ollama embedding failed: {exc}") from exc
