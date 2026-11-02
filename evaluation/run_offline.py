from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtWidgets import QApplication

from pactlyn.app.bootstrap import build_container
from pactlyn.app.configuration import Settings
from pactlyn.core.commitments import CommitmentCandidate, CommitmentService
from pactlyn.core.scheduler import ReminderScheduler
from pactlyn.email.service import EmailService
from pactlyn.llm.providers.ollama import OllamaProvider
from pactlyn.rag.embeddings import DeterministicTestEmbedding
from pactlyn.rag.retrieval import HybridRetriever
from pactlyn.storage.models import CommitmentType, EmailState


async def run() -> dict[str, object]:
    with TemporaryDirectory(prefix="pactlyn-offline-") as directory:
        settings = Settings(data_dir=Path(directory), ollama_url="http://127.0.0.1:11434")
        container = build_container(settings)
        session = container.session()
        try:
            app = QApplication.instance() or QApplication([])
            from pactlyn.ui.main_window import PactlynWindow

            window = PactlynWindow(container)
            desktop_ui = not window.tray.icon().isNull()
            ollama = OllamaProvider(settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model)
            ollama_available = await ollama.available()
            local_embeddings = False
            rag_available = False
            if ollama_available:
                await ollama.embed(["offline local embedding probe"])
                local_embeddings = True
                rag_available = bool(
                    await HybridRetriever(session, container.vectors, ollama).search(
                        "offline", limit=5
                    )
                )
            candidate = CommitmentCandidate(
                title="Offline proposal",
                description="Offline proposal",
                type=CommitmentType.PERSONAL_TASK,
                due_at=datetime.now(UTC) + timedelta(days=1),
                reminder_at=datetime.now(UTC) - timedelta(minutes=1),
                needs_confirmation=False,
            )
            commitment = CommitmentService(session).create(candidate, confirmed=True)
            session.commit()
            notifications: list[str] = []
            ReminderScheduler(session, lambda _title, body: notifications.append(body)).evaluate()
            email = EmailService(session)
            action = email.draft(
                sender="offline@example.com",
                recipients=["test@example.com"],
                subject="Offline draft",
                body_text="This remains local.",
                commitment_id=commitment.id,
            )
            session.commit()
            email.approve(action.id)
            session.refresh(action)
            qdrant_vector = (await DeterministicTestEmbedding().embed(["physical offline qdrant probe"]))[0]
            container.vectors.upsert(
                "personal_knowledge",
                str(uuid.uuid4()),
                qdrant_vector,
                {"source_id": "offline-probe", "content": "physical offline qdrant probe"},
            )
            qdrant_local_ok = bool(
                container.vectors.search("personal_knowledge", qdrant_vector, limit=1)
            )
            qdrant_path_exists = settings.qdrant_path.exists() and qdrant_local_ok
            window.shutdown()
            app.quit()
            return {
                "network_namespace": os.environ.get("PACTLYN_OFFLINE_NAMESPACE", "not-recorded"),
                "sqlite": True,
                "qdrant_local_path": qdrant_path_exists,
                "desktop_ui": desktop_ui,
                "ollama_available": ollama_available,
                "local_embeddings": local_embeddings,
                "rag": rag_available,
                "commitment_created": commitment.id is not None,
                "reminder_evaluated": bool(notifications),
                "email_draft_created": action.id is not None,
                "email_queued_without_provider": action.state == EmailState.QUEUED,
                "cloud_fallback": False,
                "note": "Run with `unshare -n` for physical network isolation. Ollama/RAG are unavailable unless local Ollama is already installed and reachable without networking.",
            }
        finally:
            session.close()
            container.vectors.close()


if __name__ == "__main__":
    report = asyncio.run(run())
    destination = Path(__file__).parent / "reports" / "offline.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
