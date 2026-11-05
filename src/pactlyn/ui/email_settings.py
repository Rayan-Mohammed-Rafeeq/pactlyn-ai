from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pactlyn.app.bootstrap import AppContainer
from pactlyn.email.addresses import (
    is_public_mailbox_domain,
    is_resend_managed_receiving_address,
    is_valid_email_address,
)
from pactlyn.email.composer import EmailComposer
from pactlyn.email.resend.connection import ConnectionCheck, ConnectionStatus
from pactlyn.email.resend.provider import ResendProvider
from pactlyn.email.settings import (
    EmailPreferences,
    EmailTone,
    ReplyDestination,
    preferences_from_form,
    validate_email_settings,
)
from pactlyn.security.credentials import CredentialStoreError
from pactlyn.storage.models import EmailState
from pactlyn.ui.theme import COLOR_TERRACOTTA, ThemeMode, get_saved_theme, status_color

TEST_EMAIL_BODY = (
    "This is a test email sent from Pactlyn.\n\n"
    "If you received this message, the configured Resend sender and API key can "
    "deliver email. No commitment or draft was sent automatically."
)


class ConnectionTestWorker(QThread):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        provider: ResendProvider,
        sender_email: str,
        receiving_email: str,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.sender_email = sender_email
        self.receiving_email = receiving_email

    def run(self) -> None:
        try:
            result = asyncio.run(
                self.provider.check_connection(
                    sender_email=self.sender_email,
                    receiving_email=self.receiving_email,
                )
            )
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class TestEmailWorker(QThread):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, container: AppContainer, recipient: str) -> None:
        super().__init__()
        self.container = container
        self.recipient = recipient

    def run(self) -> None:
        session = self.container.session()
        try:
            async def send() -> dict[str, object]:
                repository = self.container.email_settings(session)
                preferences = repository.load(self.container.settings)
                composer = EmailComposer(session, repository, self.container.settings)
                action = composer.create_draft(
                    recipients=[self.recipient],
                    subject="Pactlyn test email",
                    body_text=TEST_EMAIL_BODY,
                    reply_to=preferences.reply_to_address(),
                    append_signature=True,
                )
                session.commit()
                service = self.container.email(session)
                service.approve(action.id)
                await service.process_queue([action.id])
                await service.reconcile()
                session.refresh(action)
                return {
                    "action_id": action.id,
                    "state": action.state.value,
                    "provider_id": action.provider_id,
                    "error": action.last_error,
                    "recipient": self.recipient,
                }

            self.finished.emit(asyncio.run(send()))
        except Exception as exc:
            session.rollback()
            self.failed.emit(str(exc))
        finally:
            session.close()


class TestEmailDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        preferences: EmailPreferences,
        recipient_default: str,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Send a test email")
        self.setMinimumWidth(640)
        self._body = preferences.with_signature(TEST_EMAIL_BODY)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "This sends one real email through the existing approval queue. "
                "Connection tests never send email."
            )
        )
        form = QFormLayout()
        sender = QLineEdit(preferences.sender or "(sender not configured)")
        sender.setReadOnly(True)
        reply_to = QLineEdit(preferences.reply_to_address() or "(none)")
        reply_to.setReadOnly(True)
        self.recipient = QLineEdit(recipient_default)
        self.recipient.setPlaceholderText("recipient@example.com")
        subject = QLineEdit("Pactlyn test email")
        subject.setReadOnly(True)
        body = QTextEdit(self._body)
        body.setReadOnly(True)
        body.setMinimumHeight(170)
        form.addRow("From", sender)
        form.addRow("To", self.recipient)
        form.addRow("Reply-to", reply_to)
        form.addRow("Subject", subject)
        form.addRow("Message", body)
        layout.addLayout(form)
        self.confirm = QCheckBox(
            "I understand this will send a real test email to the recipient above."
        )
        layout.addWidget(self.confirm)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        send_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if send_button is not None:
            send_button.setText("Send test email")
            send_button.setObjectName("primary")
            send_button.setDefault(True)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setObjectName("secondary")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        if not is_valid_email_address(self.recipient.text()):
            QMessageBox.warning(self, "Check recipient", "Enter a valid recipient email address.")
            return
        if not self.confirm.isChecked():
            QMessageBox.warning(
                self,
                "Confirmation required",
                "Tick the confirmation box before sending a real test email.",
            )
            return
        self.accept()

    def values(self) -> dict[str, Any]:
        return {"recipient": self.recipient.text().strip(), "body": self._body}


class EmailSettingsPage(QWidget):
    settingsSaved = Signal()
    syncRequested = Signal()

    def __init__(self, container: AppContainer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.container = container
        self._connection: ConnectionCheck | None = None
        self._connection_stale = False
        self._last_sync: datetime | None = None
        self._loading = False
        self._connection_worker: ConnectionTestWorker | None = None
        self._test_email_worker: TestEmailWorker | None = None
        self.theme_mode: ThemeMode = get_saved_theme()
        self._build_ui()
        self.refresh()

    def set_theme(self, mode: ThemeMode) -> None:
        self.theme_mode = mode
        self._update_connection_labels(self._preferences_from_fields())
        self._update_receiving_status(self._preferences_from_fields())

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        self.setLayout(outer)
        outer.addWidget(scroll)
        scroll.setWidget(content)

        guide = QGroupBox("First-time email setup")
        guide_layout = QVBoxLayout(guide)
        _link = f"color: {COLOR_TERRACOTTA}; text-decoration: underline;"
        instructions = QLabel(
            f'1. Create or sign in to a <a href="https://resend.com/signup" style="{_link}">Resend account</a>.<br>'
            f'2. Create an API key in <a href="https://resend.com/api-keys" style="{_link}">Resend → API Keys</a>. '
            'Use a <b>full-access</b> key to verify domains and read incoming mail; a '
            'sending-only key can send but cannot show domain or receiving status.<br>'
            f'3. Add and verify a domain you own in <a href="https://resend.com/domains" style="{_link}">Resend → Domains</a>. '
            'A personal Gmail or Outlook address cannot be used as a Resend sender.<br>'
            '4. Enter the sender name and an address at that verified domain.<br>'
            '5. Optionally copy your <code>&lt;id&gt;.resend.app</code> receiving address from '
            'the Receiving tab in Resend, or enable receiving on a custom domain.<br>'
            '6. Save, then click <b>Test connection</b>. This checks credentials without sending email.<br>'
            '7. Use <b>Send test email</b> only when you are ready to send one real, approved message.'
        )
        instructions.setWordWrap(True)
        instructions.setOpenExternalLinks(True)
        instructions.setObjectName("muted")
        guide_layout.addWidget(instructions)
        layout.addWidget(guide)

        identity = QGroupBox("Your identity")
        identity_form = QFormLayout(identity)
        self.personal_name = QLineEdit()
        self.personal_name.setPlaceholderText("For example, Rayan Mohammed Rafeeq")
        self.personal_email = QLineEdit()
        self.personal_email.setPlaceholderText("rayan@example.com")
        self.personal_email.setToolTip(
            "Your real personal address. It is used for signatures and can be used as "
            "the default reply-to. It is never treated as a Resend sender automatically."
        )
        self.signature = QTextEdit()
        self.signature.setPlaceholderText("Best regards,\nRayan")
        self.signature.setMaximumHeight(90)
        self.tone = QComboBox()
        for tone in EmailTone:
            self.tone.addItem(tone.value.title(), tone.value)
        identity_form.addRow("Your full name", self.personal_name)
        identity_form.addRow("Personal email", self.personal_email)
        identity_form.addRow("Default signature", self.signature)
        identity_form.addRow("Preferred tone", self.tone)
        layout.addWidget(identity)

        sender = QGroupBox("Resend configuration")
        sender_form = QFormLayout(sender)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Paste a Resend API key; it is saved in the OS keyring")
        self.api_key.setToolTip(
            "The key is stored through the Linux keyring and is never written to SQLite, "
            "JSON settings, logs or .env."
        )
        key_row = QHBoxLayout()
        key_row.addWidget(self.api_key, 1)
        self.show_key = QPushButton("Show")
        self.show_key.setCheckable(True)
        self.show_key.setObjectName("secondary")
        self.show_key.toggled.connect(self._toggle_key_visibility)
        key_row.addWidget(self.show_key)
        key_widget = QWidget()
        key_widget.setLayout(key_row)
        key_buttons = QHBoxLayout()
        self.save_key_button = QPushButton("Save API key")
        self.save_key_button.setObjectName("primary")
        self.save_key_button.clicked.connect(self._save_api_key)
        self.remove_key_button = QPushButton("Remove API key")
        self.remove_key_button.setObjectName("secondary")
        self.remove_key_button.clicked.connect(self._remove_api_key)
        key_buttons.addWidget(self.save_key_button)
        key_buttons.addWidget(self.remove_key_button)
        key_buttons.addStretch()
        key_widget_buttons = QWidget()
        key_widget_buttons.setLayout(key_buttons)
        self.api_key_status = QLabel()
        self.api_key_status.setObjectName("muted")
        self.api_key_status.setWordWrap(True)
        self.sender_name = QLineEdit()
        self.sender_name.setPlaceholderText("Pactlyn")
        self.sender_email = QLineEdit()
        self.sender_email.setPlaceholderText("pactlyn@your-verified-domain.example")
        self.sender_email.setToolTip(
            "The From address for outgoing email. Its domain must be verified in Resend. "
            "This is different from your personal email and from the receiving address."
        )
        self.test_connection_button = QPushButton("Test connection")
        self.test_connection_button.setObjectName("secondary")
        self.test_connection_button.clicked.connect(self._test_connection)
        self.connection_status = QLabel("Not tested yet.")
        self.connection_status.setObjectName("muted")
        self.connection_status.setWordWrap(True)
        self.domain_status = QLabel("Domain verification: not checked.")
        self.domain_status.setObjectName("muted")
        self.domain_status.setWordWrap(True)
        sender_form.addRow("API key", key_widget)
        sender_form.addRow("", key_widget_buttons)
        sender_form.addRow("", self.api_key_status)
        sender_form.addRow("Sender name", self.sender_name)
        sender_form.addRow("Sender email", self.sender_email)
        sender_form.addRow("", self.test_connection_button)
        sender_form.addRow("Connection status", self.connection_status)
        sender_form.addRow("Domain status", self.domain_status)
        layout.addWidget(sender)

        receiving = QGroupBox("Incoming email")
        receiving_form = QFormLayout(receiving)
        self.receiving_email = QLineEdit()
        self.receiving_email.setPlaceholderText("your-address@your-id.resend.app")
        self.receiving_email.setToolTip(
            "The Resend receiving address, not your personal inbox. Resend only delivers "
            "mail to its managed <id>.resend.app domain or to a custom domain with "
            "receiving enabled."
        )
        self.inbound_enabled = QCheckBox("Enable inbound email synchronisation")
        self.sync_interval = QSpinBox()
        self.sync_interval.setRange(5, 1440)
        self.sync_interval.setSuffix(" minutes")
        self.sync_interval.setValue(15)
        self.sync_now_button = QPushButton("Synchronise now")
        self.sync_now_button.setObjectName("secondary")
        self.sync_now_button.clicked.connect(lambda: self.syncRequested.emit())
        self.receiving_status = QLabel()
        self.receiving_status.setWordWrap(True)
        self.receiving_status.setObjectName("muted")
        receiving_help = QLabel(
            "Resend must be configured separately to receive mail. Entering an arbitrary "
            "address here does not activate inbound email. Pactlyn polls the receiving "
            "API; it does not require a public webhook."
        )
        receiving_help.setWordWrap(True)
        receiving_help.setObjectName("muted")
        receiving_form.addRow("Receiving address", self.receiving_email)
        receiving_form.addRow("Synchronisation", self.inbound_enabled)
        receiving_form.addRow("Interval", self.sync_interval)
        receiving_form.addRow("", self.sync_now_button)
        receiving_form.addRow("Status", self.receiving_status)
        receiving_form.addRow("", receiving_help)
        layout.addWidget(receiving)

        behaviour = QGroupBox("Email behaviour")
        behaviour_form = QFormLayout(behaviour)
        self.reply_destination = QComboBox()
        self.reply_destination.addItem(
            "Reply to my personal email address", ReplyDestination.PERSONAL.value
        )
        self.reply_destination.addItem(
            "Reply to Pactlyn's configured receiving address",
            ReplyDestination.RECEIVING.value,
        )
        self.reply_destination.currentIndexChanged.connect(self._update_reply_help)
        self.reply_help = QLabel()
        self.reply_help.setWordWrap(True)
        self.reply_help.setObjectName("muted")
        self.approval = QCheckBox("Always require approval before sending")
        self.approval.setChecked(True)
        self.approval.setEnabled(False)
        approval_help = QLabel(
            "Pactlyn never sends a draft automatically. The exact approved payload "
            "(From, To, CC/BCC, Reply-To, subject, body, headers and attachments) must "
            "match before anything enters the send queue."
        )
        approval_help.setWordWrap(True)
        approval_help.setObjectName("muted")
        behaviour_form.addRow("Default reply destination", self.reply_destination)
        behaviour_form.addRow("", self.reply_help)
        behaviour_form.addRow("Sending approval", self.approval)
        behaviour_form.addRow("", approval_help)
        layout.addWidget(behaviour)

        actions = QHBoxLayout()
        self.save_button = QPushButton("Save email settings")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(lambda: self._save())
        self.cancel_button = QPushButton("Cancel changes")
        self.cancel_button.setObjectName("secondary")
        self.cancel_button.clicked.connect(self.refresh)
        self.test_email_button = QPushButton("Send test email")
        self.test_email_button.setObjectName("secondary")
        self.test_email_button.clicked.connect(self._test_email)
        actions.addWidget(self.save_button)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.test_email_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.page_status = QLabel()
        self.page_status.setWordWrap(True)
        layout.addWidget(self.page_status)
        layout.addStretch()

        self._update_reply_help()

    def _toggle_key_visibility(self, visible: bool) -> None:
        self.api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self.show_key.setText("Hide" if visible else "Show")

    def _update_reply_help(self) -> None:
        if self.reply_destination.currentData() == ReplyDestination.RECEIVING.value:
            text = (
                "Replies to your outgoing mail go to the Pactlyn receiving address. "
                "This keeps conversations inside Pactlyn when Resend receiving is configured."
            )
        else:
            text = (
                "Replies to your outgoing mail go to your personal email. For a message "
                "received through Pactlyn, Pactlyn still replies to that message's actual "
                "sender and preserves its threading headers."
            )
        self.reply_help.setText(text)

    # -------------------------------------------------------------- lifecycle
    def refresh(self) -> None:
        session = self.container.session()
        try:
            repository = self.container.email_settings(session)
            preferences = repository.load(self.container.settings)
            self._last_sync = repository.last_synced_at()
            self._api_key_source = repository.api_key_source(self.container.settings)
            key_configured = repository.api_key_configured()
            keyring_available = repository.credentials.is_available()
            keyring_backend = repository.credentials.backend_name()
        finally:
            session.close()
        self._loading = True
        try:
            self.personal_name.setText(preferences.personal_name)
            self.personal_email.setText(preferences.personal_email)
            self.signature.setPlainText(preferences.signature)
            self._select_data(self.tone, preferences.tone.value)
            self.sender_name.setText(preferences.sender_name)
            self.sender_email.setText(preferences.sender_email)
            self.receiving_email.setText(preferences.receiving_email)
            self.inbound_enabled.setChecked(preferences.inbound_enabled)
            self.sync_interval.setValue(max(5, min(1440, preferences.sync_interval_minutes)))
            self._select_data(self.reply_destination, preferences.reply_destination.value)
            self.approval.setChecked(True)
            self.api_key.clear()
            self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_key.setChecked(False)
            self.api_key.setPlaceholderText(
                "Saved in the OS keyring — enter a new key to replace it"
                if key_configured
                else "Paste a Resend API key; it is saved in the OS keyring"
            )
            if not keyring_available:
                self.api_key_status.setText(
                    f"The operating-system keyring is unavailable ({keyring_backend}). "
                    "Unlock or install a keyring before saving a key. Pactlyn will not "
                    "store the API key in its database."
                )
            elif key_configured:
                self.api_key_status.setText(
                    "API key saved in the OS keyring. The saved value is never displayed."
                )
            else:
                self.api_key_status.setText("No Resend API key is saved in the OS keyring.")
            self.remove_key_button.setEnabled(key_configured)
        finally:
            self._loading = False
        self._connection = None
        self._connection_stale = False
        self._last_preferences = preferences
        self._update_connection_labels(preferences)
        self._update_receiving_status(preferences)
        self.page_status.clear()
        self._update_reply_help()

    def refresh_status(self) -> None:
        """Refresh status labels without discarding unsaved form changes."""

        session = self.container.session()
        try:
            repository = self.container.email_settings(session)
            self._last_sync = repository.last_synced_at()
        finally:
            session.close()
        self._update_receiving_status(self._preferences_from_fields())

    def _select_data(self, combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    # ------------------------------------------------------------ persistence
    def _preferences_from_fields(self) -> EmailPreferences:
        return preferences_from_form(
            personal_name=self.personal_name.text(),
            personal_email=self.personal_email.text(),
            sender_name=self.sender_name.text(),
            sender_email=self.sender_email.text(),
            receiving_email=self.receiving_email.text(),
            reply_destination=str(self.reply_destination.currentData()),
            signature=self.signature.toPlainText(),
            tone=str(self.tone.currentData()),
            inbound_enabled=self.inbound_enabled.isChecked(),
            sync_interval_minutes=self.sync_interval.value(),
        )

    def _save(self, *, show_message: bool = True) -> bool:
        preferences = self._preferences_from_fields()
        errors = validate_email_settings(preferences)
        if errors:
            message = "\n".join(f"• {error}" for error in errors)
            self.page_status.setText(message)
            self.page_status.setStyleSheet(f"color: {status_color('error', self.theme_mode)};")
            if show_message:
                QMessageBox.warning(self, "Check email settings", message)
            return False

        previous = getattr(self, "_last_preferences", None)
        session = self.container.session()
        try:
            repository = self.container.email_settings(session)
            saved = repository.save(
                personal_name=preferences.personal_name,
                personal_email=preferences.personal_email,
                sender_name=preferences.sender_name,
                sender_email=preferences.sender_email,
                receiving_email=preferences.receiving_email,
                reply_destination=preferences.reply_destination,
                signature=preferences.signature,
                tone=preferences.tone,
                inbound_enabled=preferences.inbound_enabled,
                sync_interval_minutes=preferences.sync_interval_minutes,
            )
        except Exception as exc:
            session.rollback()
            self.page_status.setText(f"Could not save email settings: {exc}")
            self.page_status.setStyleSheet(f"color: {status_color('error', self.theme_mode)};")
            if show_message:
                QMessageBox.warning(self, "Could not save email settings", str(exc))
            return False
        finally:
            session.close()
        self.container.refresh_email_provider()
        self._last_preferences = saved
        if previous and (
            previous.sender_email != saved.sender_email
            or previous.receiving_email != saved.receiving_email
        ):
            self._connection = None
            self._connection_stale = True
        if preferences.receiving_email and is_public_mailbox_domain(preferences.receiving_email):
            self.page_status.setText(
                "Email settings saved. The receiving address is a personal mailbox, so "
                "incoming mail is not configured. Use a Resend receiving address."
            )
            self.page_status.setStyleSheet(f"color: {status_color('warning', self.theme_mode)};")
        else:
            self.page_status.setText("Email settings saved.")
            self.page_status.setStyleSheet(f"color: {status_color('success', self.theme_mode)};")
        if self.api_key.text().strip():
            self.page_status.setText(
                f"{self.page_status.text()} Click Save API key to store the new key in the keyring."
            )
        self._update_connection_labels(saved)
        self._update_receiving_status(saved)
        self.settingsSaved.emit()
        return True

    def _save_api_key(self) -> None:
        value = self.api_key.text().strip()
        if not value:
            QMessageBox.warning(self, "API key", "Enter a Resend API key first.")
            return
        session = self.container.session()
        try:
            repository = self.container.email_settings(session)
            repository.save_api_key(value)
        except (CredentialStoreError, ValueError) as exc:
            self.page_status.setText(str(exc))
            self.page_status.setStyleSheet(f"color: {status_color('error', self.theme_mode)};")
            QMessageBox.warning(self, "Could not save API key", str(exc))
            return
        finally:
            session.close()
        self.api_key.clear()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_key.setChecked(False)
        self.api_key.setPlaceholderText("Saved in the OS keyring — enter a new key to replace it")
        self.api_key_status.setText(
            "API key saved in the OS keyring. The saved value is never displayed."
        )
        self.remove_key_button.setEnabled(True)
        self._api_key_source = "keyring"
        self.container.refresh_email_provider()
        self._connection = None
        self._connection_stale = True
        self.page_status.setText("API key saved in the OS keyring.")
        self.page_status.setStyleSheet(f"color: {status_color('success', self.theme_mode)};")
        self._update_connection_labels(self._preferences_from_fields())

    def _remove_api_key(self) -> None:
        response = QMessageBox.question(
            self,
            "Remove API key",
            "Remove the Resend API key from the operating system keyring?",
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        session = self.container.session()
        try:
            repository = self.container.email_settings(session)
            removed = repository.remove_api_key()
            source = repository.api_key_source(self.container.settings)
        except CredentialStoreError as exc:
            QMessageBox.warning(self, "Could not remove API key", str(exc))
            return
        finally:
            session.close()
        self.container.refresh_email_provider()
        self.api_key.clear()
        self.api_key.setPlaceholderText("Paste a Resend API key; it is saved in the OS keyring")
        self.api_key_status.setText(
            "API key removed from the OS keyring."
            if removed
            else "No saved API key was present in the OS keyring."
        )
        self.remove_key_button.setEnabled(False)
        self._api_key_source = source
        self._connection = None
        self._connection_stale = True
        if source == "environment":
            self.api_key_status.setText(
                f"{self.api_key_status.text()} A development environment key is still "
                "being used as a fallback."
            )
        self._update_connection_labels(self._preferences_from_fields())

    # -------------------------------------------------------------- connection
    def _test_connection(self) -> None:
        if self._connection_worker and self._connection_worker.isRunning():
            return
        if self.api_key.text().strip():
            QMessageBox.information(
                self,
                "Save the API key first",
                "Click Save API key before testing so the test uses the keyring value.",
            )
            return
        if not self._save(show_message=True):
            return
        session = self.container.session()
        try:
            repository = self.container.email_settings(session)
            key = repository.resolve_api_key(self.container.settings)
        finally:
            session.close()
        if not key:
            self._connection = ConnectionCheck(
                status=ConnectionStatus.CREDENTIALS_MISSING,
                message="No Resend API key is saved. Add one in Settings → Email.",
            )
            self._connection_stale = False
            self._update_connection_labels(self._preferences_from_fields())
            self._update_receiving_status(self._preferences_from_fields())
            return
        preferences = self._preferences_from_fields()
        provider = ResendProvider(key)
        self.connection_status.setText("Connecting…")
        self.connection_status.setStyleSheet(f"color: {status_color('info', self.theme_mode)};")
        self.test_connection_button.setEnabled(False)
        worker = ConnectionTestWorker(
            provider, preferences.sender_email, preferences.receiving_email
        )
        worker.finished.connect(lambda result: self._connection_finished(worker, result))
        worker.failed.connect(lambda error: self._connection_failed(worker, error))
        self._connection_worker = worker
        worker.start()

    def _connection_finished(self, worker: ConnectionTestWorker, result: object) -> None:
        worker.deleteLater()
        if self._connection_worker is worker:
            self._connection_worker = None
        self.test_connection_button.setEnabled(True)
        if not isinstance(result, ConnectionCheck):
            self._connection_failed(worker, "The connection test returned an unknown result.")
            return
        self._connection = result
        self._connection_stale = False
        preferences = self._preferences_from_fields()
        session = self.container.session()
        try:
            repository = self.container.email_settings(session)
            repository.record_connection_result(result.status.value, result.message)
        finally:
            session.close()
        self._update_connection_labels(preferences)
        self._update_receiving_status(preferences)
        self.page_status.setText(result.message)
        self.page_status.setStyleSheet(
            f"color: {self._connection_color(result.status, restricted=result.restricted_key)};"
        )

    def _connection_failed(self, worker: ConnectionTestWorker, error: str) -> None:
        worker.deleteLater()
        if self._connection_worker is worker:
            self._connection_worker = None
        self.test_connection_button.setEnabled(True)
        self._connection = ConnectionCheck(
            status=ConnectionStatus.PROVIDER_ERROR,
            message=f"The connection test failed unexpectedly: {error}",
        )
        self._connection_stale = False
        self._update_connection_labels(self._preferences_from_fields())
        self.page_status.setText(self._connection.message)
        self.page_status.setStyleSheet(f"color: {status_color('error', self.theme_mode)};")

    def _update_connection_labels(self, preferences: EmailPreferences) -> None:
        if self._connection_stale:
            self.connection_status.setText("Not tested after the latest changes.")
            self.connection_status.setStyleSheet(f"color: {status_color('warning', self.theme_mode)};")
            self.domain_status.setText("Domain verification: not checked after the latest changes.")
            return
        if self._connection is not None:
            self.connection_status.setText(self._connection.status.label)
            self.connection_status.setStyleSheet(
                "color: "
                + self._connection_color(
                    self._connection.status, restricted=self._connection.restricted_key
                )
                + ";"
            )
            self.domain_status.setText(f"Domain verification: {self._connection.domain_summary}")
            return
        if preferences.last_test_status:
            try:
                stored_status: ConnectionStatus | None = ConnectionStatus(
                    preferences.last_test_status
                )
            except ValueError:
                stored_status = None
            status = stored_status.label if stored_status else preferences.last_test_status
            self.connection_status.setText(
                f"Last check: {status}"
                + (
                    f" · {preferences.last_tested_at:%d %b %Y %H:%M}"
                    if preferences.last_tested_at
                    else ""
                )
            )
            self.connection_status.setStyleSheet(
                "color: "
                + (self._connection_color(stored_status) if stored_status else status_color("warning", self.theme_mode))
                + ";"
            )
            self.domain_status.setText(
                "Domain verification: run Test connection to check the current sender."
            )
        else:
            self.connection_status.setText("Not tested yet.")
            self.connection_status.setStyleSheet(f"color: {status_color('muted', self.theme_mode)};")
            self.domain_status.setText("Domain verification: not checked.")

    def _update_receiving_status(self, preferences: EmailPreferences) -> None:
        receiving = preferences.receiving_email.strip()
        if not receiving:
            address_status = "No receiving address entered."
            domain_status = "Not configured."
            api_status = "Not checked."
        elif not is_valid_email_address(receiving):
            address_status = "Entered, but the address is invalid."
            domain_status = "Not configured."
            api_status = "Not checked."
        elif is_public_mailbox_domain(receiving):
            address_status = "Entered, but this is a personal mailbox, not a Resend receiving address."
            domain_status = "Not a Resend receiving domain."
            api_status = "Not checked."
        else:
            address_status = "Configured in Pactlyn."
            if self._connection_stale:
                domain_status = "Not checked after the latest changes."
                api_status = "Not checked."
            elif self._connection is not None and self._connection.receiving_address_configured:
                domain_status = (
                    "Verified in Resend."
                    if self._connection.receiving_domain_configured
                    else "Not verified in Resend."
                )
                api_status = (
                    "Available."
                    if self._connection.receiving_api_ok
                    else "Unavailable or not checked."
                )
            elif is_resend_managed_receiving_address(receiving):
                domain_status = "Resend-managed domain. Run Test connection to verify API access."
                api_status = "Not checked."
            else:
                domain_status = "Not checked. Run Test connection to verify Resend receiving."
                api_status = "Not checked."
        enabled = preferences.inbound_enabled
        if self._last_sync is not None and enabled:
            sync_status = f"Enabled · last synchronised {self._last_sync:%d %b %Y %H:%M}"
        elif enabled:
            sync_status = "Enabled · not synchronised yet"
        else:
            sync_status = "Disabled"
        self.receiving_status.setText(
            f"Receiving address: {address_status}\n"
            f"Receiving domain: {domain_status}\n"
            f"Provider inbound API: {api_status}\n"
            f"Incoming synchronisation: {sync_status}"
        )

    @staticmethod
    def _connection_status_from_value(value: str) -> str | None:
        try:
            return ConnectionStatus(value).label
        except ValueError:
            return None

    def _connection_color(
        self,
        status: ConnectionStatus,
        *,
        restricted: bool = False,
        mode: ThemeMode | None = None,
    ) -> str:
        current_mode: ThemeMode = self.theme_mode if mode is None else mode
        if status == ConnectionStatus.CONNECTED and not restricted:
            return status_color("success", current_mode)
        if status in {
            ConnectionStatus.NETWORK_UNAVAILABLE,
            ConnectionStatus.RATE_LIMITED,
            ConnectionStatus.PROVIDER_ERROR,
        }:
            return status_color("warning", current_mode)
        return status_color("error", current_mode)

    # --------------------------------------------------------------- test mail
    def _test_email(self) -> None:
        if self._test_email_worker and self._test_email_worker.isRunning():
            return
        if self.api_key.text().strip():
            QMessageBox.information(
                self,
                "Save the API key first",
                "Click Save API key before sending a test so the keyring value is used.",
            )
            return
        if not self._save(show_message=True):
            return
        preferences = self._preferences_from_fields()
        errors = validate_email_settings(preferences, require_sender=True)
        if errors:
            QMessageBox.warning(self, "Email not ready", "\n".join(errors))
            return
        session = self.container.session()
        try:
            repository = self.container.email_settings(session)
            key = repository.resolve_api_key(self.container.settings)
        finally:
            session.close()
        if not key:
            QMessageBox.information(
                self,
                "Resend not configured",
                "Save a Resend API key before sending a test email.",
            )
            return
        self.container.refresh_email_provider()
        dialog = TestEmailDialog(self, preferences, preferences.personal_email)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        recipient = str(dialog.values()["recipient"])
        confirmation = QMessageBox.question(
            self,
            "Send test email?",
            f"Send one real test email from {preferences.sender} to {recipient}?",
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        self.test_email_button.setEnabled(False)
        self.page_status.setText("Sending the approved test email…")
        self.page_status.setStyleSheet(f"color: {status_color('info', self.theme_mode)};")
        worker = TestEmailWorker(self.container, recipient)
        worker.finished.connect(lambda result: self._test_email_finished(worker, result))
        worker.failed.connect(lambda error: self._test_email_failed(worker, error))
        self._test_email_worker = worker
        worker.start()

    def _test_email_finished(self, worker: TestEmailWorker, result: object) -> None:
        worker.deleteLater()
        if self._test_email_worker is worker:
            self._test_email_worker = None
        self.test_email_button.setEnabled(True)
        if not isinstance(result, dict):
            self._test_email_failed(worker, "The test send returned an unknown result.")
            return
        state = str(result.get("state", ""))
        provider_id = result.get("provider_id")
        error = result.get("error")
        if state == EmailState.SENT.value:
            message = (
                f"Resend accepted the test email for {result.get('recipient')}.\n\n"
                f"Provider message ID: {provider_id or 'not returned'}\n"
                "API acceptance: accepted\n"
                "Delivery status: not yet confirmed. Resend accepted the message; this "
                "is separate from inbox delivery. Use provider reconciliation for later status."
            )
            self.page_status.setText("Test email accepted by Resend.")
            self.page_status.setStyleSheet(f"color: {status_color('success', self.theme_mode)};")
        elif state == EmailState.DELIVERED.value:
            message = (
                f"Test email delivered to {result.get('recipient')}.\n\n"
                f"Provider message ID: {provider_id or 'not returned'}\n"
                "API acceptance: accepted\nDelivery status: delivered."
            )
            self.page_status.setText("Test email delivered.")
            self.page_status.setStyleSheet(f"color: {status_color('success', self.theme_mode)};")
        else:
            message = (
                "The test email was not accepted.\n\n"
                f"State: {state or 'unknown'}\n"
                f"Provider ID: {provider_id or 'none'}\n"
                f"Error: {error or 'No provider error was recorded.'}"
            )
            self.page_status.setText("Test email failed or has an unknown outcome.")
            self.page_status.setStyleSheet(f"color: {status_color('error', self.theme_mode)};")
        QMessageBox.information(self, "Test email result", message)

    def _test_email_failed(self, worker: TestEmailWorker, error: str) -> None:
        worker.deleteLater()
        if self._test_email_worker is worker:
            self._test_email_worker = None
        self.test_email_button.setEnabled(True)
        self.page_status.setText(f"Test email failed: {error}")
        self.page_status.setStyleSheet(f"color: {status_color('error', self.theme_mode)};")
        QMessageBox.warning(self, "Test email failed", error)

    def shutdown(self) -> None:
        for worker in (self._connection_worker, self._test_email_worker):
            if worker and worker.isRunning():
                worker.quit()
                worker.wait(2000)
