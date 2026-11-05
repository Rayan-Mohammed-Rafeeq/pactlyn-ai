from __future__ import annotations

import keyring


class CredentialStoreError(RuntimeError):
    """Raised when the operating-system credential store is unavailable."""


class CredentialStore:
    """Small wrapper around the Linux OS keyring.

    Secrets are never written to SQLite, JSON settings or logs.  The wrapper
    deliberately raises a user-facing error when a secret cannot be stored so
    callers can explain the problem instead of silently falling back to
    plaintext storage.
    """

    service = "io.pactlyn.desktop"

    def set(self, name: str, value: str) -> None:
        if not value:
            raise ValueError("A credential value is required")
        try:
            keyring.set_password(self.service, name, value)
        except keyring.errors.KeyringError as exc:
            raise CredentialStoreError(
                "The operating system keyring is unavailable. Install or unlock a "
                "keyring such as GNOME Keyring or KWallet, then try again. Pactlyn "
                "will not save the API key in its database."
            ) from exc
        except Exception as exc:  # defensive: some backends raise platform errors
            raise CredentialStoreError(
                "The operating system keyring could not store the credential. "
                "Pactlyn will not save the API key in its database."
            ) from exc

    def get(self, name: str) -> str | None:
        try:
            return keyring.get_password(self.service, name)
        except Exception:
            # Reading is best-effort; callers can inspect is_available() and
            # explain that the keyring could not be opened.
            return None

    def delete(self, name: str) -> bool:
        try:
            keyring.delete_password(self.service, name)
            return True
        except keyring.errors.PasswordDeleteError:
            return False
        except keyring.errors.KeyringError as exc:
            raise CredentialStoreError(
                "The operating system keyring is unavailable, so the saved "
                "credential could not be removed."
            ) from exc
        except Exception as exc:
            raise CredentialStoreError(
                "The operating system keyring could not remove the credential."
            ) from exc

    def is_available(self) -> bool:
        try:
            backend = keyring.get_keyring()
            priority = getattr(backend, "priority", 0)
            return bool(priority and priority > 0)
        except Exception:
            return False

    def backend_name(self) -> str:
        try:
            return str(getattr(keyring.get_keyring(), "name", "unknown"))
        except Exception:
            return "unavailable"
