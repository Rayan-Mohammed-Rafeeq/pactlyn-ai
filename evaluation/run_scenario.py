from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from pactlyn.app.bootstrap import build_container
from pactlyn.app.configuration import Settings
from pactlyn.core.commitments import CommitmentExtractor, CommitmentService
from pactlyn.email.service import EmailService
from pactlyn.memory.service import MemoryService
from pactlyn.rag.embeddings import DeterministicTestEmbedding
from pactlyn.rag.retrieval import HybridRetriever
from pactlyn.storage.models import EmailState, MemoryKind


async def run() -> dict[str, object]:
    with TemporaryDirectory(prefix="pactlyn-scenario-") as directory:
        container = build_container(Settings(data_dir=Path(directory)))
        now = datetime(2026, 11, 2, 10, tzinfo=UTC)
        text = "I'm waiting for Rahul to send me the project proposal by Friday."
        extracted = CommitmentExtractor().extract(text, now=now).candidates[0]
        session = container.session()
        try:
            commitment = CommitmentService(session).create(extracted, confirmed=True, source="scenario")
            deterministic_embedder = DeterministicTestEmbedding()
            memory = MemoryService(session, container.vectors, deterministic_embedder)
            await memory.remember(
                text,
                kind=MemoryKind.EPISODIC,
                source_type="commitment",
                source_id=commitment.id,
            )
            session.commit()
            retrieval = await HybridRetriever(session, container.vectors, deterministic_embedder).search(
                "Rahul project proposal", limit=5
            )
            email = EmailService(session)
            action = email.draft(
                sender="me@example.com",
                recipients=["rahul@example.com"],
                subject="Project proposal follow-up",
                body_text="Hi Rahul, could you share an update on the project proposal?",
                commitment_id=commitment.id,
            )
            session.commit()
            email.approve(action.id)
            session.close()
            restarted = container.session()
            try:
                saved = restarted.get(type(commitment), commitment.id)
                saved_action = restarted.get(type(action), action.id)
            finally:
                restarted.close()
            return {
                "input": text,
                "extracted_type": extracted.type.value,
                "extracted_person": extracted.person,
                "extracted_due_at_utc": extracted.due_at.isoformat() if extracted.due_at else None,
                "initial_confirmation_required": extracted.needs_confirmation,
                "saved_status": saved.status.value if saved else None,
                "memory_persisted": bool(memory.list()),
                "retrieval_hit": any(item.source_id == commitment.id for item in retrieval),
                "email_approval_bound": bool(action.approval_hash),
                "email_queued": saved_action.state == EmailState.QUEUED if saved_action else False,
                "restart_persisted": saved is not None and saved_action is not None,
                "reply_sync": "not_run_without_live_Resend",
                "outcome_confirmation": "not_run_without_live_Resend",
                "external_model": "not_run_without_live_Ollama",
                "external_email": "not_run_without_live_Resend",
            }
        finally:
            if session.is_active:
                session.close()
            container.vectors.close()


if __name__ == "__main__":
    report = asyncio.run(run())
    destination = Path(__file__).parent / "reports" / "scenario.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
