from __future__ import annotations

import pytest

from pactlyn.storage.backup import BackupError, BackupService


def test_encrypted_backup_round_trip(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "pactlyn.sqlite3"
    # A real SQLite file is required for the backup API.
    import sqlite3

    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE marker(value TEXT)")
    connection.execute("INSERT INTO marker VALUES ('kept')")
    connection.commit()
    connection.close()
    service = BackupService(data_dir)
    backup = service.create(tmp_path / "pactlyn.pactlyn", password="correct")
    restored = tmp_path / "restored"
    BackupService(restored).restore(backup, password="correct")
    assert (restored / "pactlyn.sqlite3").exists()
    with pytest.raises(BackupError):
        BackupService(tmp_path / "bad").restore(backup, password="wrong")
