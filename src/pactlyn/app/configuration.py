from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Non-secret application settings.

    Secrets intentionally do not live in this object or in SQLite. Use
    :class:`pactlyn.security.credentials.CredentialStore` for provider keys.
    """

    model_config = SettingsConfigDict(env_prefix="PACTLYN_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=Path("~/.local/share/pactlyn"))
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_embedding_model: str = "nomic-embed-text"
    openrouter_model: str | None = None
    openrouter_enabled: bool = False
    resend_from: str | None = None
    resend_inbound_address: str | None = None
    default_timezone: str = "UTC"
    reminder_lead_hours: int = 24
    quiet_hours_start: int = 22
    quiet_hours_end: int = 8

    def expanded_data_dir(self) -> Path:
        path = self.data_dir.expanduser()
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
        return path

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.expanded_data_dir() / 'pactlyn.sqlite3').as_posix()}"

    @property
    def qdrant_path(self) -> Path:
        path = self.expanded_data_dir() / "qdrant"
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
        return path
