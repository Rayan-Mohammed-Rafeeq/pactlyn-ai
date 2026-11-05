import keyring
import pytest

from pactlyn.security.approvals import approval_is_valid, payload_hash
from pactlyn.security.credentials import CredentialStore, CredentialStoreError
from pactlyn.security.redaction import redact_sensitive


def test_email_approval_is_invalidated_by_payload_edit():
    payload = dict(sender="me@example.com", recipients=["them@example.com"], cc=[], bcc=[], reply_to=None, subject="Hello", body_text="Body", body_html=None)
    digest = payload_hash(**payload)
    assert approval_is_valid(digest, **payload)
    assert not approval_is_valid(digest, **{**payload, "subject": "Edited"})


def test_redaction_does_not_leak_secret():
    assert "super-secret" not in redact_sensitive("api_key=super-secret")


def test_keyring_store_failure_is_reported_without_plaintext_fallback(monkeypatch):
    def fail(*_args, **_kwargs):
        raise keyring.errors.KeyringError("locked")

    monkeypatch.setattr(keyring, "set_password", fail)
    with pytest.raises(CredentialStoreError, match="will not save"):
        CredentialStore().set("resend_api_key", "re_secret")


def test_keyring_read_failure_is_best_effort(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("keyring backend crashed")

    monkeypatch.setattr(keyring, "get_password", fail)
    assert CredentialStore().get("resend_api_key") is None


def test_keyring_delete_failure_is_reported(monkeypatch):
    def fail(*_args, **_kwargs):
        raise keyring.errors.KeyringError("locked")

    monkeypatch.setattr(keyring, "delete_password", fail)
    with pytest.raises(CredentialStoreError, match="could not be removed"):
        CredentialStore().delete("resend_api_key")


def test_missing_keyring_entry_is_not_an_error(monkeypatch):
    def fail(*_args, **_kwargs):
        raise keyring.errors.PasswordDeleteError("missing")

    monkeypatch.setattr(keyring, "delete_password", fail)
    assert CredentialStore().delete("resend_api_key") is False


def test_local_data_directory_is_private(tmp_path):
    from pactlyn.app.configuration import Settings

    data_dir = Settings(data_dir=tmp_path / "pactlyn").expanded_data_dir()
    assert data_dir.stat().st_mode & 0o777 == 0o700
    assert Settings(data_dir=data_dir).qdrant_path.stat().st_mode & 0o777 == 0o700
