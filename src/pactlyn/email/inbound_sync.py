from __future__ import annotations

from datetime import datetime
from email.utils import parseaddr
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from pactlyn.core.contacts import ContactService
from pactlyn.email.interfaces import EmailProvider
from pactlyn.storage.models import (
    Commitment,
    CommitmentEvent,
    CommitmentStatus,
    EmailMessage,
    EmailThread,
)


class InboundEmailSync:
    def __init__(self, session: Session, provider: EmailProvider):
        self.session = session
        self.provider = provider

    async def sync(self, cursor: str | None = None) -> tuple[int, str | None]:
        records, next_cursor = await self.provider.list_received(cursor)
        count = 0
        for summary in records:
            provider_id = str(summary.get("id", ""))
            if not provider_id or self.session.scalar(select(EmailMessage).where(EmailMessage.provider_message_id == provider_id)):
                continue
            message = await self.provider.get_received(provider_id)
            subject = str(message.get("subject", summary.get("subject", "")))
            in_reply_to = str(message.get("in_reply_to", "")) or None
            provider_thread_id = str(message.get("thread_id", summary.get("thread_id", ""))) or None
            thread = None
            if in_reply_to:
                thread = self.session.scalar(
                    select(EmailThread)
                    .join(EmailMessage)
                    .where(EmailMessage.message_id_header == in_reply_to)
                )
            if not thread and provider_thread_id:
                thread = self.session.scalar(
                    select(EmailThread).where(EmailThread.provider_thread_id == provider_thread_id)
                )
            if not thread:
                thread = EmailThread(
                    subject=subject,
                    provider_thread_id=provider_thread_id,
                    association_confidence=0.0,
                    needs_review=True,
                )
                self.session.add(thread)
                self.session.flush()
            else:
                thread.association_confidence = 1.0
                thread.needs_review = False
            to_value = message.get("to", [])
            recipients = cast(list[str], to_value) if isinstance(to_value, list) else [str(to_value)]
            sender = str(message.get("from", ""))
            sender_name, sender_email = parseaddr(sender)
            if sender_email:
                ContactService(self.session).upsert(sender_name or sender_email, sender_email)
            self.session.add(EmailMessage(thread_id=thread.id, provider_message_id=provider_id, message_id_header=message.get("message_id"), in_reply_to=in_reply_to, sender=str(message.get("from", "")), recipients=recipients, subject=subject, body_text=str(message.get("text", "")), received_at=datetime.utcnow()))
            if thread.commitment_id:
                commitment = self.session.get(Commitment, thread.commitment_id)
                if commitment and commitment.status == CommitmentStatus.WAITING:
                    commitment.status = CommitmentStatus.RESPONSE_RECEIVED
                    self.session.add(CommitmentEvent(commitment_id=commitment.id, event_type="incoming_reply", detail=f"Reply received from {message.get('from', '')}"))
            count += 1
        self.session.commit()
        return count, next_cursor
