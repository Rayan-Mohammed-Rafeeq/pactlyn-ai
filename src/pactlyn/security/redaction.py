from __future__ import annotations

import re


def redact_sensitive(text: str, *, redact_emails: bool = False) -> str:
    value = re.sub(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
    if redact_emails:
        value = re.sub(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", "[EMAIL REDACTED]", value)
    return value
