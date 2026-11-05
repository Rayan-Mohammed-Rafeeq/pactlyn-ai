from __future__ import annotations

import re
from email.utils import formataddr, parseaddr

_ADDRESS_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PUBLIC_MAILBOX_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "yahoo.com",
        "ymail.com",
        "icloud.com",
        "me.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "mail.com",
    }
)


def split_address(value: str | None) -> tuple[str, str]:
    """Return ``(display_name, address)`` for a header or bare address."""

    if not value:
        return "", ""
    name, address = parseaddr(value)
    return name.strip(), address.strip()


def is_valid_email_address(value: str | None) -> bool:
    if not value:
        return False
    _name, address = split_address(value)
    return bool(address and _ADDRESS_RE.match(address))


def email_address(value: str | None) -> str:
    return split_address(value)[1].lower()


def email_domain(value: str | None) -> str | None:
    address = email_address(value)
    if "@" not in address:
        return None
    return address.rsplit("@", 1)[1].lower() or None


def is_public_mailbox_domain(value: str | None) -> bool:
    domain = email_domain(value)
    return bool(domain and domain in PUBLIC_MAILBOX_DOMAINS)


def is_resend_managed_receiving_address(value: str | None) -> bool:
    domain = email_domain(value)
    return bool(domain and domain.endswith(".resend.app"))


def sender_header(display_name: str, address: str) -> str:
    """Format a sender header without ever using a personal address implicitly."""

    address = email_address(address)
    name, embedded = split_address(display_name)
    if not address:
        address = embedded
    if not address:
        return ""
    return formataddr((name or display_name.strip(), address))
