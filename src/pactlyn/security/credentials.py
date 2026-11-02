from __future__ import annotations

import keyring


class CredentialStore:
    service = "io.pactlyn.desktop"

    def set(self, name: str, value: str) -> None:
        keyring.set_password(self.service, name, value)

    def get(self, name: str) -> str | None:
        try:
            return keyring.get_password(self.service, name)
        except keyring.errors.KeyringError:
            return None

    def delete(self, name: str) -> None:
        try:
            keyring.delete_password(self.service, name)
        except keyring.errors.PasswordDeleteError:
            pass
