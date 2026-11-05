from __future__ import annotations

import pytest

from pactlyn.email.interfaces import SendResult
from pactlyn.email.service import EmailService
from pactlyn.storage.models import EmailState


class FakeProvider:
    def __init__(self):
        self.requests = []

    async def send(self, request):
        self.requests.append(request)
        return SendResult(provider_id="provider-1", state="sent")

    async def status(self, provider_id):
        return "delivered"


@pytest.mark.asyncio
async def test_email_requires_approval_and_sends_once(session):
    provider = FakeProvider()
    service = EmailService(session, provider)
    action = service.draft(sender="me@example.com", recipients=["rahul@example.com"], subject="Update", body_text="Could you review this?")
    session.commit()
    assert action.state == EmailState.DRAFT
    assert await service.process_queue() == []
    service.approve(action.id)
    sent = await service.process_queue()
    assert len(sent) == 1
    assert len(provider.requests) == 1
    assert action.state == EmailState.SENT


@pytest.mark.parametrize("sender", ["person@gmail.com", "person@outlook.com"])
def test_personal_mailbox_cannot_be_used_as_sender(session, sender):
    service = EmailService(session)
    with pytest.raises(ValueError, match="cannot be used as the Resend sender"):
        service.draft(
            sender=sender,
            recipients=["rahul@example.com"],
            subject="Update",
            body_text="Body",
        )


def test_invalid_sender_cannot_be_drafted(session):
    service = EmailService(session)
    with pytest.raises(ValueError, match="not valid"):
        service.draft(
            sender="not-an-email",
            recipients=["rahul@example.com"],
            subject="Update",
            body_text="Body",
        )


def test_identical_drafts_have_distinct_action_idempotency_keys(session):
    service = EmailService(session)
    first = service.draft(sender="me@example.com", recipients=["rahul@example.com"], subject="Update", body_text="Same")
    second = service.draft(sender="me@example.com", recipients=["rahul@example.com"], subject="Update", body_text="Same")
    assert first.idempotency_key != second.idempotency_key


@pytest.mark.asyncio
async def test_payload_change_after_approval_is_rejected_and_never_sent(session):
    provider = FakeProvider()
    service = EmailService(session, provider)
    action = service.draft(
        sender="me@example.com",
        recipients=["rahul@example.com"],
        subject="Update",
        body_text="Original body",
    )
    session.commit()
    service.approve(action.id)
    action.body_text = "Tampered after approval"
    session.commit()

    assert await service.process_queue() == []
    assert action.state == EmailState.FAILED
    assert "Approval invalidated" in (action.last_error or "")
    assert provider.requests == []


@pytest.mark.asyncio
async def test_test_email_is_not_queued_or_sent_without_explicit_approval(session):
    provider = FakeProvider()
    service = EmailService(session, provider)
    action = service.draft(
        sender="me@example.com",
        recipients=["recipient@example.com"],
        subject="Pactlyn test email",
        body_text="Test body",
    )
    session.commit()

    assert action.state == EmailState.DRAFT
    assert await service.process_queue([action.id]) == []
    assert provider.requests == []
    assert action.state == EmailState.DRAFT

    service.approve(action.id)
    assert action.state == EmailState.QUEUED
    assert await service.process_queue([action.id]) != []
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_uncertain_provider_result_is_not_automatically_retried(session):
    class UncertainProvider(FakeProvider):
        async def send(self, request):
            self.requests.append(request)
            raise TimeoutError("network timeout after provider accepted the request")

    provider = UncertainProvider()
    service = EmailService(session, provider)
    action = service.draft(sender="me@example.com", recipients=["rahul@example.com"], subject="Update", body_text="Could you review this?")
    session.commit()
    service.approve(action.id)
    assert await service.process_queue() == []
    assert action.state == EmailState.UNKNOWN
    assert await service.process_queue() == []
    assert len(provider.requests) == 1
