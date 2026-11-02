from __future__ import annotations

import httpx

from pactlyn.email.interfaces import SendRequest, SendResult


class ResendProvider:
    """Resend provider; API key is supplied by CredentialStore at composition time."""

    def __init__(self, api_key: str, *, base_url: str = "https://api.resend.com", timeout: float = 30.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def send(self, request: SendRequest) -> SendResult:
        payload: dict[str, object] = {"from": request.sender, "to": request.recipients, "subject": request.subject, "text": request.body_text}
        if request.cc:
            payload["cc"] = request.cc
        if request.bcc:
            payload["bcc"] = request.bcc
        if request.reply_to:
            payload["reply_to"] = request.reply_to
        if request.body_html:
            payload["html"] = request.body_html
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/emails", headers=self._headers(request.idempotency_key), json=payload)
            response.raise_for_status()
        return SendResult(provider_id=str(response.json()["id"]), state="sent")

    async def list_received(self, cursor: str | None = None) -> tuple[list[dict[str, object]], str | None]:
        params = {"limit": "100"}
        if cursor:
            params["after"] = cursor
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/emails/receiving", headers=self._headers(), params=params)
            response.raise_for_status()
        body = response.json()
        return list(body.get("data", [])), body.get("next_page")

    async def get_received(self, message_id: str) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/emails/receiving/{message_id}", headers=self._headers())
            response.raise_for_status()
        return dict(response.json())

    async def status(self, provider_id: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/emails/{provider_id}", headers=self._headers())
            response.raise_for_status()
        return str(response.json().get("last_event", "unknown"))
