from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from pactlyn.app.configuration import Settings
from pactlyn.email.settings import (
    EmailPreferences,
    EmailSettingsRepository,
    EmailTone,
    ReplyDestination,
    validate_email_settings,
)
from pactlyn.security.credentials import CredentialStoreError
from pactlyn.storage.models import EmailAccount, UserPreference, UserProfile


class FakeCredentials:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def delete(self, name: str) -> bool:
        return self.values.pop(name, None) is not None

    def is_available(self) -> bool:
        return True

    def backend_name(self) -> str:
        return "fake-keyring"


def _save(repository: EmailSettingsRepository, *, sender: str = "pactlyn@example.com") -> EmailPreferences:
    return repository.save(
        personal_name="Rayan",
        personal_email="rayan@example.com",
        sender_name="Pactlyn",
        sender_email=sender,
        receiving_email="inbox@abc123.resend.app",
        reply_destination=ReplyDestination.PERSONAL,
        signature="Best regards,\nRayan",
        tone=EmailTone.FRIENDLY,
        inbound_enabled=True,
        sync_interval_minutes=15,
    )


def test_save_personal_identity_and_sender(session: Session) -> None:
    credentials = FakeCredentials()
    repository = EmailSettingsRepository(session, credentials)  # type: ignore[arg-type]
    preferences = _save(repository)

    assert preferences.personal_name == "Rayan"
    assert preferences.personal_email == "rayan@example.com"
    assert preferences.sender == "Pactlyn <pactlyn@example.com>"
    assert preferences.receiving_email == "inbox@abc123.resend.app"
    assert preferences.tone == EmailTone.FRIENDLY
    assert preferences.always_require_approval is True
    assert session.query(UserProfile).count() == 1
    assert session.query(EmailAccount).count() == 1
    assert session.query(UserPreference).count() >= 5


def test_api_key_is_only_stored_in_keyring_and_survives_new_session(
    session: Session,
) -> None:
    credentials = FakeCredentials()
    repository = EmailSettingsRepository(session, credentials)  # type: ignore[arg-type]
    _save(repository)
    repository.save_api_key("re_secret_value")
    assert credentials.values["resend_api_key"] == "re_secret_value"
    assert "re_secret_value" not in str(
        session.query(UserPreference).all()
    )

    restarted = Session(bind=session.get_bind())
    try:
        loaded = EmailSettingsRepository(restarted, credentials)  # type: ignore[arg-type]
        assert loaded.api_key() == "re_secret_value"
        assert loaded.api_key_configured() is True
        assert loaded.remove_api_key() is True
        assert loaded.api_key() is None
    finally:
        restarted.close()


def test_non_secret_settings_survive_a_new_session(session: Session) -> None:
    credentials = FakeCredentials()
    repository = EmailSettingsRepository(session, credentials)  # type: ignore[arg-type]
    _save(repository)

    restarted = Session(bind=session.get_bind())
    try:
        loaded = EmailSettingsRepository(restarted, credentials).load()  # type: ignore[arg-type]
        assert loaded.personal_name == "Rayan"
        assert loaded.sender == "Pactlyn <pactlyn@example.com>"
        assert loaded.receiving_email == "inbox@abc123.resend.app"
        assert loaded.reply_destination == ReplyDestination.PERSONAL
        assert loaded.tone == EmailTone.FRIENDLY
        assert loaded.inbound_enabled is True
        assert loaded.sync_interval_minutes == 15
        assert loaded.initialized is True
    finally:
        restarted.close()


def test_saved_settings_take_precedence_over_environment(session: Session) -> None:
    settings = Settings(
        _env_file=None,
        resend_from="Old Env <old@env.example>",
        resend_inbound_address="old-inbox@env.example",
    )
    credentials = FakeCredentials()
    repository = EmailSettingsRepository(session, credentials)  # type: ignore[arg-type]

    before_save = repository.load(settings)
    assert before_save.sender_email == "old@env.example"
    assert before_save.receiving_email == "old-inbox@env.example"

    _save(repository)
    after_save = repository.load(settings)
    assert after_save.sender_email == "pactlyn@example.com"
    assert after_save.receiving_email == "inbox@abc123.resend.app"


def test_environment_api_key_is_only_a_fallback(session: Session) -> None:
    credentials = FakeCredentials()
    repository = EmailSettingsRepository(session, credentials)  # type: ignore[arg-type]
    settings = Settings(_env_file=None, resend_api_key="re_environment")
    assert repository.resolve_api_key(settings) == "re_environment"
    repository.save_api_key("re_keyring")
    assert repository.resolve_api_key(settings) == "re_keyring"


def test_environment_api_key_stops_after_settings_are_saved(session: Session) -> None:
    credentials = FakeCredentials()
    repository = EmailSettingsRepository(session, credentials)  # type: ignore[arg-type]
    settings = Settings(_env_file=None, resend_api_key="re_environment")
    _save(repository)

    assert repository.resolve_api_key(settings) is None
    assert repository.api_key_source(settings) == "none"


def test_validation_reports_invalid_addresses_and_interval() -> None:
    preferences = EmailPreferences(
        personal_email="not-an-email",
        sender_email="sender@example.com",
        receiving_email="also-not-an-email",
        sync_interval_minutes=1,
    )
    errors = validate_email_settings(preferences, require_sender=True)
    assert any("personal email" in error for error in errors)
    assert any("receiving address" in error for error in errors)
    assert any("interval" in error for error in errors)


@pytest.mark.parametrize("sender", ["person@gmail.com", "person@outlook.com"])
def test_public_mailbox_sender_is_rejected(sender: str) -> None:
    preferences = EmailPreferences(
        personal_email="other@example.com", sender_email=sender
    )
    errors = validate_email_settings(preferences, require_sender=True)
    assert any("cannot be a Resend sender" in error for error in errors)


def test_personal_address_cannot_be_the_sender() -> None:
    preferences = EmailPreferences(
        personal_email="Rayan@example.com", sender_email="rayan@example.com"
    )
    errors = validate_email_settings(preferences, require_sender=True)
    assert any("dedicated sender identity" in error for error in errors)


@pytest.mark.parametrize("sender", ["person@gmail.com", "person@outlook.com"])
def test_composer_refuses_a_public_mailbox_sender(sender: str, session: Session) -> None:
    from pactlyn.email.composer import EmailComposer

    credentials = FakeCredentials()
    repository = EmailSettingsRepository(session, credentials)  # type: ignore[arg-type]
    _save(repository, sender=sender)
    with pytest.raises(ValueError, match="Personal Gmail or Outlook"):
        EmailComposer(session, repository).create_draft(
            recipients=["friend@example.com"], subject="Hi", body_text="Hello"
        )


def test_api_key_is_absent_from_the_whole_sqlite_database(session: Session) -> None:
    credentials = FakeCredentials()
    repository = EmailSettingsRepository(session, credentials)  # type: ignore[arg-type]
    _save(repository)
    repository.save_api_key("re_do_not_persist_me")

    dump = "\n".join(session.connection().connection.iterdump())
    assert "re_do_not_persist_me" not in dump


def test_connection_result_is_cleared_when_sender_or_receiving_address_changes(
    session: Session,
) -> None:
    credentials = FakeCredentials()
    repository = EmailSettingsRepository(session, credentials)  # type: ignore[arg-type]
    _save(repository)
    repository.record_connection_result("connected", "Verified")
    assert repository.load().last_test_status == "connected"

    _save(repository, sender="new-sender@example.com")
    assert repository.load().last_test_status is None
    assert repository.load().last_test_detail == ""


def test_connection_result_is_cleared_when_api_key_changes(session: Session) -> None:
    credentials = FakeCredentials()
    repository = EmailSettingsRepository(session, credentials)  # type: ignore[arg-type]
    _save(repository)
    repository.record_connection_result("connected", "Verified")
    repository.save_api_key("re_new")
    assert repository.load().last_test_status is None

    repository.record_connection_result("connected", "Verified")
    repository.remove_api_key()
    assert repository.load().last_test_status is None


class FailingCredentials(FakeCredentials):
    def set(self, name: str, value: str) -> None:
        raise CredentialStoreError("The operating system keyring is unavailable.")

    def delete(self, name: str) -> bool:
        raise CredentialStoreError("The operating system keyring is unavailable.")


def test_keyring_storage_errors_propagate_and_do_not_fall_back_to_sqlite(
    session: Session,
) -> None:
    credentials = FailingCredentials()
    repository = EmailSettingsRepository(session, credentials)  # type: ignore[arg-type]
    _save(repository)

    with pytest.raises(CredentialStoreError, match="keyring is unavailable"):
        repository.save_api_key("re_secret")
    with pytest.raises(CredentialStoreError, match="keyring is unavailable"):
        repository.remove_api_key()

    dump = "\n".join(session.connection().connection.iterdump())
    assert "re_secret" not in dump
