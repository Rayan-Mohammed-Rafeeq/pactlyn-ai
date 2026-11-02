from __future__ import annotations

import pytest

from pactlyn.core.commitments import CommitmentCandidate, CommitmentService
from pactlyn.email.inbound_sync import InboundEmailSync
from pactlyn.storage.models import CommitmentStatus, CommitmentType, EmailMessage, EmailThread


class FakeInboundProvider:
    async def list_received(self, cursor=None):
        return ([{"id": "received-1", "subject": "Interview update"}], None)

    async def get_received(self, message_id):
        return {"id": message_id, "subject": "Interview update", "from": "coordinator@example.com", "to": ["me@example.com"], "in_reply_to": "<outbound@pactlyn.local>", "message_id": "<received@provider.test>", "text": "The interview is confirmed."}


@pytest.mark.asyncio
async def test_inbound_reply_resolves_waiting_commitment(session):
    candidate = CommitmentCandidate(title="Waiting for interview details", description="Waiting for interview details", type=CommitmentType.WAITING_FOR, person="coordinator", needs_confirmation=False)
    commitment = CommitmentService(session).create(candidate, confirmed=True)
    thread = EmailThread(subject="Interview update", commitment_id=commitment.id)
    session.add(thread)
    session.flush()
    session.add(EmailMessage(thread_id=thread.id, message_id_header="<outbound@pactlyn.local>", sender="me@example.com", recipients=["coordinator@example.com"], subject=thread.subject, body_text="Any update?"))
    session.commit()
    count, _ = await InboundEmailSync(session, FakeInboundProvider()).sync()
    session.refresh(commitment)
    assert count == 1
    assert commitment.status == CommitmentStatus.COMPLETED
