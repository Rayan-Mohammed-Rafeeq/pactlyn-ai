from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from pactlyn.app.configuration import Settings
from pactlyn.core.commitments import CommitmentService
from pactlyn.email.resend.provider import ResendProvider
from pactlyn.email.service import EmailService
from pactlyn.llm.gateway import LLMGateway
from pactlyn.llm.providers.ollama import OllamaProvider
from pactlyn.llm.providers.openrouter import OpenRouterProvider
from pactlyn.memory.service import MemoryService
from pactlyn.security.credentials import CredentialStore
from pactlyn.storage.database import create_session_factory, init_database, make_engine
from pactlyn.storage.models import Contact, MemoryRecord
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore


@dataclass
class AppContainer:
    settings: Settings
    session_factory: sessionmaker[Session]
    llm: LLMGateway
    vectors: LocalQdrantStore
    embedder: object
    clock: Callable[[], datetime]
    email_provider: ResendProvider | None = None

    def session(self) -> Session:
        return self.session_factory()

    def commitments(self, session: Session) -> CommitmentService:
        return CommitmentService(session)

    def memories(self, session: Session) -> MemoryService:
        return MemoryService(session, self.vectors, self.embedder)

    def email(self, session: Session) -> EmailService:
        return EmailService(session, self.email_provider)

    def capture_context(self, session: Session, query: str, *, limit: int = 8) -> str:
        """Return small, explicitly labelled local context for the extraction prompt."""
        contacts = list(session.scalars(select(Contact).order_by(Contact.name).limit(limit)))
        memories = list(
            session.scalars(
                select(MemoryRecord)
                .where(MemoryRecord.deleted_at.is_(None), MemoryRecord.content.contains(query[:40]))
                .limit(limit)
            )
        )
        lines = [f"Known contact: {contact.name} <{contact.email or 'no email'}>" for contact in contacts]
        lines.extend(f"Memory ({memory.source_type}/{memory.source_id}): {memory.content}" for memory in memories)
        return "\n".join(lines)


def build_container(
    settings: Settings | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
) -> AppContainer:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    init_database(engine)
    local = OllamaProvider(settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model)
    # Ollama is the production embedding provider. Tests inject the explicit
    # deterministic adapter instead, so no personal data leaves the machine.
    credentials = CredentialStore()
    cloud = None
    openrouter_key = credentials.get("openrouter_api_key")
    if settings.openrouter_enabled and openrouter_key and settings.openrouter_model:
        cloud = OpenRouterProvider(openrouter_key, settings.openrouter_model)
    email_provider = None
    resend_key = credentials.get("resend_api_key")
    if resend_key and settings.resend_from:
        email_provider = ResendProvider(resend_key)
    return AppContainer(
        settings=settings,
        session_factory=create_session_factory(engine),
        llm=LLMGateway(local, cloud),
        vectors=LocalQdrantStore(settings.qdrant_path),
        embedder=local,
        clock=clock or (lambda: datetime.now(UTC)),
        email_provider=email_provider,
    )
