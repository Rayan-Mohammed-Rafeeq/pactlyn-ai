from __future__ import annotations

from typing import cast

import httpx

from pactlyn.email.addresses import (
    email_address,
    email_domain,
    is_public_mailbox_domain,
    is_resend_managed_receiving_address,
    is_valid_email_address,
)
from pactlyn.email.interfaces import SendRequest, SendResult
from pactlyn.email.resend.connection import (
    ConnectionCheck,
    ConnectionStatus,
    DomainInfo,
)


class ResendProvider:
    """Resend provider; API key is supplied by CredentialStore at composition time."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.resend.com",
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def send(self, request: SendRequest) -> SendResult:
        payload: dict[str, object] = {
            "from": request.sender,
            "to": request.recipients,
            "subject": request.subject,
            "text": request.body_text,
        }
        if request.cc:
            payload["cc"] = request.cc
        if request.bcc:
            payload["bcc"] = request.bcc
        if request.reply_to:
            payload["reply_to"] = request.reply_to
        if request.body_html:
            payload["html"] = request.body_html
        if request.headers:
            payload["headers"] = request.headers
        if request.attachments:
            payload["attachments"] = [
                {
                    "filename": item.get("filename", "attachment"),
                    "content": item.get("content_base64", ""),
                    "content_type": item.get("content_type", "application/octet-stream"),
                }
                for item in request.attachments
            ]
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/emails",
                headers=self._headers(request.idempotency_key),
                json=payload,
            )
            response.raise_for_status()
        body = self._json(response)
        return SendResult(provider_id=str(body["id"]), state="sent")

    async def list_received(
        self, cursor: str | None = None, *, limit: int = 100
    ) -> tuple[list[dict[str, object]], str | None]:
        params = {"limit": str(max(1, min(100, limit)))}
        if cursor:
            params["after"] = cursor
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/emails/receiving", headers=self._headers(), params=params
            )
            response.raise_for_status()
        body = self._json(response)
        data = body.get("data", [])
        records = (
            [cast(dict[str, object], item) for item in data] if isinstance(data, list) else []
        )
        next_cursor = body.get("next_page")
        if not next_cursor and body.get("has_more") and records:
            last_id = records[-1].get("id")
            next_cursor = str(last_id) if last_id else None
        return records, str(next_cursor) if next_cursor else None

    async def get_received(self, message_id: str) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/emails/receiving/{message_id}", headers=self._headers()
            )
            response.raise_for_status()
        return self._json(response)

    async def list_domains(self) -> list[dict[str, object]]:
        domains: list[dict[str, object]] = []
        cursor: str | None = None
        while True:
            params = {"limit": "100"}
            if cursor:
                params["after"] = cursor
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/domains", headers=self._headers(), params=params
                )
                response.raise_for_status()
            body = self._json(response)
            data = body.get("data", [])
            page = (
                [cast(dict[str, object], item) for item in data] if isinstance(data, list) else []
            )
            domains.extend(page)
            if not body.get("has_more") or not page:
                break
            last_id = page[-1].get("id")
            if not last_id:
                break
            cursor = str(last_id)
        return domains

    async def status(self, provider_id: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/emails/{provider_id}", headers=self._headers()
            )
            response.raise_for_status()
        return str(self._json(response).get("last_event", "unknown"))

    async def check_connection(
        self,
        *,
        sender_email: str | None = None,
        receiving_email: str | None = None,
    ) -> ConnectionCheck:
        """Verify credentials and domain status without sending an email.

        The only provider requests made here are safe reads: ``GET /domains``
        and, when a receiving address is configured, a one-item
        ``GET /emails/receiving`` query.  No message is sent during a
        connection test.
        """

        sender = (sender_email or "").strip()
        receiving = (receiving_email or "").strip()
        if not self.api_key:
            return ConnectionCheck(
                status=ConnectionStatus.CREDENTIALS_MISSING,
                message="No Resend API key is saved. Add one in Settings → Email.",
            )

        restricted_key = False
        try:
            raw_domains = await self.list_domains()
        except httpx.HTTPStatusError as exc:
            failure = self._status_failure(exc)
            if failure.status == ConnectionStatus.PERMISSION_DENIED:
                restricted_key = True
                raw_domains = []
            else:
                return failure
        except httpx.RequestError as exc:
            return self._network_failure(exc)

        domains = tuple(self._domain_info(item) for item in raw_domains)
        by_name = {domain.name.lower(): domain for domain in domains}

        sender_domain = email_domain(sender)
        sender_status: str | None = None
        sender_verified = False
        if sender:
            if not is_valid_email_address(sender) or not sender_domain:
                return ConnectionCheck(
                    status=ConnectionStatus.INVALID_SENDER,
                    message="The configured sender email address is not valid.",
                    domains=domains,
                    restricted_key=restricted_key,
                )
            if is_public_mailbox_domain(sender):
                return ConnectionCheck(
                    status=ConnectionStatus.INVALID_SENDER,
                    message=(
                        "A personal Gmail, Outlook or similar address cannot be a "
                        "Resend sender. Verify a domain you own and use an address "
                        "at that domain."
                    ),
                    sender_domain=sender_domain,
                    domains=domains,
                    restricted_key=restricted_key,
                )
            record = by_name.get(sender_domain)
            if record:
                sender_status = record.status
                sender_verified = record.status == "verified" and record.sending_enabled
            elif not restricted_key:
                sender_status = "not_found"

        receiving_configured = bool(receiving)
        receiving_domain_configured = False
        receiving_api_ok: bool | None = None
        receiving_message = ""
        if receiving:
            if not is_valid_email_address(receiving):
                receiving_message = "The receiving address is not a valid email address."
            elif is_public_mailbox_domain(receiving):
                receiving_message = (
                    "This looks like a personal mailbox. Resend can only receive mail at "
                    "your <id>.resend.app address or a domain with receiving enabled in Resend."
                )
            elif is_resend_managed_receiving_address(receiving):
                receiving_domain_configured = True
                receiving_message = "Using a Resend-managed receiving domain."
            else:
                domain = email_domain(receiving)
                record = by_name.get(domain or "")
                if record and record.receiving_enabled:
                    receiving_domain_configured = True
                    receiving_message = "The receiving domain has receiving enabled in Resend."
                elif restricted_key:
                    receiving_message = (
                        "A full-access API key is required to verify and read incoming mail."
                    )
                elif record:
                    receiving_message = (
                        "The domain exists in Resend but receiving is not enabled for it."
                    )
                else:
                    receiving_message = (
                        "The receiving domain was not found in this Resend account. "
                        "Add it in Resend and enable receiving, or use your <id>.resend.app address."
                    )

            if restricted_key:
                receiving_api_ok = False
                receiving_message = (
                    f"{receiving_message} A full-access API key is required for the receiving API."
                ).strip()
            else:
                try:
                    await self.list_received(limit=1)
                    receiving_api_ok = True
                    if receiving_domain_configured:
                        receiving_message = (
                            f"{receiving_message} The receiving API is reachable."
                        ).strip()
                except httpx.HTTPStatusError as exc:
                    receiving_api_ok = False
                    receiving_message = (
                        f"{receiving_message} {self._status_failure(exc).message}"
                    ).strip()
                except httpx.RequestError:
                    receiving_api_ok = False
                    receiving_message = (
                        f"{receiving_message} The receiving API could not be reached."
                    ).strip()

        if restricted_key:
            return ConnectionCheck(
                status=ConnectionStatus.CONNECTED,
                message=(
                    "The Resend API key is valid but restricted to sending. "
                    "Domain verification and incoming mail need a full-access key."
                ),
                sender_domain=sender_domain,
                sender_domain_status=sender_status,
                sender_verified=False,
                restricted_key=True,
                receiving_address_configured=receiving_configured,
                receiving_domain_configured=receiving_domain_configured,
                receiving_api_ok=receiving_api_ok,
                receiving_message=receiving_message,
                domains=domains,
            )

        if sender and not sender_verified:
            if sender_domain == "resend.dev":
                detail = (
                    "resend.dev is a testing sender and can only deliver to the Resend "
                    "account owner. Verify a domain you own for normal sending."
                )
            elif sender_status == "not_found":
                detail = (
                    f"The sender domain {sender_domain} is not in this Resend account. "
                    "Add and verify it in Resend first."
                )
            else:
                detail = (
                    f"The sender domain {sender_domain} is not verified for sending. "
                    "Complete DNS verification in Resend."
                )
            return ConnectionCheck(
                status=ConnectionStatus.SENDER_DOMAIN_UNVERIFIED,
                message=detail,
                sender_domain=sender_domain,
                sender_domain_status=sender_status,
                sender_verified=False,
                receiving_address_configured=receiving_configured,
                receiving_domain_configured=receiving_domain_configured,
                receiving_api_ok=receiving_api_ok,
                receiving_message=receiving_message,
                domains=domains,
            )

        message = "The Resend API key is valid."
        if sender:
            message += f" {sender_domain} is verified for sending."
        else:
            message += " Add a verified sender address before sending."
        if receiving and receiving_message:
            message += f" Incoming: {receiving_message}"
        return ConnectionCheck(
            status=ConnectionStatus.CONNECTED,
            message=message,
            sender_domain=sender_domain,
            sender_domain_status=sender_status,
            sender_verified=sender_verified,
            receiving_address_configured=receiving_configured,
            receiving_domain_configured=receiving_domain_configured,
            receiving_api_ok=receiving_api_ok,
            receiving_message=receiving_message,
            domains=domains,
        )

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _json(response: httpx.Response) -> dict[str, object]:
        try:
            body = response.json()
        except ValueError:
            return {}
        return cast(dict[str, object], body) if isinstance(body, dict) else {}

    @staticmethod
    def _domain_info(value: dict[str, object]) -> DomainInfo:
        capabilities = value.get("capabilities", {})
        capability_map = capabilities if isinstance(capabilities, dict) else {}
        return DomainInfo(
            name=str(value.get("name", "")),
            status=str(value.get("status", "unknown")),
            sending_enabled=str(capability_map.get("sending", "disabled")) == "enabled",
            receiving_enabled=str(capability_map.get("receiving", "disabled")) == "enabled",
        )

    @classmethod
    def _status_failure(cls, exc: httpx.HTTPStatusError) -> ConnectionCheck:
        code = exc.response.status_code
        detail = cls._provider_detail(exc.response)
        if code == 401:
            status = ConnectionStatus.INVALID_API_KEY
            message = "Resend rejected the API key. Check or replace the saved key."
        elif code == 403:
            status = ConnectionStatus.PERMISSION_DENIED
            message = (
                "The API key is valid but does not have permission for this operation. "
                "Use a full-access key to verify domains and receive mail."
            )
        elif code == 429:
            status = ConnectionStatus.RATE_LIMITED
            message = "Resend rate-limited the connection test. Wait a moment and try again."
        else:
            status = ConnectionStatus.PROVIDER_ERROR
            message = f"Resend returned an error (HTTP {code})."
        if detail:
            message = f"{message} {detail}"
        return ConnectionCheck(status=status, message=message)

    @staticmethod
    def _network_failure(exc: httpx.RequestError) -> ConnectionCheck:
        return ConnectionCheck(
            status=ConnectionStatus.NETWORK_UNAVAILABLE,
            message=(
                "The Resend API could not be reached. Check the internet connection and try again."
            ),
        )

    @staticmethod
    def _provider_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return ""
        if isinstance(body, dict):
            message = body.get("message")
            if message:
                return str(message)[:300]
        return ""

    @staticmethod
    def normalized_sender(sender: str) -> str:
        """Return just the address portion of a sender header."""

        return email_address(sender)
