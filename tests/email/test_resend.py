from __future__ import annotations

import httpx
import pytest

from pactlyn.email.interfaces import SendRequest
from pactlyn.email.resend.provider import ResendProvider


@pytest.mark.asyncio
async def test_resend_send_uses_stable_idempotency_key(monkeypatch):
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers["Idempotency-Key"]
        return httpx.Response(200, json={"id": "resend-1"})

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    class Client:
        def __init__(self, **_kwargs):
            self.client = real_async_client(transport=transport)

        async def __aenter__(self):
            return self.client

        async def __aexit__(self, *args):
            await self.client.aclose()

    monkeypatch.setattr("pactlyn.email.resend.provider.httpx.AsyncClient", Client)
    result = await ResendProvider("re_test", base_url="https://resend.test").send(SendRequest("a@example.com", ["b@example.com"], [], [], None, "Subject", "Body", None, "pactlyn-action-1"))
    assert result.provider_id == "resend-1"
    assert seen["key"] == "pactlyn-action-1"
