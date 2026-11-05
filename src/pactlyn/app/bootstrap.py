from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from pactlyn.app.configuration import Settings
from pactlyn.core.commitments import CommitmentService
from pactlyn.email.composer import EmailComposer
from pactlyn.email.resend.provider import ResendProvider
from pactlyn.email.service import EmailService
from pactlyn.email.settings import EmailPreferences, EmailSettingsRepository
from pactlyn.llm.gateway import LLMGateway
from pactlyn.llm.model_config import ModelConfigurationService, ModelRole
from pactlyn.llm.providers.ollama import OllamaProvider
from pactlyn.llm.providers.openrouter import OpenRouterProvider
from pactlyn.memory.service import MemoryService
from pactlyn.rag.embeddings import EmbeddingModelState, activate_embedding_model
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
    embedding_state: EmbeddingModelState | None = None
    email_provider: ResendProvider | None = None

    def session(self) -> Session:
        return self.session_factory()

    def commitments(self, session: Session) -> CommitmentService:
        return CommitmentService(session)

    def memories(self, session: Session) -> MemoryService:
        return MemoryService(session, self.vectors, self.embedder)

    def email(self, session: Session) -> EmailService:
        return EmailService(session, self.email_provider)

    def email_settings(self, session: Session) -> EmailSettingsRepository:
        return EmailSettingsRepository(session)

    def email_composer(self, session: Session) -> EmailComposer:
        return EmailComposer(session, self.email_settings(session), self.settings)

    def effective_email_settings(self) -> EmailPreferences:
        session = self.session()
        try:
            return self.email_settings(session).load(self.settings)
        finally:
            session.close()

    def refresh_email_provider(self) -> bool:
        session = self.session()
        try:
            repository = self.email_settings(session)
            key = repository.resolve_api_key(self.settings)
        finally:
            session.close()
        self.email_provider = ResendProvider(key) if key else None
        return self.email_provider is not None

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


def _load_active_models(session_factory: sessionmaker[Session], settings: Settings) -> tuple[str, str]:
    """Load active model selections from database or fall back to settings.
    
    Returns (assistant_model, embedding_model) tuple.
    """
    session = session_factory()
    try:
        model_config_service = ModelConfigurationService(session)
        active = model_config_service.get_all_active_models()
        
        # Use persisted selections or fall back to settings (environment variables)
        assistant_model = active.assistant_model or settings.ollama_model
        embedding_model = active.embedding_model or settings.ollama_embedding_model
        
        return assistant_model, embedding_model
    finally:
        session.close()


def build_container(
    settings: Settings | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
) -> AppContainer:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    init_database(engine)
    session_factory = create_session_factory(engine)
    
    # Load active model selections from database
    assistant_model, embedding_model = _load_active_models(session_factory, settings)
    
    # Create Ollama provider with selected models
    local = OllamaProvider(settings.ollama_url, assistant_model, embedding_model)
    
    # Ollama is the production embedding provider. Tests inject the explicit
    # deterministic adapter instead, so no personal data leaves the machine.
    credentials = CredentialStore()
    cloud = None
    # Keyring takes precedence; fall back to the .env / env-var value.
    openrouter_key = credentials.get("openrouter_api_key") or settings.openrouter_api_key
    if settings.openrouter_enabled and openrouter_key and settings.openrouter_model:
        cloud = OpenRouterProvider(openrouter_key, settings.openrouter_model)
    vectors = LocalQdrantStore(settings.qdrant_path)
    
    email_provider = None
    config_session = session_factory()
    try:
        # Settings → Email values in SQLite take precedence. The keyring is
        # checked first for the secret; environment values remain a
        # development/CI fallback only.
        email_settings_repository = EmailSettingsRepository(config_session, credentials)
        email_settings_repository.load(settings)
        resend_key = email_settings_repository.resolve_api_key(settings)
        if resend_key:
            email_provider = ResendProvider(resend_key)
    finally:
        config_session.close()
    
    metadata_session = session_factory()
    try:
        embedding_state = activate_embedding_model(
            metadata_session, vectors, embedding_model
        )
    finally:
        metadata_session.close()
    
    return AppContainer(
        settings=settings,
        session_factory=session_factory,
        llm=LLMGateway(local, cloud),
        vectors=vectors,
        embedder=local,
        clock=clock or (lambda: datetime.now(UTC)),
        embedding_state=embedding_state,
        email_provider=email_provider,
    )
