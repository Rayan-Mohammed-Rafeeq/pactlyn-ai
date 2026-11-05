from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from pactlyn.email.addresses import is_public_mailbox_domain, is_valid_email_address
from pactlyn.email.interfaces import EmailProvider, SendRequest
from pactlyn.security.approvals import approval_is_valid, payload_hash
from pactlyn.storage.models import (
    AuditEvent,
    EmailMessage,
    EmailSendAction,
    EmailState,
    EmailThread,
)


class EmailService:
    def __init__(self, session: Session, provider: EmailProvider | None = None):
        self.session = session
        self.provider = provider

    def draft(
        self,
        *,
        sender: str,
        recipients: list[str],
        subject: str,
        body_text: str,
        commitment_id: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        body_html: str | None = None,
        headers: dict[str, str] | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> EmailSendAction:
        self._validate_sender(sender)
        thread = EmailThread(subject=subject, commitment_id=commitment_id)
        self.session.add(thread)
        self.session.flush()
        action = EmailSendAction(
            sender=sender,
            recipients=recipients,
            cc=cc or [],
            bcc=bcc or [],
            reply_to=reply_to,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            headers=dict(headers or {}),
            attachments=list(attachments or []),
            commitment_id=commitment_id,
            thread_id=thread.id,
            idempotency_key="pending",
        )
        self.session.add(action)
        self.session.flush()
        action.idempotency_key = f"pactlyn-{action.id}"
        action.headers = {
            **action.headers,
            "Message-ID": action.headers.get("Message-ID", f"<{action.id}@pactlyn.local>"),
        }
        return action

    def approve(self, action_id: str) -> EmailSendAction:
        action = self._required(action_id)
        if action.state in {EmailState.SENT, EmailState.DELIVERED, EmailState.CANCELLED}:
            raise ValueError("This email cannot be approved in its current state")
        action.approval_hash = payload_hash(
            sender=action.sender,
            recipients=action.recipients,
            cc=action.cc,
            bcc=action.bcc,
            reply_to=action.reply_to,
            subject=action.subject,
            body_text=action.body_text,
            body_html=action.body_html,
            headers=action.headers,
            attachments=action.attachments,
        )
        action.state = EmailState.QUEUED
        self.session.add(
            AuditEvent(
                operation="email_approved",
                operation_id=action.id,
                detail={"payload_hash": action.approval_hash},
            )
        )
        self.session.commit()
        return action

    def list_actions(self, *, limit: int = 100) -> list[EmailSendAction]:
        return list(
            self.session.scalars(
                select(EmailSendAction)
                .order_by(EmailSendAction.updated_at.desc())
                .limit(limit)
            )
        )

    def update_draft(
        self,
        action_id: str,
        *,
        sender: str,
        recipients: list[str],
        cc: list[str],
        bcc: list[str],
        reply_to: str | None,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        commitment_id: str | None = None,
        headers: dict[str, str] | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> EmailSendAction:
        action = self._required(action_id)
        if action.state in {EmailState.SENT, EmailState.DELIVERED}:
            raise ValueError("Sent email payloads cannot be edited")
        self._validate_sender(sender)
        action.sender = sender
        action.recipients = recipients
        action.cc = cc
        action.bcc = bcc
        action.reply_to = reply_to
        action.subject = subject
        action.body_text = body_text
        action.body_html = body_html
        action.commitment_id = commitment_id
        if headers is not None:
            action.headers = dict(headers)
        if attachments is not None:
            action.attachments = list(attachments)
        if action.thread_id:
            thread = self.session.get(EmailThread, action.thread_id)
            if thread:
                thread.subject = subject
                thread.commitment_id = commitment_id
        action.approval_hash = None
        action.state = EmailState.DRAFT
        action.last_error = None
        self.session.add(
            AuditEvent(
                operation="email_edited",
                operation_id=action.id,
                detail={"approval_invalidated": True},
            )
        )
        return action

    def cancel(self, action_id: str) -> EmailSendAction:
        action = self._required(action_id)
        action.state = EmailState.CANCELLED
        self.session.commit()
        return action

    def retry(self, action_id: str) -> EmailSendAction:
        action = self._required(action_id)
        if action.state != EmailState.FAILED:
            raise ValueError("Only failed sends can be retried")
        action.state = EmailState.QUEUED
        action.last_error = None
        self.session.commit()
        return action

    async def process_queue(self, action_ids: list[str] | None = None) -> list[EmailSendAction]:
        if not self.provider:
            return []
        query = select(EmailSendAction).where(EmailSendAction.state == EmailState.QUEUED)
        if action_ids is not None:
            if not action_ids:
                return []
            query = query.where(EmailSendAction.id.in_(action_ids))
        actions = list(self.session.scalars(query))
        processed: list[EmailSendAction] = []
        for action in actions:
            if is_public_mailbox_domain(action.sender) or not is_valid_email_address(
                action.sender
            ):
                action.state = EmailState.FAILED
                action.last_error = (
                    "The sender address is not a usable Resend sender; personal "
                    "mailboxes are not allowed"
                )
                self.session.commit()
                continue
            if not approval_is_valid(
                action.approval_hash,
                sender=action.sender,
                recipients=action.recipients,
                cc=action.cc,
                bcc=action.bcc,
                reply_to=action.reply_to,
                subject=action.subject,
                body_text=action.body_text,
                body_html=action.body_html,
                headers=action.headers,
                attachments=action.attachments,
            ):
                action.state = EmailState.FAILED
                action.last_error = "Approval invalidated because the payload changed"
                self.session.commit()
                continue
            action.state = EmailState.SENDING
            action.attempts += 1
            try:
                result = await self.provider.send(
                    SendRequest(
                        sender=action.sender,
                        recipients=action.recipients,
                        cc=action.cc,
                        bcc=action.bcc,
                        reply_to=action.reply_to,
                        subject=action.subject,
                        body_text=action.body_text,
                        body_html=action.body_html,
                        idempotency_key=action.idempotency_key,
                        headers=action.headers,
                        attachments=action.attachments,
                    )
                )
                action.provider_id = result.provider_id
                action.state = EmailState.SENT
                action.last_error = None
                processed.append(action)
                self.session.add(
                    EmailMessage(
                        thread_id=action.thread_id or "",
                        provider_message_id=result.provider_id,
                        message_id_header=action.headers.get(
                            "Message-ID", f"<{action.id}@pactlyn.local>"
                        ),
                        in_reply_to=action.headers.get("In-Reply-To"),
                        references_header=action.headers.get("References"),
                        sender=action.sender,
                        recipients=action.recipients,
                        subject=action.subject,
                        body_text=action.body_text,
                        received_at=datetime.utcnow(),
                    )
                )
                self.session.add(
                    AuditEvent(
                        operation="email_sent",
                        operation_id=action.id,
                        detail={"provider_id": result.provider_id},
                    )
                )
            except Exception as exc:  # uncertain outcomes must not auto-retry
                action.state = EmailState.UNKNOWN
                action.last_error = str(exc)[:1000]
            self.session.commit()
        return processed

    async def reconcile(self) -> None:
        if not self.provider:
            return
        actions = list(
            self.session.scalars(
                select(EmailSendAction).where(
                    EmailSendAction.provider_id.is_not(None),
                    EmailSendAction.state.in_([EmailState.SENT, EmailState.UNKNOWN]),
                )
            )
        )
        for action in actions:
            try:
                state = await self.provider.status(action.provider_id or "")
                normalized = state.lower()
                if normalized in {"sent", "delivered", "delivery_delayed", "bounced", "complained"}:
                    action.state = EmailState.DELIVERED if normalized == "delivered" else EmailState.FAILED if normalized in {"bounced", "complained"} else EmailState.SENT
            except Exception:
                continue
        self.session.commit()

    @staticmethod
    def _validate_sender(sender: str) -> None:
        if is_public_mailbox_domain(sender):
            raise ValueError(
                "A personal Gmail, Outlook or similar address cannot be used as "
                "the Resend sender. Configure a verified domain sender in Settings → Email."
            )
        if not is_valid_email_address(sender):
            raise ValueError("The sender email address is not valid.")

    def _required(self, action_id: str) -> EmailSendAction:
        action = self.session.get(EmailSendAction, action_id)
        if not action:
            raise KeyError(f"Unknown email action: {action_id}")
        return action
