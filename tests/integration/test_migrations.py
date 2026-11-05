from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from pactlyn.storage.database import init_database


def _config(database: Path) -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config()
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("prepend_sys_path", str(root / "src"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    return config


def test_email_settings_migration_preserves_existing_rows(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("PACTLYN_DATA_DIR", str(tmp_path))
    database = tmp_path / "pactlyn.sqlite3"
    config = _config(database)
    command.upgrade(config, "8c0_relationship_review_audit")

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO email_accounts (id, provider, inbound_address, sender_address, enabled) "
            "VALUES ('account-1', 'resend', 'old@abc.resend.app', 'old@example.com', 1)"
        )
        connection.execute(
            "INSERT INTO email_messages "
            "(id, thread_id, provider_message_id, message_id_header, in_reply_to, sender, "
            " recipients, subject, body_text, received_at) "
            "VALUES ('message-1', 'thread-1', 'provider-1', '<old@example.com>', NULL, "
            " 'sender@example.com', '[\"old@abc.resend.app\"]', 'Old', 'Body', CURRENT_TIMESTAMP)"
        )
        connection.commit()
    finally:
        connection.close()

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database}")
    try:
        schema = inspect(engine)
        account_columns = {column["name"] for column in schema.get_columns("email_accounts")}
        message_columns = {column["name"] for column in schema.get_columns("email_messages")}
        action_columns = {column["name"] for column in schema.get_columns("email_send_actions")}
        assert {
            "sender_name",
            "sync_interval_minutes",
            "last_test_status",
            "last_test_detail",
            "last_tested_at",
        } <= account_columns
        assert "references_header" in message_columns
        assert {"headers", "attachments"} <= action_columns
        # Verify the personal_facts table was created by the new migration.
        assert "personal_facts" in schema.get_table_names()
    finally:
        engine.dispose()

    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT sender_address, sender_name, sync_interval_minutes, inbound_address "
            "FROM email_accounts WHERE id = 'account-1'"
        ).fetchone()
        assert row == ("old@example.com", "", 15, "old@abc.resend.app")
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version == ("a0_personal_facts",)
    finally:
        connection.close()


def test_init_database_contains_email_settings_columns(tmp_path: Path) -> None:
    database = tmp_path / "schema.sqlite3"
    engine = create_engine(f"sqlite:///{database}")
    init_database(engine)
    try:
        schema = inspect(engine)
        assert "sender_name" in {
            column["name"] for column in schema.get_columns("email_accounts")
        }
        assert "references_header" in {
            column["name"] for column in schema.get_columns("email_messages")
        }
    finally:
        engine.dispose()
