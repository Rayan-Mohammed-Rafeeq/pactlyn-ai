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
