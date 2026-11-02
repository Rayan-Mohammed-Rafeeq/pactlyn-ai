from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
            thread = self.session.scalar(select(EmailThread).join(EmailMessage, isouter=True).where(EmailThread.subject == subject, EmailMessage.message_id_header == in_reply_to)) if in_reply_to else None
            if not thread:
                thread = self.session.scalar(select(EmailThread).where(func.lower(EmailThread.subject) == subject.lower()))
            if not thread:
                thread = EmailThread(subject=subject)
                self.session.add(thread)
                self.session.flush()
            to_value = message.get("to", [])
            recipients = cast(list[str], to_value) if isinstance(to_value, list) else [str(to_value)]
            self.session.add(EmailMessage(thread_id=thread.id, provider_message_id=provider_id, message_id_header=message.get("message_id"), in_reply_to=in_reply_to, sender=str(message.get("from", "")), recipients=recipients, subject=subject, body_text=str(message.get("text", "")), received_at=datetime.utcnow()))
            if thread.commitment_id:
                commitment = self.session.get(Commitment, thread.commitment_id)
                if commitment and commitment.status == CommitmentStatus.WAITING:
                    commitment.status = CommitmentStatus.COMPLETED
                    self.session.add(CommitmentEvent(commitment_id=commitment.id, event_type="incoming_reply", detail=f"Reply received from {message.get('from', '')}"))
            count += 1
        self.session.commit()
        return count, next_cursor
