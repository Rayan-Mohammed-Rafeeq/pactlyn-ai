from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session
from pactlyn.app.configuration import Settings
from pactlyn.email.addresses import (
    is_public_mailbox_domain,
    is_valid_email_address,
    sender_header,
    split_address,
)
from pactlyn.security.credentials import CredentialStore
from pactlyn.storage.models import (
    EmailAccount,
    EmailSyncCursor,
    UserPreference,
    UserProfile,
)

RESEND_API_KEY_NAME = "resend_api_key"
EMAIL_PREFERENCE_PREFIX = "email."


class ReplyDestination(StrEnum):
    PERSONAL = "personal"
    RECEIVING = "receiving"


class EmailTone(StrEnum):
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"
    CONCISE = "concise"
    FORMAL = "formal"


@dataclass(frozen=True)
class EmailPreferences:
    personal_name: str = ""
    personal_email: str = ""
    sender_name: str = ""
    sender_email: str = ""
    receiving_email: str = ""
    reply_destination: ReplyDestination = ReplyDestination.PERSONAL
    signature: str = ""
    tone: EmailTone = EmailTone.PROFESSIONAL
    inbound_enabled: bool = False
    sync_interval_minutes: int = 15
    always_require_approval: bool = True
    initialized: bool = False
    last_test_status: str | None = None
    last_test_detail: str = ""
    last_tested_at: datetime | None = None

    @property
    def sender(self) -> str:
        return sender_header(self.sender_name, self.sender_email)

    def reply_to_address(self) -> str | None:
        if self.reply_destination == ReplyDestination.RECEIVING:
            return self.receiving_email.strip() or self.personal_email.strip() or None
        return self.personal_email.strip() or self.receiving_email.strip() or None

    def with_signature(self, body: str) -> str:
        signature = self.signature.strip()
        if not signature:
            return body
        if body.rstrip().endswith(signature):
            return body
        return f"{body.rstrip()}\n\n{signature}".strip()

    def resolved(self, settings: Settings | None = None) -> EmailPreferences:
        """Apply development environment fallbacks only before first save.

        Once a user saves Settings → Email, the SQLite values take precedence
        even when a stale environment variable is still present.
        """

        if settings is None or self.initialized:
            return self
        env_name, env_address = split_address(settings.resend_from)
        return replace(
            self,
            sender_name=self.sender_name or env_name,
            sender_email=self.sender_email or env_address,
            receiving_email=self.receiving_email
            or (settings.resend_inbound_address or "").strip(),
        )


class EmailSettingsRepository:
    """Persist non-secret email configuration in SQLite.

    The API key intentionally never passes through this class's database
    methods; it is delegated to :class:`CredentialStore` (Linux keyring).
    """

    def __init__(self, session: Session, credentials: CredentialStore | None = None):
        self.session = session
        self.credentials = credentials or CredentialStore()

    # ------------------------------------------------------------------ reads
    def load(self, settings: Settings | None = None) -> EmailPreferences:
        profile = self._profile(create=False)
        account = self._account(create=False)
        values = self._preference_values(profile.id) if profile else {}
        preferences = EmailPreferences(
            personal_name=profile.display_name if profile else "",
            personal_email=str(values.get("personal_email", "")),
            sender_name=account.sender_name if account else "",
            sender_email=account.sender_address if account else "",
            receiving_email=(account.inbound_address or "") if account else "",
            reply_destination=self._reply_destination(values.get("reply_destination")),
            signature=str(values.get("signature", "")),
            tone=self._tone(values.get("tone")),
            inbound_enabled=bool(account.enabled) if account else False,
            sync_interval_minutes=int(account.sync_interval_minutes) if account else 15,
            always_require_approval=True,
            initialized=bool(values.get("initialized", False)),
            last_test_status=account.last_test_status if account else None,
            last_test_detail=account.last_test_detail if account else "",
            last_tested_at=account.last_tested_at if account else None,
        )
        return preferences.resolved(settings)

    def last_synced_at(self) -> datetime | None:
        account = self._account(create=False)
        if not account:
            return None
        cursor = self.session.scalar(
            select(EmailSyncCursor).where(EmailSyncCursor.account_id == account.id)
        )
        return cursor.synced_at if cursor else None

    def account_id(self) -> str | None:
        account = self._account(create=False)
        return account.id if account else None

    def api_key(self) -> str | None:
        return self.credentials.get(RESEND_API_KEY_NAME)

    def resolve_api_key(self, settings: Settings | None = None) -> str | None:
        """Keyring first, then the optional development environment value.

        The environment fallback stops once the user has saved Settings → Email
        so that removing a keyring key cannot silently reactivate a stale `.env`
        value.
        """

        key = self.api_key()
        if key:
            return key
        if settings is None or self._initialized():
            return None
        return (settings.resend_api_key or "").strip() or None

    def api_key_configured(self) -> bool:
        return bool(self.api_key())

    def api_key_source(self, settings: Settings | None = None) -> str:
        if self.api_key():
            return "keyring"
        if (
            settings is not None
            and not self._initialized()
            and (settings.resend_api_key or "").strip()
        ):
            return "environment"
        return "none"

    # ----------------------------------------------------------------- writes
    def save(
        self,
        *,
        personal_name: str,
        personal_email: str,
        sender_name: str,
        sender_email: str,
        receiving_email: str,
        reply_destination: ReplyDestination | str,
        signature: str,
        tone: EmailTone | str,
        inbound_enabled: bool,
        sync_interval_minutes: int,
    ) -> EmailPreferences:
        profile = self._profile(create=True)
        account = self._account(create=True)
        assert profile is not None and account is not None

        previous_sender = (account.sender_address or "").strip().lower()
        previous_receiving = (account.inbound_address or "").strip().lower()
        profile.display_name = personal_name.strip()
        account.sender_name = sender_name.strip()
        account.sender_address = sender_email.strip()
        account.inbound_address = receiving_email.strip() or None
        account.enabled = bool(inbound_enabled)
        account.sync_interval_minutes = max(5, min(1440, int(sync_interval_minutes)))
        if (
            previous_sender != account.sender_address.lower()
            or previous_receiving != (account.inbound_address or "").lower()
        ):
            # A result recorded for the old sender/receiving address must not
            # look current after the user changes either endpoint.
            account.last_test_status = None
            account.last_test_detail = ""
            account.last_tested_at = None
        self._set_preference(profile.id, "personal_email", personal_email.strip())
        self._set_preference(
            profile.id, "reply_destination", self._reply_destination(reply_destination).value
        )
        self._set_preference(profile.id, "signature", signature)
        self._set_preference(profile.id, "tone", self._tone(tone).value)
        self._set_preference(profile.id, "always_require_approval", True)
        self._set_preference(profile.id, "initialized", True)
        self.session.commit()
        return self.load()

    def save_api_key(self, api_key: str) -> None:
        value = api_key.strip()
        if not value:
            raise ValueError("Enter a Resend API key first")
        self.credentials.set(RESEND_API_KEY_NAME, value)
        self.clear_connection_result()

    def remove_api_key(self) -> bool:
        removed = self.credentials.delete(RESEND_API_KEY_NAME)
        self.clear_connection_result()
        return removed

    def record_connection_result(self, status: str, detail: str) -> None:
        account = self._account(create=True)
        assert account is not None
        account.last_test_status = status
        account.last_test_detail = detail[:2000]
        account.last_tested_at = datetime.utcnow()
        self.session.commit()

    def clear_connection_result(self) -> None:
        account = self._account(create=False)
        if account is None:
            return
        account.last_test_status = None
        account.last_test_detail = ""
        account.last_tested_at = None
        self.session.commit()

    # ---------------------------------------------------------------- helpers
    def _initialized(self) -> bool:
        profile = self._profile(create=False)
        if profile is None:
            return False
        return bool(self._preference_values(profile.id).get("initialized", False))

    def _profile(self, *, create: bool) -> UserProfile | None:
        profile = self.session.scalar(select(UserProfile).order_by(UserProfile.created_at).limit(1))
        if profile is None and create:
            profile = UserProfile(display_name="")
            self.session.add(profile)
            self.session.flush()
        return profile

    def _account(self, *, create: bool) -> EmailAccount | None:
        account = self.session.scalar(
            select(EmailAccount)
            .where(EmailAccount.provider == "resend")
            .order_by(EmailAccount.id)
            .limit(1)
        )
        if account is None and create:
            account = EmailAccount(provider="resend", sender_address="", sender_name="")
            self.session.add(account)
            self.session.flush()
        return account

    def _preference_values(self, user_id: str) -> dict[str, object]:
        rows = self.session.scalars(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        result: dict[str, object] = {}
        for row in rows:
            value = row.value.get("value") if isinstance(row.value, dict) else None
            if row.key.startswith(EMAIL_PREFERENCE_PREFIX):
                result[row.key.removeprefix(EMAIL_PREFERENCE_PREFIX)] = value
        return result

    def _set_preference(self, user_id: str, key: str, value: object) -> None:
        full_key = f"{EMAIL_PREFERENCE_PREFIX}{key}"
        row = self.session.scalar(
            select(UserPreference).where(
                UserPreference.user_id == user_id, UserPreference.key == full_key
            )
        )
        if row is None:
            self.session.add(UserPreference(user_id=user_id, key=full_key, value={"value": value}))
            return
        row.value = {"value": value}

    @staticmethod
    def _reply_destination(value: object) -> ReplyDestination:
        try:
            return ReplyDestination(str(value))
        except ValueError:
            return ReplyDestination.PERSONAL

    @staticmethod
    def _tone(value: object) -> EmailTone:
        try:
            return EmailTone(str(value))
        except ValueError:
            return EmailTone.PROFESSIONAL


def validate_email_settings(
    preferences: EmailPreferences, *, require_sender: bool = False
) -> list[str]:
    """Return user-facing validation errors for the non-secret settings."""

    errors: list[str] = []
    if preferences.personal_email and not is_valid_email_address(preferences.personal_email):
        errors.append("Your personal email address is not valid.")
    if require_sender and not preferences.sender_email:
        errors.append("A verified Resend sender email is required before sending.")
    elif preferences.sender_email and not is_valid_email_address(preferences.sender_email):
        errors.append("The sender email address is not valid.")
    elif preferences.sender_email and is_public_mailbox_domain(preferences.sender_email):
        errors.append(
            "A personal Gmail, Outlook or similar address cannot be a Resend sender. "
            "Verify a domain you own in Resend and use an address at that domain."
        )
    if (
        preferences.sender_email
        and preferences.personal_email
        and preferences.sender_email.strip().lower()
        == preferences.personal_email.strip().lower()
    ):
        errors.append(
            "Use a dedicated sender identity, not your personal email address. "
            "Your personal address is for replies and signatures."
        )
    if preferences.receiving_email and not is_valid_email_address(preferences.receiving_email):
        errors.append("The receiving address is not a valid email address.")
    if not 5 <= preferences.sync_interval_minutes <= 1440:
        errors.append("The synchronisation interval must be between 5 and 1440 minutes.")
    if not preferences.always_require_approval:
        errors.append("Pactlyn always requires approval before sending.")
    return errors


def preferences_from_form(
    *,
    personal_name: str,
    personal_email: str,
    sender_name: str,
    sender_email: str,
    receiving_email: str,
    reply_destination: ReplyDestination | str,
    signature: str,
    tone: EmailTone | str,
    inbound_enabled: bool,
    sync_interval_minutes: int,
) -> EmailPreferences:
    try:
        reply = ReplyDestination(str(reply_destination))
    except ValueError:
        reply = ReplyDestination.PERSONAL
    try:
        selected_tone = EmailTone(str(tone))
    except ValueError:
        selected_tone = EmailTone.PROFESSIONAL
    return EmailPreferences(
        personal_name=personal_name.strip(),
        personal_email=personal_email.strip(),
        sender_name=sender_name.strip(),
        sender_email=sender_email.strip(),
        receiving_email=receiving_email.strip(),
        reply_destination=reply,
        signature=signature,
        tone=selected_tone,
        inbound_enabled=bool(inbound_enabled),
        sync_interval_minutes=max(5, min(1440, int(sync_interval_minutes))),
        always_require_approval=True,
    )
