from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from pactlyn.app.configuration import Settings
from pactlyn.email.addresses import (
    email_address,
    is_public_mailbox_domain,
    is_valid_email_address,
    split_address,
)
from pactlyn.email.service import EmailService
from pactlyn.email.settings import EmailPreferences, EmailSettingsRepository
from pactlyn.storage.models import EmailMessage, EmailSendAction


@dataclass(frozen=True)
class DraftDefaults:
    sender: str = ""
    recipients: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    reply_to: str | None = None
    subject: str = ""
    body_text: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    attachments: list[dict[str, str]] = field(default_factory=list)
    signature: str = ""
    tone: str = "professional"
    commitment_id: str | None = None


class EmailComposer:
    """Apply saved Settings → Email preferences to new drafts and replies."""

    def __init__(
        self,
        session: Session,
        repository: EmailSettingsRepository,
        settings: Settings | None = None,
    ):
        self.session = session
        self.repository = repository
        self.settings = settings

    def preferences(self) -> EmailPreferences:
        return self.repository.load(self.settings)

    def defaults(
        self,
        *,
        recipients: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        subject: str = "",
        body_text: str = "",
        commitment_id: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> DraftDefaults:
        preferences = self.preferences()
        return DraftDefaults(
            sender=preferences.sender,
            recipients=list(recipients or []),
            cc=list(cc or []),
            bcc=list(bcc or []),
            reply_to=preferences.reply_to_address(),
            subject=subject,
            body_text=body_text,
            headers=dict(headers or {}),
            signature=preferences.signature,
            tone=preferences.tone.value,
            commitment_id=commitment_id,
        )

    def create_draft(
        self,
        *,
        recipients: list[str],
        subject: str,
        body_text: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        commitment_id: str | None = None,
        headers: dict[str, str] | None = None,
        attachments: list[dict[str, str]] | None = None,
        append_signature: bool = True,
    ) -> EmailSendAction:
        preferences = self.preferences()
        if (
            not preferences.sender_email
            or not is_valid_email_address(preferences.sender_email)
            or is_public_mailbox_domain(preferences.sender_email)
        ):
            raise ValueError(
                "Configure a verified Resend sender in Settings → Email before drafting. "
                "Personal Gmail or Outlook addresses cannot be used as the sender."
            )
        body = preferences.with_signature(body_text) if append_signature else body_text
        return EmailService(self.session).draft(
            sender=preferences.sender,
            recipients=recipients,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to or preferences.reply_to_address(),
            subject=subject,
            body_text=body,
            commitment_id=commitment_id,
            headers=dict(headers or {}),
            attachments=list(attachments or []),
        )

    def reply_defaults(self, message: EmailMessage) -> DraftDefaults:
        preferences = self.preferences()
        _sender_name, sender_address = split_address(message.sender)
        address = sender_address or email_address(message.sender) or message.sender
        subject = message.subject if message.subject.lower().startswith("re:") else f"Re: {message.subject}"
        in_reply_to = message.message_id_header or ""
        references = " ".join(
            part
            for part in (
                (message.references_header or "").strip(),
                message.message_id_header or "",
            )
            if part
        )
        headers: dict[str, str] = {}
        if in_reply_to:
            headers["In-Reply-To"] = in_reply_to
        if references:
            headers["References"] = references
        commitment_id = message.thread.commitment_id if message.thread else None
        return DraftDefaults(
            sender=preferences.sender,
            recipients=[address] if address else [],
            reply_to=preferences.reply_to_address(),
            subject=subject,
            body_text="",
            headers=headers,
            signature=preferences.signature,
            tone=preferences.tone.value,
            commitment_id=commitment_id,
        )
