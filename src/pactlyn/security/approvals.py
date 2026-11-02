from __future__ import annotations

import hashlib
import json


def payload_hash(*, sender: str, recipients: list[str], cc: list[str], bcc: list[str], reply_to: str | None, subject: str, body_text: str, body_html: str | None) -> str:
    canonical = json.dumps({"sender": sender, "recipients": recipients, "cc": cc, "bcc": bcc, "reply_to": reply_to, "subject": subject, "body_text": body_text, "body_html": body_html}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def approval_is_valid(expected: str | None, **payload: object) -> bool:
    if not expected:
        return False
    return expected == payload_hash(**payload)  # type: ignore[arg-type]
