from __future__ import annotations

import base64
import io
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class BackupError(RuntimeError):
    pass


class BackupService:
    """Create and restore local data backups with optional password encryption."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.expanduser()
        self.database = self.data_dir / "pactlyn.sqlite3"
        self.qdrant = self.data_dir / "qdrant"

    def create(self, destination: Path, *, password: str | None = None) -> Path:
        if not self.database.exists():
            raise BackupError("Pactlyn database does not exist yet")
        destination = destination.expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as snapshot:
            source = sqlite3.connect(self.database)
            target = sqlite3.connect(snapshot.name)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot.name, "pactlyn.sqlite3")
                if self.qdrant.exists():
                    for path in self.qdrant.rglob("*"):
                        if path.is_file():
                            archive.write(path, str(Path("qdrant") / path.relative_to(self.qdrant)))
                archive.writestr("manifest.txt", "Pactlyn local backup v1\n")
            payload = raw.getvalue()
        if password:
            salt = os.urandom(16)
            encrypted = self._fernet(password, salt).encrypt(payload)
            destination.write_bytes(b"PACTLYN-BACKUP-1" + salt + encrypted)
        else:
            destination.write_bytes(payload)
        destination.chmod(0o600)
        return destination

    def restore(self, source: Path, *, password: str | None = None) -> None:
        payload = source.expanduser().read_bytes()
        if payload.startswith(b"PACTLYN-BACKUP-1"):
            if not password:
                raise BackupError("A backup password is required")
            salt = payload[16:32]
            try:
                payload = self._fernet(password, salt).decrypt(payload[32:])
            except InvalidToken as exc:
                raise BackupError("Incorrect backup password or corrupt backup") from exc
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = archive.namelist()
                if "pactlyn.sqlite3" not in names or "manifest.txt" not in names:
                    raise BackupError("Not a Pactlyn backup")
                for name in names:
                    target = (self.data_dir / name).resolve()
                    if not str(target).startswith(str(self.data_dir.resolve()) + os.sep):
                        raise BackupError("Backup contains an unsafe path")
                self.data_dir.mkdir(parents=True, exist_ok=True)
                for name in names:
                    if name.endswith("/"):
                        continue
                    target = self.data_dir / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(name))
        except zipfile.BadZipFile as exc:
            raise BackupError("Corrupt Pactlyn backup") from exc

    @staticmethod
    def _fernet(password: str, salt: bytes) -> Fernet:
        derivation = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=390_000,
        )
        key = derivation.derive(password.encode("utf-8"))
        return Fernet(base64.urlsafe_b64encode(key))
