from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from pactlyn.llm.interfaces import LLMUnavailable


class OpenRouterProvider:
    name = "openrouter"
    is_local = False

    def __init__(self, api_key: str, model: str, timeout: float = 60.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.base_url = "https://openrouter.ai/api/v1"

    async def available(self) -> bool:
        return bool(self.api_key and self.model)

    async def list_models(self) -> list[str]:
        return [self.model]

    async def complete(self, messages: list[dict[str, str]], *, json_schema: dict[str, object] | None = None) -> str:
        payload: dict[str, object] = {"model": self.model, "messages": messages}
        if json_schema:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "pactlyn_output", "schema": json_schema}}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=payload)
                response.raise_for_status()
            return str(response.json()["choices"][0]["message"]["content"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMUnavailable(f"OpenRouter completion failed: {exc}") from exc

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        payload = {"model": self.model, "messages": messages, "stream": True}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", f"{self.base_url}/chat/completions", headers=self._headers(), json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: ") and line != "data: [DONE]":
                            content = json.loads(line[6:]).get("choices", [{}])[0].get("delta", {}).get("content")
                            if content:
                                yield str(content)
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMUnavailable(f"OpenRouter streaming failed: {exc}") from exc

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "X-Title": "Pactlyn"}
