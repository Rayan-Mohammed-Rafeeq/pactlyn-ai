from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pactlyn.core.commitments import CommitmentCandidate, CommitmentService
from pactlyn.email.inbound_sync import InboundEmailSync
from pactlyn.storage.models import (
    CommitmentStatus,
    CommitmentType,
    Contact,
    EmailAccount,
    EmailMessage,
    EmailSyncCursor,
    EmailThread,
)


class MetadataProvider:
    def __init__(self, message: dict[str, object], cursor: str | None = "next-page") -> None:
        self.message = message
        self.cursor = cursor

    async def list_received(self, cursor=None):
        return ([{"id": str(self.message["id"]), "subject": self.message.get("subject", "")}], self.cursor)

    async def get_received(self, message_id):
        return self.message


@pytest.mark.asyncio
async def test_thread_headers_are_preserved_and_contact_is_associated(session: Session) -> None:
    provider = MetadataProvider(
        {
            "id": "received-1",
            "subject": "Re: Project",
            "from": "Rahul <rahul@example.com>",
            "to": ["inbox@abc123.resend.app"],
            "headers": {
                "In-Reply-To": "<outbound@pactlyn.local>",
                "References": "<first@provider.test> <outbound@pactlyn.local>",
            },
            "message_id": "<received@provider.test>",
            "text": "Thanks.",
        }
    )
    count, cursor = await InboundEmailSync(session, provider).sync()
    assert count == 1
    assert cursor == "next-page"
    stored = session.scalar(select(EmailMessage))
    assert stored is not None
    assert stored.message_id_header == "<received@provider.test>"
    assert stored.in_reply_to == "<outbound@pactlyn.local>"
    assert stored.references_header == "<first@provider.test> <outbound@pactlyn.local>"
    assert session.scalar(select(Contact).where(Contact.email == "rahul@example.com"))


@pytest.mark.asyncio
async def test_sync_updates_cursor_timestamp(session: Session) -> None:
    account = EmailAccount(provider="resend", sender_address="sender@example.com")
    session.add(account)
    session.commit()
    provider = MetadataProvider(
        {
            "id": "received-2",
            "subject": "Hello",
            "from": "Rahul <rahul@example.com>",
            "to": ["inbox@abc123.resend.app"],
            "message_id": "<received2@provider.test>",
            "text": "Hello",
        }
    )
    await InboundEmailSync(session, provider, account_id=account.id).sync()
    cursor = session.scalar(
        select(EmailSyncCursor).where(EmailSyncCursor.account_id == account.id)
    )
    assert cursor is not None
    assert cursor.cursor == "next-page"
    assert cursor.synced_at is not None


@pytest.mark.asyncio
async def test_reply_to_known_thread_marks_response_received_without_completing(
    session: Session,
) -> None:
    commitment = CommitmentService(session).create(
        CommitmentCandidate(
            title="Waiting for interview details",
            description="Waiting for interview details",
            type=CommitmentType.WAITING_FOR,
            person="Rahul",
            contact_email="rahul@example.com",
            needs_confirmation=False,
        ),
        confirmed=True,
    )
    thread = EmailThread(
        subject="Interview update",
        commitment_id=commitment.id,
        association_confidence=1.0,
        needs_review=False,
    )
    session.add(thread)
    session.flush()
    session.add(
        EmailMessage(
            thread_id=thread.id,
            message_id_header="<outbound@pactlyn.local>",
            sender="Pactlyn <pactlyn@example.com>",
            recipients=["rahul@example.com"],
            subject=thread.subject,
            body_text="Any update?",
        )
    )
    session.commit()

    provider = MetadataProvider(
        {
            "id": "received-4",
            "subject": "Re: Interview update",
            "from": "Rahul <rahul@example.com>",
            "to": ["inbox@abc123.resend.app"],
            "headers": {"In-Reply-To": "<outbound@pactlyn.local>"},
            "message_id": "<received4@provider.test>",
            "text": "Confirmed for Monday.",
        },
        cursor=None,
    )
    await InboundEmailSync(session, provider).sync()

    session.refresh(commitment)
    session.refresh(thread)
    assert commitment.status == CommitmentStatus.RESPONSE_RECEIVED
    assert commitment.status != CommitmentStatus.COMPLETED
    assert thread.needs_review is False
    assert thread.association_confidence == 1.0


class MultiMessageProvider:
    def __init__(self, messages: list[dict[str, object]], cursor: str | None = None) -> None:
        self.messages = messages
        self.cursor = cursor
        self.cursors: list[str | None] = []

    async def list_received(self, cursor=None):
        self.cursors.append(cursor)
        summaries = [
            {"id": str(message["id"]), "subject": message.get("subject", "")}
            for message in self.messages
        ]
        return summaries, self.cursor

    async def get_received(self, message_id):
        return next(
            message for message in self.messages if str(message["id"]) == message_id
        )


@pytest.mark.asyncio
async def test_sync_ignores_messages_for_other_receiving_addresses(
    session: Session,
) -> None:
    provider = MultiMessageProvider(
        [
            {
                "id": "received-6",
                "subject": "For Pactlyn",
                "from": "Rahul <rahul@example.com>",
                "to": ["inbox@abc123.resend.app"],
                "message_id": "<received6@provider.test>",
                "text": "Hello",
            },
            {
                "id": "received-7",
                "subject": "For someone else",
                "from": "Other <other@example.com>",
                "to": ["different@abc123.resend.app"],
                "message_id": "<received7@provider.test>",
                "text": "Hello",
            },
        ]
    )

    count, _ = await InboundEmailSync(
        session, provider, receiving_address="inbox@abc123.resend.app"
    ).sync()

    assert count == 1
    stored = list(session.scalars(select(EmailMessage)))
    assert [message.provider_message_id for message in stored] == ["received-6"]


@pytest.mark.asyncio
async def test_sync_reuses_the_stored_cursor(session: Session) -> None:
    account = EmailAccount(provider="resend", sender_address="sender@example.com")
    session.add(account)
    session.commit()
    provider = MultiMessageProvider([], cursor="next-page")

    await InboundEmailSync(session, provider, account_id=account.id).sync()
    await InboundEmailSync(session, provider, account_id=account.id).sync()

    assert provider.cursors == [None, "next-page"]
    cursor = session.scalar(
        select(EmailSyncCursor).where(EmailSyncCursor.account_id == account.id)
    )
    assert cursor is not None
    assert cursor.cursor == "next-page"


@pytest.mark.asyncio
async def test_repeated_provider_message_is_ignored(session: Session) -> None:
    message = {
        "id": "received-5",
        "subject": "Hello",
        "from": "Rahul <rahul@example.com>",
        "to": ["inbox@abc123.resend.app"],
        "message_id": "<received5@provider.test>",
        "text": "Hello",
    }
    provider = MetadataProvider(message, cursor=None)

    assert await InboundEmailSync(session, provider).sync() == (1, None)
    assert await InboundEmailSync(session, provider).sync() == (0, None)
    assert len(list(session.scalars(select(EmailMessage)))) == 1


@pytest.mark.asyncio
async def test_new_thread_only_suggests_commitment_and_requires_review(session: Session) -> None:
    commitment = CommitmentService(session).create(
        CommitmentCandidate(
            title="Waiting for project update",
            description="Waiting for project update",
            type=CommitmentType.WAITING_FOR,
            person="Rahul",
            contact_email="rahul@example.com",
            needs_confirmation=False,
        ),
        confirmed=True,
    )
    session.commit()
    provider = MetadataProvider(
        {
            "id": "received-3",
            "subject": "Project update",
            "from": "Rahul <rahul@example.com>",
            "to": ["inbox@abc123.resend.app"],
            "message_id": "<received3@provider.test>",
            "text": "Here is the update.",
        },
        cursor=None,
    )
    await InboundEmailSync(session, provider).sync()
    thread = session.scalar(select(EmailThread))
    assert thread is not None
    assert thread.commitment_id == commitment.id
    assert thread.needs_review is True
    assert thread.association_confidence < 1.0
    session.refresh(commitment)
    assert commitment.status == CommitmentStatus.WAITING
