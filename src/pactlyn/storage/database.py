from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        future=True,
    )
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: object, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def init_database(engine: Engine) -> None:
    # Import models before create_all so all metadata is registered. Alembic
    # migrations can be layered on this stable metadata in a later release.
    from pactlyn.storage import models  # noqa: F401

    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS commitment_fts USING fts5("
            "commitment_id UNINDEXED, title, description, person, content)"
        ))
        connection.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS personal_fact_fts USING fts5("
            "fact_id UNINDEXED, attribute, value, display_value, source_text)"
        ))


def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
