from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from pactlyn.email.composer import EmailComposer
from pactlyn.email.interfaces import SendResult
from pactlyn.email.service import EmailService
from pactlyn.email.settings import EmailSettingsRepository, EmailTone, ReplyDestination
from pactlyn.storage.models import EmailMessage, EmailState, EmailThread


class FakeProvider:
    def __init__(self) -> None:
        self.requests = []

    async def send(self, request):
        self.requests.append(request)
        return SendResult(provider_id="provider-1", state="sent")

    async def status(self, provider_id: str) -> str:
        return "delivered"

    async def list_received(self, cursor=None):
        return [], cursor

    async def get_received(self, message_id: str):
        return {"id": message_id}


def _repository(session: Session) -> EmailSettingsRepository:
    repository = EmailSettingsRepository(session)
    repository.save(
        personal_name="Rayan",
        personal_email="rayan@example.com",
        sender_name="Pactlyn",
        sender_email="pactlyn@example.com",
        receiving_email="inbox@abc123.resend.app",
        reply_destination=ReplyDestination.PERSONAL,
        signature="Best regards,\nRayan",
        tone=EmailTone.PROFESSIONAL,
        inbound_enabled=True,
        sync_interval_minutes=15,
    )
    return repository


def test_new_draft_uses_configured_sender_reply_to_and_signature(session: Session) -> None:
    repository = _repository(session)
    composer = EmailComposer(session, repository)
    action = composer.create_draft(
        recipients=["rahul@example.com"],
        subject="Update",
        body_text="Could you review this?",
    )
    assert action.sender == "Pactlyn <pactlyn@example.com>"
    assert action.reply_to == "rayan@example.com"
    assert action.body_text.endswith("Best regards,\nRayan")
    assert action.headers["Message-ID"].startswith(f"<{action.id}@pactlyn.local>")


def test_reply_uses_actual_message_sender_and_thread_headers(session: Session) -> None:
    repository = _repository(session)
    thread = EmailThread(subject="Interview update")
    session.add(thread)
    session.flush()
    message = EmailMessage(
        thread_id=thread.id,
        message_id_header="<received@provider.test>",
        references_header="<first@provider.test>",
        sender="Rahul <rahul@example.com>",
        recipients=["inbox@abc123.resend.app"],
        subject="Interview update",
        body_text="Confirmed.",
    )
    session.add(message)
    session.commit()

    defaults = EmailComposer(session, repository).reply_defaults(message)
    assert defaults.recipients == ["rahul@example.com"]
    assert defaults.recipients != ["rayan@example.com"]
    assert defaults.reply_to == "rayan@example.com"
    assert defaults.headers["In-Reply-To"] == "<received@provider.test>"
    assert "<first@provider.test>" in defaults.headers["References"]
    assert "<received@provider.test>" in defaults.headers["References"]
    assert defaults.subject == "Re: Interview update"


def test_editing_or_changing_attachments_invalidates_approval(session: Session) -> None:
    repository = _repository(session)
    composer = EmailComposer(session, repository)
    action = composer.create_draft(
        recipients=["rahul@example.com"],
        subject="Update",
        body_text="Original",
        attachments=[
            {
                "filename": "note.txt",
                "content_type": "text/plain",
                "content_base64": "aGVsbG8=",
            }
        ],
    )
    session.commit()
    EmailService(session).approve(action.id)
    assert action.state == EmailState.QUEUED
    assert action.approval_hash

    EmailService(session).update_draft(
        action.id,
        sender=action.sender,
        recipients=action.recipients,
        cc=action.cc,
        bcc=action.bcc,
        reply_to=action.reply_to,
        subject=action.subject,
        body_text="Edited body",
        headers=action.headers,
        attachments=action.attachments,
    )
    session.commit()
    assert action.state == EmailState.DRAFT
    assert action.approval_hash is None


@pytest.mark.asyncio
async def test_test_email_send_only_processes_the_explicit_action(session: Session) -> None:
    repository = _repository(session)
    composer = EmailComposer(session, repository)
    provider = FakeProvider()
    service = EmailService(session, provider)
    first = composer.create_draft(
        recipients=["one@example.com"], subject="One", body_text="One"
    )
    second = composer.create_draft(
        recipients=["two@example.com"], subject="Two", body_text="Two"
    )
    session.commit()
    service.approve(first.id)
    service.approve(second.id)

    sent = await service.process_queue([first.id])
    assert [item.id for item in sent] == [first.id]
    assert len(provider.requests) == 1
    assert first.state == EmailState.SENT
    assert second.state == EmailState.QUEUED
