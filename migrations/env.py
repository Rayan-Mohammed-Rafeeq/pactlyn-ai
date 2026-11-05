from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from pactlyn.storage import models  # noqa: F401
from pactlyn.storage.database import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def _database_url() -> str:
    """Return the database URL, preferring the live data directory from Settings.

    This makes ``alembic upgrade head`` target the same database the running
    app uses (respecting ``PACTLYN_DATA_DIR`` / ``.env``) rather than the
    repo-root ``pactlyn.sqlite3`` hardcoded in ``alembic.ini``.
    """
    try:
        from pactlyn.app.configuration import Settings

        return Settings().database_url
    except Exception:
        # Fall back to alembic.ini value if Settings cannot be loaded.
        return config.get_main_option("sqlalchemy.url", default="sqlite:///pactlyn.sqlite3")


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
