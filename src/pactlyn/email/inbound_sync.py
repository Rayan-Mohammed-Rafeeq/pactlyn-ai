from __future__ import annotations

import re
from datetime import datetime
from email.utils import parseaddr
from typing import cast

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from pactlyn.core.contacts import ContactService
from pactlyn.email.addresses import email_address
from pactlyn.email.interfaces import EmailProvider
from pactlyn.storage.models import (
    Commitment,
    CommitmentEvent,
    CommitmentStatus,
    EmailMessage,
    EmailSyncCursor,
    EmailThread,
)

_MESSAGE_ID_RE = re.compile(r"<[^>]+>")


def _header_value(message: dict[str, object], *names: str) -> str | None:
    for name in names:
        value = message.get(name)
        if value not in (None, ""):
            return str(value)
    headers = message.get("headers")
    if isinstance(headers, dict):
        lowered = {str(key).lower(): value for key, value in headers.items()}
        for name in names:
            value = lowered.get(name.replace("_", "-").lower())
            if value not in (None, ""):
                return str(value)
    return None


def _message_ids(value: str | None) -> list[str]:
    if not value:
        return []
    identifiers = _MESSAGE_ID_RE.findall(value)
    return identifiers or [value.strip()]


class InboundEmailSync:
    def __init__(
        self,
        session: Session,
        provider: EmailProvider,
        account_id: str | None = None,
        receiving_address: str | None = None,
    ):
        self.session = session
        self.provider = provider
        self.account_id = account_id
        self.receiving_address = (receiving_address or "").strip()

    async def sync(self, cursor: str | None = None) -> tuple[int, str | None]:
        if cursor is None and self.account_id:
            cursor_row = self.session.scalar(
                select(EmailSyncCursor).where(EmailSyncCursor.account_id == self.account_id)
            )
            cursor = cursor_row.cursor if cursor_row else None
        records, next_cursor = await self.provider.list_received(cursor)
        count = 0
        for summary in records:
            provider_id = str(summary.get("id", ""))
            if not provider_id or self.session.scalar(
                select(EmailMessage).where(EmailMessage.provider_message_id == provider_id)
            ):
                continue
            message = await self.provider.get_received(provider_id)
            subject = str(message.get("subject", summary.get("subject", "")))
            message_id = _header_value(message, "message_id", "message-id")
            in_reply_to = _header_value(message, "in_reply_to", "in-reply-to")
            references = _header_value(message, "references")
            provider_thread_id = (
                str(message.get("thread_id", summary.get("thread_id", ""))) or None
            )
            reference_ids = [
                *_message_ids(in_reply_to),
                *_message_ids(references),
            ]
            thread = None
            if reference_ids:
                thread = self.session.scalar(
                    select(EmailThread)
                    .join(EmailMessage)
                    .where(
                        or_(
                            EmailMessage.message_id_header.in_(reference_ids),
                            EmailMessage.references_header.in_(reference_ids),
                        )
                    )
                    .limit(1)
                )
            if not thread and provider_thread_id:
                thread = self.session.scalar(
                    select(EmailThread).where(
                        EmailThread.provider_thread_id == provider_thread_id
                    )
                )

            to_value = message.get("to", [])
            recipients = (
                [str(item) for item in cast(list[object], to_value)]
                if isinstance(to_value, list)
                else [str(to_value)]
                if to_value
                else []
            )
            configured_receiving = email_address(self.receiving_address)
            if configured_receiving and recipients:
                delivered_to = {email_address(recipient) for recipient in recipients}
                if configured_receiving not in delivered_to:
                    continue

            sender = str(message.get("from", ""))
            sender_name, sender_email = parseaddr(sender)
            if sender_email:
                ContactService(self.session).upsert(sender_name or sender_email, sender_email)

            if thread is None:
                is_new_thread = True
                thread = EmailThread(
                    subject=subject,
                    provider_thread_id=provider_thread_id,
                    association_confidence=0.0,
                    needs_review=True,
                )
                self.session.add(thread)
                self.session.flush()
                self._suggest_association(thread, sender_email)
            else:
                is_new_thread = False
                thread.association_confidence = 1.0
                thread.needs_review = False

            self.session.add(
                EmailMessage(
                    thread_id=thread.id,
                    provider_message_id=provider_id,
                    message_id_header=message_id,
                    in_reply_to=in_reply_to,
                    references_header=references,
                    sender=sender,
                    recipients=recipients,
                    subject=subject,
                    body_text=str(message.get("text", "") or ""),
                    received_at=datetime.utcnow(),
                )
            )

            # Existing high-confidence threads (for example an outgoing reply)
            # move to RESPONSE_RECEIVED for review. A new, only suggested
            # association waits for the user to confirm it first.
            if thread.commitment_id and (not is_new_thread or not thread.needs_review):
                commitment = self.session.get(Commitment, thread.commitment_id)
                if commitment and commitment.status == CommitmentStatus.WAITING:
                    commitment.status = CommitmentStatus.RESPONSE_RECEIVED
                    self.session.add(
                        CommitmentEvent(
                            commitment_id=commitment.id,
                            event_type="incoming_reply",
                            detail=f"Reply received from {sender}",
                        )
                    )
            count += 1

        if self.account_id:
            cursor_row = self.session.scalar(
                select(EmailSyncCursor).where(EmailSyncCursor.account_id == self.account_id)
            )
            if cursor_row is None:
                cursor_row = EmailSyncCursor(account_id=self.account_id)
                self.session.add(cursor_row)
            if next_cursor is not None:
                cursor_row.cursor = next_cursor
            cursor_row.synced_at = datetime.utcnow()
        self.session.commit()
        return count, next_cursor

    def _suggest_association(self, thread: EmailThread, sender_email: str) -> None:
        if not sender_email:
            return
        candidates = list(
            self.session.scalars(
                select(Commitment).where(
                    func.lower(Commitment.contact_email) == sender_email.lower(),
                    Commitment.status.in_(
                        [
                            CommitmentStatus.WAITING,
                            CommitmentStatus.ACTIVE,
                            CommitmentStatus.DUE_SOON,
                            CommitmentStatus.OVERDUE,
                        ]
                    ),
                )
            )
        )
        if len(candidates) == 1:
            thread.commitment_id = candidates[0].id
            thread.association_confidence = 0.5
            thread.needs_review = True
