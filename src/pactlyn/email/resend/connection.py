from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ConnectionStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CREDENTIALS_MISSING = "credentials_missing"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    INVALID_API_KEY = "invalid_api_key"
    SENDER_DOMAIN_UNVERIFIED = "sender_domain_unverified"
    NETWORK_UNAVAILABLE = "network_unavailable"
    RATE_LIMITED = "rate_limited"
    PROVIDER_ERROR = "provider_error"
    PERMISSION_DENIED = "permission_denied"
    INVALID_SENDER = "invalid_sender"

    @property
    def label(self) -> str:
        return {
            ConnectionStatus.NOT_CONFIGURED: "Not configured",
            ConnectionStatus.CREDENTIALS_MISSING: "Credentials missing",
            ConnectionStatus.CONNECTING: "Connecting…",
            ConnectionStatus.CONNECTED: "Connected",
            ConnectionStatus.INVALID_API_KEY: "Invalid API key",
            ConnectionStatus.SENDER_DOMAIN_UNVERIFIED: "Sender domain unverified",
            ConnectionStatus.NETWORK_UNAVAILABLE: "Network unavailable",
            ConnectionStatus.RATE_LIMITED: "Rate limited by Resend",
            ConnectionStatus.PROVIDER_ERROR: "Provider error",
            ConnectionStatus.PERMISSION_DENIED: "API key permission denied",
            ConnectionStatus.INVALID_SENDER: "Invalid sender address",
        }[self]


@dataclass(frozen=True)
class DomainInfo:
    name: str
    status: str
    sending_enabled: bool
    receiving_enabled: bool


@dataclass(frozen=True)
class ConnectionCheck:
    status: ConnectionStatus
    message: str
    sender_domain: str | None = None
    sender_domain_status: str | None = None
    sender_verified: bool = False
    restricted_key: bool = False
    receiving_address_configured: bool = False
    receiving_domain_configured: bool = False
    receiving_api_ok: bool | None = None
    receiving_message: str = ""
    domains: tuple[DomainInfo, ...] = field(default_factory=tuple)

    @property
    def connected(self) -> bool:
        return self.status in {
            ConnectionStatus.CONNECTED,
            ConnectionStatus.SENDER_DOMAIN_UNVERIFIED,
        }

    @property
    def domain_summary(self) -> str:
        if self.restricted_key:
            return (
                "Domain verification cannot be queried with a sending-only API key. "
                "Use a full-access key to verify the sender domain."
            )
        if not self.domains:
            return "No verified domains were returned by Resend."
        return "; ".join(
            f"{domain.name}: {domain.status}"
            f" (sending {'on' if domain.sending_enabled else 'off'}, "
            f"receiving {'on' if domain.receiving_enabled else 'off'})"
            for domain in self.domains
        )
