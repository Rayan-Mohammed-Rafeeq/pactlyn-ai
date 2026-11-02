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


def test_identical_drafts_have_distinct_action_idempotency_keys(session):
    service = EmailService(session)
    first = service.draft(sender="me@example.com", recipients=["rahul@example.com"], subject="Update", body_text="Same")
    second = service.draft(sender="me@example.com", recipients=["rahul@example.com"], subject="Update", body_text="Same")
    assert first.idempotency_key != second.idempotency_key


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
