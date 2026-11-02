from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from pactlyn.email.inbound_sync import InboundEmailSync
from pactlyn.email.resend.provider import ResendProvider
from pactlyn.email.service import EmailService
from pactlyn.security.credentials import CredentialStore
from pactlyn.storage.database import create_session_factory, init_database, make_engine
from pactlyn.storage.models import EmailState

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("PACTLYN_LIVE_RESEND") != "1",
        reason="Set PACTLYN_LIVE_RESEND=1 to enable real Resend tests",
    ),
]


def _provider() -> ResendProvider:
    key = CredentialStore().get("resend_api_key") or os.environ.get("PACTLYN_LIVE_RESEND_API_KEY")
    sender = os.environ.get("PACTLYN_LIVE_RESEND_FROM")
    recipient = os.environ.get("PACTLYN_LIVE_RESEND_RECIPIENT")
    if not key or not sender or not recipient:
        pytest.skip("Live Resend key, verified sender and allowlisted recipient are required")
    if os.environ.get("PACTLYN_LIVE_RESEND_ALLOWLIST") != recipient:
        pytest.fail("The exact recipient must be repeated in PACTLYN_LIVE_RESEND_ALLOWLIST")
    return ResendProvider(key)


@pytest.mark.asyncio
async def test_live_resend_outbound_delivery_and_duplicate_protection(tmp_path):
    provider = _provider()
    sender = os.environ["PACTLYN_LIVE_RESEND_FROM"]
    recipient = os.environ["PACTLYN_LIVE_RESEND_RECIPIENT"]
    engine = make_engine(f"sqlite:///{tmp_path / 'live.sqlite3'}")
    init_database(engine)
    session = create_session_factory(engine)()
    service = EmailService(session, provider)
    action = service.draft(
        sender=sender,
        recipients=[recipient],
        subject=f"Pactlyn live validation {datetime.now(UTC).isoformat()}",
        body_text="Pactlyn Resend integration validation email.",
    )
    session.commit()
    service.approve(action.id)
    sent = await service.process_queue()
    assert len(sent) == 1
    assert action.provider_id
    assert action.state == EmailState.SENT
    # A second queue pass must not send the already-sent action again.
    assert await service.process_queue() == []
    await service.reconcile()
    assert action.state in {EmailState.SENT, EmailState.DELIVERED, EmailState.FAILED}
    session.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_live_resend_receiving_listing_and_thread_processing():
    provider = _provider()
    records, cursor = await provider.list_received()
    assert isinstance(records, list)
    assert cursor is None or isinstance(cursor, str)
    # The initial poll is safe even when the allowlisted receiving address has
    # no message. Any returned message is processed through the real parser.
    if records:
        from sqlalchemy import create_engine

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        init_database(engine)
        session = create_session_factory(engine)()
        count, _ = await InboundEmailSync(session, provider).sync()
        assert count >= 0
        session.close()
