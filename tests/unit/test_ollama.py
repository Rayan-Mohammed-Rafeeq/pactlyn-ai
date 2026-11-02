from __future__ import annotations

import json

import httpx
import pytest

from pactlyn.llm.interfaces import EmbeddingDimensionMismatch
from pactlyn.llm.providers.ollama import OllamaProvider


def _client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    class Client:
        def __init__(self, **_kwargs):
            self.client = real_async_client(transport=transport)

        async def __aenter__(self):
            return self.client

        async def __aexit__(self, *args):
            await self.client.aclose()

    monkeypatch.setattr("pactlyn.llm.providers.ollama.httpx.AsyncClient", Client)


@pytest.mark.asyncio
async def test_ollama_embedding_batches_inputs_and_records_dimension(monkeypatch):
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.2:3b"}]})
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]})

    _client(monkeypatch, handler)
    provider = OllamaProvider("http://ollama.test", "llama3.2:3b", "nomic-embed-text")
    vectors = await provider.embed(["one", "two"])
    assert len(vectors) == 2
    assert provider.dimension == 3
    assert seen["payload"] == {"model": "nomic-embed-text", "input": ["one", "two"]}


@pytest.mark.asyncio
async def test_ollama_rejects_dimension_changes(monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    _client(monkeypatch, handler)
    provider = OllamaProvider("http://ollama.test", "llama3.2:3b", "nomic-embed-text")
    await provider.embed(["one"])
    provider.dimension = 3
    with pytest.raises(EmbeddingDimensionMismatch):
        await provider.embed(["two"])
