from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from pactlyn.app.configuration import Settings
from pactlyn.core.commitments import CommitmentService
from pactlyn.llm.gateway import LLMGateway
from pactlyn.llm.providers.ollama import OllamaProvider
from pactlyn.memory.service import MemoryService
from pactlyn.storage.database import create_session_factory, init_database, make_engine
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore


@dataclass
class AppContainer:
    settings: Settings
    session_factory: sessionmaker[Session]
    llm: LLMGateway
    vectors: LocalQdrantStore
    embedder: object

    def session(self) -> Session:
        return self.session_factory()

    def commitments(self, session: Session) -> CommitmentService:
        return CommitmentService(session)

    def memories(self, session: Session) -> MemoryService:
        return MemoryService(session, self.vectors, self.embedder)


def build_container(settings: Settings | None = None) -> AppContainer:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    init_database(engine)
    local = OllamaProvider(settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model)
    # Ollama is the production embedding provider. Tests inject the explicit
    # deterministic adapter instead, so no personal data leaves the machine.
    return AppContainer(settings=settings, session_factory=create_session_factory(engine), llm=LLMGateway(local), vectors=LocalQdrantStore(settings.qdrant_path), embedder=local)
