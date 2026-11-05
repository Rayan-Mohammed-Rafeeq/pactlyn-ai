from __future__ import annotations

import httpx
import pytest

from pactlyn.email.resend.connection import ConnectionStatus
from pactlyn.email.resend.provider import ResendProvider


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(recording_handler)
    real_async_client = httpx.AsyncClient

    class Client:
        def __init__(self, **_kwargs):
            self.client = real_async_client(transport=transport)

        async def __aenter__(self):
            return self.client

        async def __aexit__(self, *args):
            await self.client.aclose()

    monkeypatch.setattr("pactlyn.email.resend.provider.httpx.AsyncClient", Client)
    return requests


def _domains(*, status: str = "verified", sending: str = "enabled", receiving: str = "enabled") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": "domain-1",
                    "name": "example.com",
                    "status": status,
                    "capabilities": {"sending": sending, "receiving": receiving},
                }
            ],
            "has_more": False,
        },
    )


@pytest.mark.asyncio
async def test_valid_key_verified_domain_and_receiving_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/domains":
            return _domains()
        if request.url.path == "/emails/receiving":
            return httpx.Response(200, json={"data": [], "has_more": False})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    requests = _patch_client(monkeypatch, handler)
    result = await ResendProvider("re_test").check_connection(
        sender_email="Pactlyn <pactlyn@example.com>",
        receiving_email="inbox@abc123.resend.app",
    )
    assert result.status == ConnectionStatus.CONNECTED
    assert result.sender_verified is True
    assert result.sender_domain == "example.com"
    assert result.receiving_domain_configured is True
    assert result.receiving_api_ok is True
    assert all(request.method == "GET" for request in requests)
    assert not any(request.method == "POST" for request in requests)


@pytest.mark.asyncio
async def test_missing_api_key_is_reported() -> None:
    result = await ResendProvider("").check_connection(
        sender_email="pactlyn@example.com"
    )
    assert result.status == ConnectionStatus.CREDENTIALS_MISSING
    assert "No Resend API key" in result.message


@pytest.mark.asyncio
async def test_invalid_sender_address_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _domains()

    _patch_client(monkeypatch, handler)
    result = await ResendProvider("re_test").check_connection(sender_email="not-an-email")
    assert result.status == ConnectionStatus.INVALID_SENDER
    assert "not valid" in result.message


@pytest.mark.asyncio
async def test_invalid_api_key_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "API key is invalid"})

    _patch_client(monkeypatch, handler)
    result = await ResendProvider("re_bad").check_connection(
        sender_email="pactlyn@example.com"
    )
    assert result.status == ConnectionStatus.INVALID_API_KEY
    assert "API key" in result.message


@pytest.mark.asyncio
async def test_network_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down", request=request)

    _patch_client(monkeypatch, handler)
    result = await ResendProvider("re_test").check_connection(
        sender_email="pactlyn@example.com"
    )
    assert result.status == ConnectionStatus.NETWORK_UNAVAILABLE


@pytest.mark.asyncio
async def test_unverified_sender_domain_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _domains(status="pending")

    _patch_client(monkeypatch, handler)
    result = await ResendProvider("re_test").check_connection(
        sender_email="pactlyn@example.com"
    )
    assert result.status == ConnectionStatus.SENDER_DOMAIN_UNVERIFIED
    assert result.sender_verified is False
    assert "not verified" in result.message


@pytest.mark.asyncio
async def test_sending_only_key_explains_missing_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "restricted key"})

    _patch_client(monkeypatch, handler)
    result = await ResendProvider("re_sending_only").check_connection(
        sender_email="pactlyn@example.com",
        receiving_email="inbox@abc123.resend.app",
    )
    assert result.status == ConnectionStatus.CONNECTED
    assert result.restricted_key is True
    assert result.receiving_api_ok is False
    assert "full-access" in result.message


@pytest.mark.asyncio
async def test_personal_mailbox_cannot_be_used_as_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _domains()

    _patch_client(monkeypatch, handler)
    result = await ResendProvider("re_test").check_connection(
        sender_email="someone@gmail.com"
    )
    assert result.status == ConnectionStatus.INVALID_SENDER
    assert "cannot be a Resend sender" in result.message


@pytest.mark.asyncio
async def test_rate_limit_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "Too many requests"})

    _patch_client(monkeypatch, handler)
    result = await ResendProvider("re_test").check_connection(
        sender_email="pactlyn@example.com"
    )
    assert result.status == ConnectionStatus.RATE_LIMITED


@pytest.mark.asyncio
async def test_provider_downtime_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "Service unavailable"})

    _patch_client(monkeypatch, handler)
    result = await ResendProvider("re_test").check_connection(
        sender_email="pactlyn@example.com"
    )
    assert result.status == ConnectionStatus.PROVIDER_ERROR
    assert "503" in result.message


@pytest.mark.asyncio
async def test_personal_mailbox_cannot_be_used_as_receiving_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/domains":
            return _domains()
        return httpx.Response(200, json={"data": [], "has_more": False})

    _patch_client(monkeypatch, handler)
    result = await ResendProvider("re_test").check_connection(
        sender_email="pactlyn@example.com",
        receiving_email="someone@gmail.com",
    )
    assert result.receiving_domain_configured is False
    assert "personal mailbox" in result.receiving_message
