from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SendRequest:
    sender: str
    recipients: list[str]
    cc: list[str]
    bcc: list[str]
    reply_to: str | None
    subject: str
    body_text: str
    body_html: str | None
    idempotency_key: str


@dataclass(frozen=True)
class SendResult:
    provider_id: str
    state: str


class EmailProvider(Protocol):
    async def send(self, request: SendRequest) -> SendResult: ...

    async def list_received(self, cursor: str | None = None) -> tuple[list[dict[str, object]], str | None]: ...

    async def get_received(self, message_id: str) -> dict[str, object]: ...

    async def status(self, provider_id: str) -> str: ...
