from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from pactlyn.storage.database import create_session_factory, init_database, make_engine


@pytest.fixture
def session(tmp_path) -> Session:
    engine = make_engine(f"sqlite:///{tmp_path / 'test.sqlite3'}")
    init_database(engine)
    factory = create_session_factory(engine)
    value = factory()
    try:
        yield value
    finally:
        value.close()
        engine.dispose()
