from __future__ import annotations

import asyncio
import base64
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from dateutil import parser as date_parser
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from pactlyn.app.bootstrap import AppContainer
from pactlyn.core.commitments import (
    CaptureResult,
    CommitmentCandidate,
    CommitmentExtractor,
    CommitmentRelationshipCandidate,
)
from pactlyn.core.connectivity import ConnectivityMonitor, ConnectivityState
from pactlyn.core.recommendations import RecommendationEngine
from pactlyn.core.scheduler import ReminderScheduler
from pactlyn.email.addresses import email_address, is_valid_email_address
from pactlyn.email.composer import DraftDefaults
from pactlyn.email.inbound_sync import InboundEmailSync
from pactlyn.platform.linux.autostart import LinuxAutostart
from pactlyn.rag.retrieval import HybridRetriever
from pactlyn.rag.service import RAGService
from pactlyn.storage.backup import BackupError, BackupService
from pactlyn.storage.models import (
    CommitmentStatus,
    CommitmentType,
    Contact,
    EmailSendAction,
    EmailState,
    EmailThread,
    MemoryKind,
)
from pactlyn.ui.email_settings import EmailSettingsPage
from pactlyn.ui.theme import (
    COLOR_PINE,
    COLOR_TERRACOTTA,
    BrandWidget,
    ThemeMode,
    get_saved_theme,
    get_stylesheet,
    save_theme,
    status_color,
)

STYLE = get_stylesheet("light")


class Card(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")


class CaptureDialog(QDialog):
    def __init__(self, parent: QWidget, initial: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Capture a commitment")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("What do you want Pactlyn to remember?"))
        self.text = QTextEdit()
        self.text.setPlaceholderText("e.g. I need to submit my assignment by Friday")
        self.text.setPlainText(initial)
        layout.addWidget(self.text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class CaptureWorker(QThread):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, container: AppContainer, text: str, context: str):
        super().__init__()
        self.container = container
        self.text = text
        self.context = context

    def run(self) -> None:
        try:
            result = asyncio.run(
                self.container.llm.extract_commitments(
                    self.text,
                    timezone_name=self.container.settings.default_timezone,
                    context=self.context,
                    now=self.container.clock(),
                )
            )
            self.finished.emit(result)
        except Exception as exc:  # the UI must recover from worker failures
            self.failed.emit(str(exc))


class CapturePersistenceWorker(QThread):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        container: AppContainer,
        candidates: list[CommitmentCandidate],
        relationships: list[CommitmentRelationshipCandidate],
        rejected_relationships: list[CommitmentRelationshipCandidate],
        source: str,
    ):
        super().__init__()
        self.container = container
        self.candidates = candidates
        self.relationships = relationships
        self.rejected_relationships = rejected_relationships
        self.source = source

    def run(self) -> None:
        session = self.container.session()
        try:
            async def persist() -> list[str]:
                service = self.container.commitments(session)
                memory = self.container.memories(session)
                identifiers: list[str] = []
                commitments = service.create_many(
                    self.candidates,
                    self.relationships,
                    rejected_relationships=self.rejected_relationships,
                    source=self.source,
                )
                for candidate, commitment in zip(self.candidates, commitments, strict=True):
                    await memory.remember(
                        candidate.evidence or candidate.description,
                        kind=MemoryKind.EPISODIC,
                        source_type="commitment",
                        source_id=commitment.id,
                        verified=not candidate.needs_confirmation,
                    )
                    identifiers.append(commitment.id)
                session.commit()
                return identifiers

            result = asyncio.run(persist())
            self.finished.emit(result)
        except Exception as exc:
            session.rollback()
            self.failed.emit(str(exc))
        finally:
            session.close()


class AssistantWorker(QThread):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, container: AppContainer, question: str):
        super().__init__()
        self.container = container
        self.question = question

    def run(self) -> None:
        session = self.container.session()
        try:
            async def answer() -> object:
                retriever = HybridRetriever(session, self.container.vectors, self.container.embedder)
                return await RAGService(session, self.container.llm, retriever).answer(self.question)

            self.finished.emit(asyncio.run(answer()))
        except Exception as exc:
            session.rollback()
            self.failed.emit(str(exc))
        finally:
            session.close()


class EmailQueueWorker(QThread):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, container: AppContainer):
        super().__init__()
        self.container = container

    def run(self) -> None:
        session = self.container.session()
        try:
            async def process() -> list[EmailSendAction]:
                service = self.container.email(session)
                result = await service.process_queue()
                await service.reconcile()
                return result

            result = asyncio.run(process())
            self.finished.emit(result)
        except Exception as exc:
            session.rollback()
            self.failed.emit(str(exc))
        finally:
            session.close()


class EmailSyncWorker(QThread):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        container: AppContainer,
        account_id: str | None = None,
        receiving_address: str | None = None,
        silent: bool = False,
    ):
        super().__init__()
        self.container = container
        self.account_id = account_id
        self.receiving_address = receiving_address
        self.silent = silent

    def run(self) -> None:
        if not self.container.email_provider:
            self.failed.emit("Resend is not configured")
            return
        session = self.container.session()
        try:
            result = asyncio.run(
                InboundEmailSync(
                    session,
                    self.container.email_provider,
                    account_id=self.account_id,
                    receiving_address=self.receiving_address,
                ).sync()
            )
            self.finished.emit(result)
        except Exception as exc:
            session.rollback()
            self.failed.emit(str(exc))
        finally:
            session.close()


class ConnectivityWorker(QThread):
    finished = Signal(object)

    def __init__(self, monitor: ConnectivityMonitor):
        super().__init__()
        self.monitor = monitor

    def run(self) -> None:
        state = asyncio.run(self.monitor.probe("https://api.resend.com"))
        self.finished.emit(state)


class EmailDraftDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        commitments: list[Any],
        contacts: list[Contact],
        defaults: DraftDefaults | None = None,
        action: EmailSendAction | None = None,
    ):
        super().__init__(parent)
        defaults = defaults or DraftDefaults()
        self.setWindowTitle("Edit email draft" if action else "New email draft")
        self.resize(720, 700)
        self._signature = defaults.signature
        self._headers = dict(action.headers if action else defaults.headers)
        self._attachments = [dict(item) for item in (action.attachments if action else defaults.attachments)]
        layout = QFormLayout(self)
        sender_value = action.sender if action else defaults.sender
        recipients_value = action.recipients if action else defaults.recipients
        cc_value = action.cc if action else defaults.cc
        bcc_value = action.bcc if action else defaults.bcc
        reply_to_value = action.reply_to if action else defaults.reply_to
        subject_value = action.subject if action else defaults.subject
        body_value = action.body_text if action else defaults.body_text
        self.email_sender = QLineEdit(sender_value)
        self.email_sender.setReadOnly(bool(sender_value))
        self.email_sender.setToolTip(
            "The configured Resend sender. Its domain must be verified in Resend."
        )
        self.recipients = QLineEdit(", ".join(recipients_value))
        self.cc = QLineEdit(", ".join(cc_value))
        self.bcc = QLineEdit(", ".join(bcc_value))
        self.reply_to = QLineEdit(reply_to_value or "")
        self.subject = QLineEdit(subject_value)
        self.body = QTextEdit(body_value)
        self.body.setMinimumHeight(220)
        self.contact_picker = QComboBox()
        self.contact_picker.addItem("Choose a Pactlyn contact…", None)
        for contact in sorted(contacts, key=lambda item: item.name.lower()):
            if contact.email:
                self.contact_picker.addItem(
                    f"{contact.name} <{contact.email}>", contact.email
                )
        self.contact_picker.activated.connect(self._add_contact)
        self.signature = QCheckBox("Append my default signature")
        self.signature.setChecked(bool(self._signature) and action is None)
        self.tone_label = QLabel(str(defaults.tone).title())
        self.tone_label.setObjectName("muted")
        self.attachment_list = QListWidget()
        self.attachment_list.setMaximumHeight(80)
        attachment_buttons = QHBoxLayout()
        add_attachment = QPushButton("Add file…")
        add_attachment.setObjectName("secondary")
        add_attachment.clicked.connect(self._add_attachment)
        remove_attachment = QPushButton("Remove")
        remove_attachment.setObjectName("secondary")
        remove_attachment.clicked.connect(self._remove_attachment)
        attachment_buttons.addWidget(add_attachment)
        attachment_buttons.addWidget(remove_attachment)
        attachment_buttons.addStretch()
        attachment_widget = QWidget()
        attachment_layout = QVBoxLayout(attachment_widget)
        attachment_layout.setContentsMargins(0, 0, 0, 0)
        attachment_layout.addWidget(self.attachment_list)
        attachment_layout.addLayout(attachment_buttons)
        self.commitment = QComboBox()
        self.commitment.addItem("No related commitment", None)
        for commitment in commitments:
            self.commitment.addItem(commitment.title, commitment.id)
        selected_commitment = action.commitment_id if action else defaults.commitment_id
        if selected_commitment:
            index = self.commitment.findData(selected_commitment)
            if index >= 0:
                self.commitment.setCurrentIndex(index)
        layout.addRow("Sender", self.email_sender)
        layout.addRow("Add contact", self.contact_picker)
        layout.addRow("To (comma-separated)", self.recipients)
        layout.addRow("CC", self.cc)
        layout.addRow("BCC", self.bcc)
        layout.addRow("Reply-to", self.reply_to)
        layout.addRow("Subject", self.subject)
        layout.addRow("Preferred tone", self.tone_label)
        layout.addRow("Related commitment", self.commitment)
        layout.addRow("Body", self.body)
        layout.addRow("", self.signature)
        layout.addRow("Attachments", attachment_widget)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self._refresh_attachment_list()

    @staticmethod
    def _addresses(value: str) -> list[str]:
        return [address.strip() for address in value.split(",") if address.strip()]

    def _add_contact(self, index: int) -> None:
        email = self.contact_picker.itemData(index)
        if not email:
            return
        existing = self._addresses(self.recipients.text())
        if email not in existing:
            existing.append(str(email))
            self.recipients.setText(", ".join(existing))
        self.contact_picker.setCurrentIndex(0)

    def _refresh_attachment_list(self) -> None:
        self.attachment_list.clear()
        for item in self._attachments:
            filename = str(item.get("filename", "attachment"))
            size = len(str(item.get("content_base64", ""))) * 3 // 4
            self.attachment_list.addItem(f"{filename} ({size // 1024 or 1} KB)")

    def _add_attachment(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Attach a file")
        if not path:
            return
        source = Path(path)
        try:
            content = source.read_bytes()
        except OSError as exc:
            QMessageBox.warning(self, "Could not read file", str(exc))
            return
        if len(content) > 20 * 1024 * 1024:
            QMessageBox.warning(
                self, "Attachment too large", "Attachments are limited to 20 MB each."
            )
            return
        content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        self._attachments.append(
            {
                "filename": source.name,
                "content_type": content_type,
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
        self._refresh_attachment_list()

    def _remove_attachment(self) -> None:
        row = self.attachment_list.currentRow()
        if 0 <= row < len(self._attachments):
            self._attachments.pop(row)
            self._refresh_attachment_list()

    def values(self) -> dict[str, Any]:
        body = self.body.toPlainText()
        if self.signature.isChecked() and self._signature.strip():
            if not body.rstrip().endswith(self._signature.strip()):
                body = f"{body.rstrip()}\n\n{self._signature.strip()}".strip()
        return {
            "sender": self.email_sender.text().strip(),
            "recipients": self._addresses(self.recipients.text()),
            "cc": self._addresses(self.cc.text()),
            "bcc": self._addresses(self.bcc.text()),
            "reply_to": self.reply_to.text().strip() or None,
            "subject": self.subject.text().strip(),
            "body_text": body,
            "commitment_id": self.commitment.currentData(),
            "headers": dict(self._headers),
            "attachments": [dict(item) for item in self._attachments],
        }

    def _validate_and_accept(self) -> None:
        values = self.values()
        if (
            not values["sender"]
            or not values["recipients"]
            or not values["subject"]
            or not values["body_text"].strip()
        ):
            QMessageBox.warning(
                self,
                "Incomplete draft",
                "Sender, recipient, subject and body are required.",
            )
            return
        addresses = [
            *values["recipients"],
            *values["cc"],
            *values["bcc"],
            values["reply_to"] or "",
        ]
        invalid = [address for address in addresses if address and not is_valid_email_address(address)]
        if invalid or not is_valid_email_address(values["sender"]):
            QMessageBox.warning(
                self,
                "Check addresses",
                "One or more email addresses are invalid:\n"
                + "\n".join(invalid or [values["sender"]]),
            )
            return
        self.accept()


class EmailApprovalDialog(QDialog):
    def __init__(self, parent: QWidget, action: EmailSendAction):
        super().__init__(parent)
        self.setWindowTitle("Approve exact email payload")
        self.resize(680, 600)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Review the complete payload. Approval is bound to these exact values; "
                "editing the draft afterwards invalidates it."
            )
        )
        preview = QTextEdit()
        preview.setReadOnly(True)
        attachments = (
            "\n".join(
                f"- {item.get('filename', 'attachment')} "
                f"({item.get('content_type', 'application/octet-stream')})"
                for item in action.attachments
            )
            or "None"
        )
        headers = "\n".join(
            f"- {name}: {value}" for name, value in sorted(action.headers.items())
        ) or "None"
        preview.setPlainText(
            f"From: {action.sender}\n"
            f"To: {', '.join(action.recipients)}\n"
            f"CC: {', '.join(action.cc) or 'None'}\n"
            f"BCC: {', '.join(action.bcc) or 'None'}\n"
            f"Reply-To: {action.reply_to or 'None'}\n"
            f"Subject: {action.subject}\n"
            f"Headers:\n{headers}\n"
            f"Attachments:\n{attachments}\n\n"
            f"{action.body_text}"
        )
        layout.addWidget(preview, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        approve_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if approve_button is not None:
            approve_button.setText("Approve exact payload")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class CommitmentReviewDialog(QDialog):
    def __init__(self, parent: QWidget, result: CaptureResult):
        super().__init__(parent)
        self.setWindowTitle("Review commitments")
        self.resize(680, 560)
        self._capture_result = result
        self.forms: list[dict[str, QWidget]] = []
        layout = QVBoxLayout(self)
        if result.used_fallback:
            notice = QLabel("Offline fallback was explicitly selected. Review every field before saving.")
            notice.setObjectName("muted")
            layout.addWidget(notice)
        if result.explanation:
            explanation = QLabel(result.explanation)
            explanation.setWordWrap(True)
            explanation.setObjectName("muted")
            layout.addWidget(explanation)
        if result.relationships:
            relationships = QLabel(
                "Relationships: "
                + "; ".join(
                    f"{relation.source_index + 1} {relation.relationship.value} {relation.target_index + 1}"
                    for relation in result.relationships
                )
            )
            relationships.setWordWrap(True)
            relationships.setObjectName("muted")
            layout.addWidget(relationships)
        if result.relationship_warnings:
            warning = QLabel("Relationship review required: " + "; ".join(result.relationship_warnings))
            warning.setWordWrap(True)
            warning.setObjectName("muted")
            layout.addWidget(warning)
        tabs = QTabWidget()
        for index, candidate in enumerate(result.candidates, start=1):
            tabs.addTab(self._candidate_form(candidate), f"Commitment {index}")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(tabs)
        layout.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._values: list[CommitmentCandidate] = []

    def _candidate_form(self, candidate: CommitmentCandidate) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        fields: dict[str, QWidget] = {}
        title = QLineEdit(candidate.title)
        description = QTextEdit(candidate.description)
        description.setMaximumHeight(100)
        person = QLineEdit(candidate.person or "")
        email = QLineEdit(candidate.contact_email or "")
        actor = QLineEdit(candidate.actor or "")
        action = QLineEdit(candidate.action or "")
        object_value = QLineEdit(candidate.object or "")
        beneficiary = QLineEdit(candidate.beneficiary or "")
        deadline_owner = QLineEdit(candidate.deadline_owner or "")
        condition = QLineEdit(candidate.condition or "")
        responsibility = QLineEdit(candidate.responsibility)
        event_id = QLineEdit(candidate.event_id or "")
        event_id.setReadOnly(True)
        source_span = QTextEdit(candidate.source_span or candidate.evidence)
        source_span.setReadOnly(True)
        source_span.setMaximumHeight(80)
        due = QLineEdit(candidate.due_at.isoformat() if candidate.due_at else "")
        reminder = QLineEdit(candidate.reminder_at.isoformat() if candidate.reminder_at else "")
        kind = QComboBox()
        for value in CommitmentType:
            kind.addItem(value.value, value)
        kind.setCurrentIndex(max(0, list(CommitmentType).index(candidate.type)))
        confirm = QCheckBox("I confirm these extracted details")
        confirm.setChecked(not candidate.needs_confirmation)
        fields.update(
            title=title,
            description=description,
            person=person,
            email=email,
            actor=actor,
            action=action,
            object=object_value,
            beneficiary=beneficiary,
            deadline_owner=deadline_owner,
            condition=condition,
            responsibility=responsibility,
            event_id=event_id,
            source_span=source_span,
            due=due,
            reminder=reminder,
            kind=kind,
            confirm=confirm,
        )
        form.addRow("Title", title)
        form.addRow("Description", description)
        form.addRow("Type", kind)
        form.addRow("Person / organisation", person)
        form.addRow("Email", email)
        form.addRow("Event ID", event_id)
        form.addRow("Actor", actor)
        form.addRow("Action", action)
        form.addRow("Object", object_value)
        form.addRow("Beneficiary", beneficiary)
        form.addRow("Deadline owner", deadline_owner)
        form.addRow("Condition", condition)
        form.addRow("Responsibility", responsibility)
        form.addRow("Source span", source_span)
        form.addRow("Deadline (ISO or natural date)", due)
        form.addRow("Reminder (ISO or natural date)", reminder)
        form.addRow("", confirm)
        self.forms.append(fields)
        return page

    def _read_values(self) -> list[CommitmentCandidate]:
        values: list[CommitmentCandidate] = []
        for fields, original in zip(self.forms, self._capture_result.candidates, strict=True):
            confirm = fields["confirm"]
            assert isinstance(confirm, QCheckBox)
            kind = fields["kind"]
            assert isinstance(kind, QComboBox)
            title = fields["title"]
            description = fields["description"]
            person = fields["person"]
            email = fields["email"]
            actor = fields["actor"]
            action = fields["action"]
            object_value = fields["object"]
            beneficiary = fields["beneficiary"]
            deadline_owner = fields["deadline_owner"]
            condition = fields["condition"]
            responsibility = fields["responsibility"]
            event_id = fields["event_id"]
            source_span = fields["source_span"]
            due = fields["due"]
            reminder = fields["reminder"]
            assert isinstance(title, QLineEdit)
            assert isinstance(description, QTextEdit)
            assert isinstance(person, QLineEdit)
            assert isinstance(email, QLineEdit)
            assert isinstance(actor, QLineEdit)
            assert isinstance(action, QLineEdit)
            assert isinstance(object_value, QLineEdit)
            assert isinstance(beneficiary, QLineEdit)
            assert isinstance(deadline_owner, QLineEdit)
            assert isinstance(condition, QLineEdit)
            assert isinstance(responsibility, QLineEdit)
            assert isinstance(event_id, QLineEdit)
            assert isinstance(source_span, QTextEdit)
            responsibility_value = responsibility.text().strip()
            allowed_responsibilities = {
                "USER_PERFORMS",
                "OTHER_PARTY_PERFORMS",
                "USER_WAITING_FOR",
                "USER_CONTACTS",
                "CONDITIONALLY_EXECUTES",
                "UNKNOWN",
            }
            if responsibility_value not in allowed_responsibilities:
                responsibility_value = "UNKNOWN"
            assert isinstance(due, QLineEdit)
            assert isinstance(reminder, QLineEdit)
            values.append(
                CommitmentCandidate(
                    title=title.text().strip(),
                    description=description.toPlainText().strip(),
                    type=kind.currentData(),
                    person=person.text().strip() or None,
                    contact_email=email.text().strip() or None,
                    actor=actor.text().strip() or None,
                    action=action.text().strip() or None,
                    object=object_value.text().strip() or None,
                    beneficiary=beneficiary.text().strip() or None,
                    deadline_owner=deadline_owner.text().strip() or None,
                    condition=condition.text().strip() or None,
                    responsibility=cast(
                        Literal[
                            "USER_PERFORMS",
                            "OTHER_PARTY_PERFORMS",
                            "USER_WAITING_FOR",
                            "USER_CONTACTS",
                            "CONDITIONALLY_EXECUTES",
                            "UNKNOWN",
                        ],
                        responsibility_value,
                    ),
                    event_id=event_id.text().strip() or None,
                    source_span=source_span.toPlainText().strip(),
                    due_at=self._parse_datetime(due.text()),
                    timezone=original.timezone,
                    reminder_at=self._parse_datetime(reminder.text()),
                    confidence=original.confidence,
                    needs_confirmation=not confirm.isChecked(),
                    evidence=original.evidence,
                )
            )
        return values

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        cleaned = value.strip()
        if not cleaned:
            return None
        return date_parser.parse(cleaned)

    def _validate_and_accept(self) -> None:
        try:
            self._values = self._read_values()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Check the commitment", f"One of the fields is invalid: {exc}")
            return
        self.accept()

    def candidates(self) -> list[CommitmentCandidate]:
        return self._values


class PactlynWindow(QMainWindow):
    def __init__(self, container: AppContainer):
        super().__init__()
        self.container = container
        self.setWindowTitle("Pactlyn — Remember what matters")
        self.resize(1180, 760)
        self.theme_mode: ThemeMode = get_saved_theme()
        icon = QIcon(str(Path(__file__).with_name("pactlyn.svg")))
        self.setWindowIcon(icon)
        self.pages = QStackedWidget()
        self.nav: list[QPushButton] = []
        self.capture_worker: CaptureWorker | None = None
        self.persistence_worker: CapturePersistenceWorker | None = None
        self.assistant_worker: AssistantWorker | None = None
        self.email_worker: EmailQueueWorker | None = None
        self.email_sync_worker: EmailSyncWorker | None = None
        self.connectivity = ConnectivityMonitor()
        self.connectivity_worker: ConnectivityWorker | None = None
        self._shutdown_complete = False
        root = QWidget()
        root.setObjectName("central_widget")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._sidebar())
        root_layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)
        self._add_pages()
        self.apply_theme(self.theme_mode)
        self._setup_tray()
        self._refresh()
        timer = QTimer(self)
        timer.timeout.connect(self._evaluate_reminders)
        timer.start(60_000)
        self._timer = timer
        connectivity_timer = QTimer(self)
        connectivity_timer.timeout.connect(self._probe_connectivity)
        connectivity_timer.start(300_000)
        self._connectivity_timer = connectivity_timer
        inbound_timer = QTimer(self)
        inbound_timer.timeout.connect(self._maybe_auto_sync)
        inbound_timer.start(60_000)
        self._inbound_timer = inbound_timer
        QTimer.singleShot(100, self._probe_connectivity)
        QTimer.singleShot(5_000, self._maybe_auto_sync)

    def apply_theme(self, mode: ThemeMode) -> None:
        self.theme_mode = mode
        save_theme(mode)
        self.setStyleSheet(get_stylesheet(mode))
        if hasattr(self, "brand_widget"):
            self.brand_widget.set_mode(mode)
        if hasattr(self, "theme_combo"):
            idx = 1 if mode == "dark" else 0
            if self.theme_combo.currentIndex() != idx:
                self.theme_combo.blockSignals(True)
                self.theme_combo.setCurrentIndex(idx)
                self.theme_combo.blockSignals(False)
        if hasattr(self, "email_settings_page"):
            self.email_settings_page.set_theme(mode)
        self._refresh()

    def _on_theme_combo_changed(self, index: int) -> None:
        mode = cast(ThemeMode, self.theme_combo.itemData(index))
        if mode and mode != self.theme_mode:
            self.apply_theme(mode)

    def _sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 14, 12, 16)
        layout.setSpacing(4)
        self.brand_widget = BrandWidget(self.theme_mode)
        layout.addWidget(self.brand_widget)
        layout.addSpacing(6)
        layout.addWidget(self._nav_button("⌂   Home", 0))
        layout.addWidget(self._nav_button("✓   Commitments", 1))
        layout.addWidget(self._nav_button("◷   Waiting For", 2))
        layout.addWidget(self._nav_button("✉   Email Centre", 3))
        layout.addWidget(self._nav_button("▣   Memory", 4))
        layout.addWidget(self._nav_button("✦   Assistant", 5))
        layout.addStretch()
        layout.addWidget(self._nav_button("⚙   Settings", 6))
        return sidebar

    def _nav_button(self, label: str, index: int) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("nav")
        button.setCheckable(True)
        button.clicked.connect(lambda: self._navigate(index))
        self.nav.append(button)
        return button

    def _add_pages(self) -> None:
        self.pages.addWidget(self._home_page())
        self.pages.addWidget(self._commitments_page())
        self.pages.addWidget(self._waiting_page())
        self.pages.addWidget(self._email_page())
        self.pages.addWidget(self._memory_page())
        self.pages.addWidget(self._assistant_page())
        self.pages.addWidget(self._settings_page())
        self._navigate(0)

    def _header(self, title: str, subtitle: str) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("title")
        layout.addWidget(title_label)
        muted = QLabel(subtitle)
        muted.setObjectName("muted")
        layout.addWidget(muted)
        return layout

    def _home_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(28, 24, 28, 24)
        page_layout.setSpacing(16)

        hour = datetime.now().hour
        greeting = (
            "Good morning"
            if hour < 12
            else ("Good afternoon" if hour < 18 else "Good evening")
        )
        page_layout.addLayout(
            self._header(greeting, "Pactlyn keeps the promises you make to yourself and others.")
        )

        quick_card = QFrame()
        quick_card.setObjectName("card")
        quick_layout = QHBoxLayout(quick_card)
        quick_layout.setContentsMargins(14, 10, 14, 10)
        quick_layout.setSpacing(10)
        self.quick_capture = QLineEdit()
        self.quick_capture.setPlaceholderText(
            "What would you like Pactlyn to remember? (Type and press Enter)"
        )
        self.quick_capture.returnPressed.connect(lambda: self._capture(self.quick_capture.text()))
        quick_layout.addWidget(self.quick_capture, 1)
        capture = QPushButton("✦  Capture")
        capture.setObjectName("primary")
        capture.clicked.connect(lambda: self._capture(self.quick_capture.text()))
        quick_layout.addWidget(capture)
        page_layout.addWidget(quick_card)

        # KPI metric cards row
        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(14)

        self.card_active = QFrame()
        self.card_active.setObjectName("metric_card")
        active_l = QVBoxLayout(self.card_active)
        active_l.setContentsMargins(16, 12, 16, 12)
        active_l.setSpacing(2)
        self.stat_active_num = QLabel("0")
        self.stat_active_num.setStyleSheet(
            f"font-size: 26px; font-weight: 800; color: {COLOR_TERRACOTTA};"
        )
        active_l.addWidget(self.stat_active_num)
        lbl_act = QLabel("Active Commitments")
        lbl_act.setObjectName("muted")
        active_l.addWidget(lbl_act)
        metrics_layout.addWidget(self.card_active, 1)

        self.card_overdue = QFrame()
        self.card_overdue.setObjectName("metric_card")
        overdue_l = QVBoxLayout(self.card_overdue)
        overdue_l.setContentsMargins(16, 12, 16, 12)
        overdue_l.setSpacing(2)
        self.stat_overdue_num = QLabel("0")
        self.stat_overdue_num.setStyleSheet(
            f"font-size: 26px; font-weight: 800; color: {status_color('error', self.theme_mode)};"
        )
        overdue_l.addWidget(self.stat_overdue_num)
        lbl_od = QLabel("Overdue / Attention")
        lbl_od.setObjectName("muted")
        overdue_l.addWidget(lbl_od)
        metrics_layout.addWidget(self.card_overdue, 1)

        self.card_waiting = QFrame()
        self.card_waiting.setObjectName("metric_card")
        waiting_l = QVBoxLayout(self.card_waiting)
        waiting_l.setContentsMargins(16, 12, 16, 12)
        waiting_l.setSpacing(2)
        self.stat_waiting_num = QLabel("0")
        self.stat_waiting_num.setStyleSheet(
            f"font-size: 26px; font-weight: 800; color: {status_color('info', self.theme_mode)};"
        )
        waiting_l.addWidget(self.stat_waiting_num)
        lbl_wt = QLabel("Waiting For Others")
        lbl_wt.setObjectName("muted")
        waiting_l.addWidget(lbl_wt)
        metrics_layout.addWidget(self.card_waiting, 1)

        page_layout.addLayout(metrics_layout)

        # Status and connectivity
        status_row = QHBoxLayout()
        self.home_summary = QLabel()
        self.home_summary.setWordWrap(True)
        self.home_summary.setObjectName("muted")
        status_row.addWidget(self.home_summary, 1)
        self.connectivity_label = QLabel("● Connectivity: checking…")
        self.connectivity_label.setObjectName("muted")
        status_row.addWidget(self.connectivity_label)
        page_layout.addLayout(status_row)

        sec1 = QLabel("✦  Suggested Next Actions")
        sec1.setStyleSheet("font-weight: 600; font-size: 14px;")
        page_layout.addWidget(sec1)
        self.home_recommendations = QListWidget()
        self.home_recommendations.setMaximumHeight(110)
        page_layout.addWidget(self.home_recommendations)

        sec2 = QLabel("✓  Recent Commitments")
        sec2.setStyleSheet("font-weight: 600; font-size: 14px;")
        page_layout.addWidget(sec2)
        self.home_list = QListWidget()
        page_layout.addWidget(self.home_list, 1)

        page.setLayout(page_layout)
        return page

    def _commitments_page(self) -> QWidget:
        page = QWidget()
        layout = self._header("Commitments", "Every item stays local until you choose an external service.")
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        actions = QHBoxLayout()
        add = QPushButton("+ New commitment")
        add.setObjectName("primary")
        add.clicked.connect(lambda: self._capture())
        actions.addWidget(add)
        actions.addStretch()
        layout.addLayout(actions)
        filters = QHBoxLayout()
        self.commitment_search = QLineEdit()
        self.commitment_search.setPlaceholderText("Search commitments")
        self.commitment_search.textChanged.connect(self._refresh)
        filters.addWidget(self.commitment_search, 1)
        self.commitment_filter = QComboBox()
        self.commitment_filter.addItem("All statuses", None)
        for status in CommitmentStatus:
            self.commitment_filter.addItem(status.value.replace("_", " ").title(), status)
        self.commitment_filter.currentIndexChanged.connect(self._refresh)
        filters.addWidget(self.commitment_filter)
        layout.addLayout(filters)
        controls = QHBoxLayout()
        for label, handler in (
            ("Edit", self._edit_selected),
            ("Complete", self._complete_selected),
            ("Postpone", self._postpone_selected),
            ("Snooze", self._snooze_selected),
            ("Cancel", self._cancel_selected),
            ("History", self._history_selected),
        ):
            button = QPushButton(label)
            button.setObjectName("secondary")
            button.clicked.connect(handler)
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)
        self.commitment_list = QListWidget()
        self.commitment_list.currentItemChanged.connect(lambda _current, _previous: self._refresh_related())
        self.commitment_list.itemDoubleClicked.connect(lambda _item: self._complete_selected())
        tip = QLabel("💡 Tip: Double-click an item to mark it complete.")
        tip.setObjectName("muted")
        layout.addWidget(tip)
        layout.addWidget(self.commitment_list, 1)
        layout.addWidget(QLabel("Related commitments"))
        self.related_commitment_list = QListWidget()
        self.related_commitment_list.setMaximumHeight(120)
        layout.addWidget(self.related_commitment_list)
        page.setLayout(layout)
        return page

    def _waiting_page(self) -> QWidget:
        page = QWidget()
        layout = self._header("Waiting For", "Responses and hand-offs that deserve a gentle follow-up.")
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        self.waiting_list = QListWidget()
        layout.addWidget(self.waiting_list, 1)
        page.setLayout(layout)
        return page

    def _email_page(self) -> QWidget:
        page = QWidget()
        layout = self._header("Email Centre", "Drafts need explicit approval before they can enter the delivery queue.")
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        self.email_status = QLabel()
        self.email_status.setObjectName("muted")
        layout.addWidget(self.email_status)
        controls = QHBoxLayout()
        for label, handler in (
            ("+ New draft", self._new_email),
            ("Reply", self._reply_to_selected_thread),
            ("Edit", self._edit_email),
            ("Approve", self._approve_email),
            ("Send queue", self._send_email),
            ("Retry failed", self._retry_email),
            ("Cancel", self._cancel_email),
            ("Sync incoming", lambda: self._sync_email()),
        ):
            button = QPushButton(label)
            button.setObjectName("primary" if label in {"+ New draft", "Approve", "Send queue"} else "secondary")
            button.clicked.connect(handler)
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)
        self.email_list = QListWidget()
        self.email_list.itemDoubleClicked.connect(lambda _item: self._edit_email())
        layout.addWidget(self.email_list, 1)
        layout.addWidget(QLabel("Conversations"))
        self.email_thread_list = QListWidget()
        self.email_thread_list.itemDoubleClicked.connect(self._show_email_thread)
        layout.addWidget(self.email_thread_list, 1)
        page.setLayout(layout)
        return page

    def _memory_page(self) -> QWidget:
        page = QWidget()
        layout = self._header("Memory", "Pactlyn keeps provenance with every remembered fact.")
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        self.memory_list = QListWidget()
        layout.addWidget(self.memory_list, 1)
        page.setLayout(layout)
        return page

    def _assistant_page(self) -> QWidget:
        page = QWidget()
        layout = self._header("Assistant", "Ask about what is due, waiting, or worth doing next.")
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        self.assistant_input = QTextEdit()
        self.assistant_input.setPlaceholderText("Capture a commitment or ask: What am I waiting for?")
        layout.addWidget(self.assistant_input)
        controls = QHBoxLayout()
        send = QPushButton("Remember this")
        send.setObjectName("primary")
        send.clicked.connect(lambda: self._capture(self.assistant_input.toPlainText()))
        controls.addWidget(send)
        ask = QPushButton("Ask local context")
        ask.setObjectName("secondary")
        ask.clicked.connect(self._ask_assistant)
        controls.addWidget(ask)
        controls.addStretch()
        layout.addLayout(controls)
        self.assistant_output = QTextEdit()
        self.assistant_output.setReadOnly(True)
        self.assistant_output.setPlaceholderText("Grounded answers cite local source records here.")
        layout.addWidget(self.assistant_output, 1)
        page.setLayout(layout)
        return page

    def _settings_page(self) -> QWidget:
        page = QWidget()
        layout = self._header(
            "Settings",
            "Local-first by default. Provider credentials are kept in the OS credential store.",
        )
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        tabs = QTabWidget()
        general = QWidget()
        general_layout = QVBoxLayout(general)
        general_layout.setSpacing(14)

        # Appearance & Theme
        appearance_group = QGroupBox("Appearance")
        appearance_form = QFormLayout(appearance_group)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("☀️  Light Theme (Warm Sand & Forest Pine)", "light")
        self.theme_combo.addItem("🌙  Dark Theme (Midnight Obsidian Pine & Terracotta)", "dark")
        self.theme_combo.setCurrentIndex(1 if self.theme_mode == "dark" else 0)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        appearance_form.addRow("Color Theme:", self.theme_combo)
        general_layout.addWidget(appearance_group)

        general_layout.addWidget(
            QLabel(f"Data directory: {self.container.settings.expanded_data_dir()}")
        )
        general_layout.addWidget(QLabel(f"Ollama endpoint: {self.container.settings.ollama_url}"))
        provider = QLabel(
            "Local model: Ollama (connection is checked when AI is used)\n"
            "Cloud model: disabled unless explicitly configured"
        )
        provider.setObjectName("muted")
        general_layout.addWidget(provider)
        self.autostart = QCheckBox("Start Pactlyn in the system tray when I log in")
        autostart = LinuxAutostart()
        self.autostart.setChecked(autostart.enabled())
        self.autostart.toggled.connect(lambda enabled: self._set_autostart(autostart, enabled))
        general_layout.addWidget(self.autostart)
        backup_row = QHBoxLayout()
        backup = QPushButton("Create backup")
        backup.setObjectName("secondary")
        backup.clicked.connect(self._create_backup)
        restore = QPushButton("Restore backup")
        restore.setObjectName("secondary")
        restore.clicked.connect(self._restore_backup)
        backup_row.addWidget(backup)
        backup_row.addWidget(restore)
        backup_row.addStretch()
        general_layout.addLayout(backup_row)
        general_layout.addStretch()
        tabs.addTab(general, "General")
        self.email_settings_page = EmailSettingsPage(self.container)
        self.email_settings_page.settingsSaved.connect(self._email_settings_saved)
        self.email_settings_page.syncRequested.connect(self._sync_email)
        tabs.addTab(self.email_settings_page, "Email")
        layout.addWidget(tabs, 1)
        page.setLayout(layout)
        return page

    def _set_autostart(self, autostart: LinuxAutostart, enabled: bool) -> None:
        try:
            if enabled:
                autostart.enable()
            else:
                autostart.disable()
        except OSError as exc:
            QMessageBox.warning(self, "Autostart", str(exc))

    def _create_backup(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        destination, _ = QFileDialog.getSaveFileName(self, "Create Pactlyn backup", "pactlyn.pactlyn", "Pactlyn backup (*.pactlyn)")
        if not destination:
            return
        password, accepted = QInputDialog.getText(self, "Encrypt backup", "Backup password (leave empty for a private unencrypted archive):", QLineEdit.EchoMode.Password)
        if not accepted:
            return
        try:
            BackupService(self.container.settings.expanded_data_dir()).create(Path(destination), password=password or None)
            QMessageBox.information(self, "Backup created", destination)
        except (BackupError, OSError) as exc:
            QMessageBox.warning(self, "Backup failed", str(exc))

    def _restore_backup(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        source, _ = QFileDialog.getOpenFileName(self, "Restore Pactlyn backup", "", "Pactlyn backup (*.pactlyn *.zip)")
        if not source:
            return
        password, accepted = QInputDialog.getText(self, "Decrypt backup", "Backup password (if encrypted):", QLineEdit.EchoMode.Password)
        if not accepted:
            return
        try:
            BackupService(self.container.settings.expanded_data_dir()).restore(Path(source), password=password or None)
            QMessageBox.information(self, "Backup restored", "Restart Pactlyn to reopen the restored database and vector index.")
        except (BackupError, OSError) as exc:
            QMessageBox.warning(self, "Restore failed", str(exc))

    def _navigate(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for current, button in enumerate(self.nav):
            button.setChecked(current == index)
        if index == 6 and hasattr(self, "email_settings_page"):
            self.email_settings_page.refresh()
        self._refresh()

    def _capture(self, initial: str = "") -> None:
        if initial.strip():
            text = initial.strip()
        else:
            dialog = CaptureDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            text = dialog.text.toPlainText().strip()
        if not text:
            return
        self._start_capture(text)

    def _start_capture(self, text: str) -> None:
        if self.capture_worker and self.capture_worker.isRunning():
            return
        self._set_capture_busy(True)
        session = self.container.session()
        try:
            context = self.container.capture_context(session, text)
        finally:
            session.close()
        worker = CaptureWorker(self.container, text, context)
        worker.finished.connect(lambda result: self._capture_finished(text, result))
        worker.failed.connect(self._capture_failed)
        worker.finished.connect(lambda _result: self._capture_worker_done(worker))
        worker.failed.connect(lambda _error: self._capture_worker_done(worker))
        self.capture_worker = worker
        worker.start()

    def _capture_worker_done(self, worker: CaptureWorker) -> None:
        worker.deleteLater()
        if self.capture_worker is worker:
            self.capture_worker = None
        if self.persistence_worker is None:
            self._set_capture_busy(False)

    def _set_capture_busy(self, busy: bool) -> None:
        self.quick_capture.setEnabled(not busy)
        self.assistant_input.setEnabled(not busy)
        if busy:
            self.home_summary.setText("Pactlyn is asking the configured local model to understand this capture…")

    def _probe_connectivity(self) -> None:
        if self.connectivity_worker and self.connectivity_worker.isRunning():
            return
        worker = ConnectivityWorker(self.connectivity)
        worker.finished.connect(lambda state: self._connectivity_finished(worker, state))
        self.connectivity_worker = worker
        worker.start()

    def _connectivity_finished(self, worker: ConnectivityWorker, state: ConnectivityState) -> None:
        was_offline = self.connectivity.state == ConnectivityState.OFFLINE
        dot = "● " if state == ConnectivityState.ONLINE else "○ "
        self.connectivity_label.setText(f"{dot}Connectivity: {state.value}")
        worker.deleteLater()
        if self.connectivity_worker is worker:
            self.connectivity_worker = None
        if was_offline and state == ConnectivityState.ONLINE and self.container.email_provider:
            self._send_email()
            self._sync_email()

    def _capture_failed(self, error: str) -> None:
        QMessageBox.critical(self, "Capture failed", f"The local model workflow failed:\n\n{error}")

    def _ask_assistant(self) -> None:
        question = self.assistant_input.toPlainText().strip()
        if not question or (self.assistant_worker and self.assistant_worker.isRunning()):
            return
        self.assistant_output.setPlainText("Searching local memory and commitments…")
        worker = AssistantWorker(self.container, question)
        worker.finished.connect(lambda answer: self._assistant_finished(worker, answer))
        worker.failed.connect(lambda error: self._assistant_failed(worker, error))
        self.assistant_worker = worker
        worker.start()

    def _assistant_finished(self, worker: AssistantWorker, answer: Any) -> None:
        evidence = "\n\nSources:\n" + "\n".join(
            f"- {item.source_type}/{item.source_id}" for item in answer.evidence
        ) if answer.evidence else ""
        self.assistant_output.setPlainText(answer.answer + evidence)
        worker.deleteLater()
        if self.assistant_worker is worker:
            self.assistant_worker = None

    def _assistant_failed(self, worker: AssistantWorker, error: str) -> None:
        self.assistant_output.setPlainText(f"Local assistant unavailable: {error}")
        worker.deleteLater()
        if self.assistant_worker is worker:
            self.assistant_worker = None

    def _capture_finished(self, text: str, result: CaptureResult) -> None:
        if not result.candidates:
            response = QMessageBox.question(
                self,
                "Local model unavailable",
                f"{result.explanation}\n\nUse the clearly labelled offline extraction instead? It will still require review.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if response == QMessageBox.StandardButton.Yes:
                fallback = CommitmentExtractor().extract(
                    text,
                    timezone_name=self.container.settings.default_timezone,
                    now=self.container.clock(),
                )
                fallback.used_fallback = True
                fallback.provider_error = result.provider_error
                fallback.explanation = f"Explicit offline fallback after model failure: {fallback.explanation}"
                self._capture_finished(text, fallback)
            return
        dialog = CommitmentReviewDialog(self, result)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._set_capture_busy(True)
        worker = CapturePersistenceWorker(
            self.container,
            dialog.candidates(),
            result.relationships,
            result.rejected_relationships,
            "ollama" if result.used_local_model else "offline_fallback",
        )
        worker.finished.connect(lambda _ids: self._capture_persisted(worker, text))
        worker.failed.connect(lambda error: self._capture_persist_failed(worker, error))
        self.persistence_worker = worker
        worker.start()

    def _capture_persisted(self, worker: CapturePersistenceWorker, _text: str) -> None:
        worker.deleteLater()
        if self.persistence_worker is worker:
            self.persistence_worker = None
        self.quick_capture.clear()
        self.assistant_input.clear()
        self._set_capture_busy(False)
        self._refresh()

    def _capture_persist_failed(self, worker: CapturePersistenceWorker, error: str) -> None:
        self._capture_persisted(worker, "")
        QMessageBox.critical(self, "Could not save", f"No commitment was saved:\n\n{error}")

    def _refresh(self) -> None:
        session = self.container.session()
        try:
            status = self.commitment_filter.currentData() if hasattr(self, "commitment_filter") else None
            query = self.commitment_search.text() if hasattr(self, "commitment_search") else ""
            commitments = self.container.commitments(session).search(query, status=status)
            active = [item for item in commitments if item.status not in {CommitmentStatus.COMPLETED, CommitmentStatus.CANCELLED}]
            if hasattr(self, "home_summary"):
                overdue = sum(item.status == CommitmentStatus.OVERDUE for item in active)
                waiting = sum(item.status == CommitmentStatus.WAITING for item in active)
                if hasattr(self, "stat_active_num"):
                    self.stat_active_num.setText(str(len(active)))
                if hasattr(self, "stat_overdue_num"):
                    self.stat_overdue_num.setText(str(overdue))
                    err_col = status_color("error", self.theme_mode)
                    muted_col = status_color("muted", self.theme_mode)
                    self.stat_overdue_num.setStyleSheet(
                        f"font-size: 26px; font-weight: 800; color: {err_col if overdue > 0 else muted_col};"
                    )
                if hasattr(self, "stat_waiting_num"):
                    self.stat_waiting_num.setText(str(waiting))
                    info_col = status_color("info", self.theme_mode)
                    muted_col = status_color("muted", self.theme_mode)
                    self.stat_waiting_num.setStyleSheet(
                        f"font-size: 26px; font-weight: 800; color: {info_col if waiting > 0 else muted_col};"
                    )
                self.home_summary.setText(f"{len(active)} active commitments  ·  {overdue} overdue  ·  {waiting} waiting for a response")
                self.home_recommendations.clear()
                for suggestion in RecommendationEngine(session).recommend(limit=5):
                    self.home_recommendations.addItem(f"{suggestion.title} — {suggestion.explanation}")
                self.home_list.clear()
                for item in active[:10]:
                    self.home_list.addItem(self._commitment_text(item))
            if hasattr(self, "commitment_list"):
                self.commitment_list.clear()
                for item in commitments:
                    list_item = self._list_item(item)
                    self.commitment_list.addItem(list_item)
                if hasattr(self, "related_commitment_list"):
                    self._refresh_related(session)
            if hasattr(self, "waiting_list"):
                self.waiting_list.clear()
                for item in commitments:
                    if item.status == CommitmentStatus.WAITING or item.type.value == "waiting_for":
                        self.waiting_list.addItem(self._commitment_text(item))
            if hasattr(self, "email_list"):
                actions = self.container.email(session).list_actions()
                self.email_list.clear()
                for action in actions:
                    email_item = QListWidgetItem(self._email_text(action))
                    email_item.setData(Qt.ItemDataRole.UserRole, action.id)
                    self.email_list.addItem(email_item)
                preferences = self.container.effective_email_settings()
                if self.container.email_provider and preferences.sender_email:
                    self.email_status.setText(
                        f"Resend configured for {preferences.sender}. "
                        "Approved messages can be sent."
                    )
                elif self.container.email_provider:
                    self.email_status.setText(
                        "A Resend API key is saved, but no verified sender is configured. "
                        "Complete Settings → Email before sending."
                    )
                else:
                    self.email_status.setText(
                        "Resend is not configured. Drafts remain local and approved "
                        "messages stay queued."
                    )
                self.email_thread_list.clear()
                threads = list(
                    session.scalars(
                        select(EmailThread)
                        .order_by(EmailThread.created_at.desc())
                        .limit(100)
                    )
                )
                for thread in threads:
                    review = " · needs review" if thread.needs_review else ""
                    thread_item = QListWidgetItem(
                        f"{thread.subject or '(no subject)'} · {len(thread.messages)} messages{review}"
                    )
                    thread_item.setData(Qt.ItemDataRole.UserRole, thread.id)
                    self.email_thread_list.addItem(thread_item)
            if hasattr(self, "memory_list"):
                self.memory_list.clear()
                for memory in self.container.memories(session).list()[:50]:
                    self.memory_list.addItem(f"{memory.kind.value} · {memory.content} · source: {memory.source_type}/{memory.source_id}")
        finally:
            session.close()

    @staticmethod
    def _commitment_text(item: Any) -> str:
        due = f" · due {item.due_at.astimezone().strftime('%d %b')}" if item.due_at else ""
        return f"[{item.status.value}] {item.title}{due}"

    @staticmethod
    def _list_item(item: Any) -> QListWidgetItem:
        list_item = QListWidgetItem(PactlynWindow._commitment_text(item))
        list_item.setData(Qt.ItemDataRole.UserRole, item.id)
        return list_item

    def _selected_commitment_id(self) -> str | None:
        item = self.commitment_list.currentItem()
        if not item:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def _refresh_related(self, session: Any | None = None) -> None:
        if not hasattr(self, "related_commitment_list"):
            return
        owns_session = session is None
        session = session or self.container.session()
        try:
            self.related_commitment_list.clear()
            commitment_id = self._selected_commitment_id()
            if not commitment_id:
                return
            for relation, related in self.container.commitments(session).related(commitment_id):
                self.related_commitment_list.addItem(
                    f"{relation.relationship.value}: {related.title} [{related.status.value}]"
                )
        finally:
            if owns_session:
                session.close()

    @staticmethod
    def _email_text(action: EmailSendAction) -> str:
        recipients = ", ".join(action.recipients)
        error = f" — {action.last_error}" if action.last_error else ""
        return f"[{action.state.value}] {action.subject} → {recipients}{error}"

    def _selected_email_id(self) -> str | None:
        item = self.email_list.currentItem()
        if not item:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def _show_email_thread(self, item: QListWidgetItem) -> None:
        thread_id = item.data(Qt.ItemDataRole.UserRole)
        if not thread_id:
            return
        session = self.container.session()
        try:
            thread = session.get(EmailThread, str(thread_id))
            if not thread:
                return
            messages = "\n\n".join(
                f"From: {message.sender}\nTo: {', '.join(message.recipients)}\n"
                f"{message.received_at}\n\n{message.body_text}"
                for message in thread.messages
            )
            association = (
                f"\n\nAssociation confidence: {thread.association_confidence:.0%}"
                f"\nNeeds review: {'yes' if thread.needs_review else 'no'}"
            )
            subject = thread.subject
            needs_review = thread.needs_review
            commitment_id = thread.commitment_id
        finally:
            session.close()
        QMessageBox.information(self, subject or "Conversation", messages + association)
        if needs_review:
            self._review_thread_association(str(thread_id))
        elif commitment_id:
            session = self.container.session()
            try:
                commitment = self.container.commitments(session).get(commitment_id)
                response_received = commitment and commitment.status == CommitmentStatus.RESPONSE_RECEIVED
            finally:
                session.close()
            if response_received:
                outcome = QMessageBox.question(
                    self,
                    "Confirm outcome",
                    "This reply is associated with a waiting commitment. Did it resolve the commitment?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if outcome == QMessageBox.StandardButton.Yes:
                    session = self.container.session()
                    try:
                        self.container.commitments(session).complete(commitment_id)
                        session.commit()
                    finally:
                        session.close()
                    self._refresh()

    def _review_thread_association(self, thread_id: str) -> None:
        session = self.container.session()
        try:
            commitments = self.container.commitments(session).list(limit=200)
        finally:
            session.close()
        choices = ["Leave unassociated"] + [commitment.title for commitment in commitments]
        selected, accepted = QInputDialog.getItem(
            self,
            "Review incoming relationship",
            "Associate this untrusted incoming message with:",
            choices,
            0,
            False,
        )
        if not accepted:
            return
        session = self.container.session()
        try:
            thread = session.get(EmailThread, thread_id)
            if not thread:
                return
            if selected == choices[0]:
                thread.commitment_id = None
                thread.association_confidence = 0.0
            else:
                selected_commitment = next(
                    commitment for commitment in commitments if commitment.title == selected
                )
                thread.commitment_id = selected_commitment.id
                thread.association_confidence = 1.0
            thread.needs_review = False
            session.commit()
        finally:
            session.close()
        self._refresh()

    def _email_commitments(self, session: Any) -> list[Any]:
        return self.container.commitments(session).list(limit=200)

    @staticmethod
    def _email_contacts(session: Any) -> list[Contact]:
        return list(session.scalars(select(Contact).order_by(Contact.name)))

    def _require_email_ready(self) -> bool:
        preferences = self.container.effective_email_settings()
        if not preferences.sender_email:
            QMessageBox.information(
                self,
                "Email not configured",
                "Open Settings → Email and configure a verified Resend sender before "
                "drafting or sending email.",
            )
            self._navigate(6)
            return False
        if self.container.email_provider is None:
            self.container.refresh_email_provider()
        if self.container.email_provider is None:
            QMessageBox.information(
                self,
                "Resend API key missing",
                "Save a Resend API key in Settings → Email before sending. Drafts can "
                "still be created locally without a key.",
            )
        return True

    def _new_email(self) -> None:
        if not self._require_email_ready():
            return
        session = self.container.session()
        try:
            commitments = self._email_commitments(session)
            contacts = self._email_contacts(session)
            composer = self.container.email_composer(session)
            defaults = composer.defaults()
        finally:
            session.close()
        dialog = EmailDraftDialog(self, commitments, contacts, defaults=defaults)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        session = self.container.session()
        try:
            service = self.container.email(session)
            service.draft(**values)
            session.commit()
        finally:
            session.close()
        self._refresh()

    def _reply_to_selected_thread(self) -> None:
        item = self.email_thread_list.currentItem()
        if not item:
            QMessageBox.information(
                self, "Select a conversation", "Select a conversation to reply to."
            )
            return
        if not self._require_email_ready():
            return
        thread_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not thread_id:
            return
        session = self.container.session()
        try:
            thread = session.get(EmailThread, thread_id)
            if not thread:
                return
            preferences = self.container.effective_email_settings()
            sender_address = email_address(preferences.sender_email)
            inbound = [
                message
                for message in sorted(thread.messages, key=lambda item: item.received_at)
                if email_address(message.sender) != sender_address
            ]
            if not inbound:
                QMessageBox.information(
                    self,
                    "No reply target",
                    "This conversation has no inbound message to reply to.",
                )
                return
            defaults = self.container.email_composer(session).reply_defaults(inbound[-1])
            commitments = self._email_commitments(session)
            contacts = self._email_contacts(session)
        finally:
            session.close()
        dialog = EmailDraftDialog(self, commitments, contacts, defaults=defaults)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        session = self.container.session()
        try:
            self.container.email(session).draft(**values)
            session.commit()
        finally:
            session.close()
        self._refresh()

    def _edit_email(self) -> None:
        action_id = self._selected_email_id()
        if not action_id:
            return
        session = self.container.session()
        try:
            action = session.get(EmailSendAction, action_id)
            commitments = self._email_commitments(session)
            contacts = self._email_contacts(session)
            preferences = self.container.effective_email_settings()
            defaults = DraftDefaults(
                signature=preferences.signature, tone=preferences.tone.value
            )
        finally:
            session.close()
        if not action:
            return
        dialog = EmailDraftDialog(self, commitments, contacts, defaults=defaults, action=action)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        session = self.container.session()
        try:
            self.container.email(session).update_draft(
                action_id,
                sender=values["sender"],
                recipients=values["recipients"],
                cc=values["cc"],
                bcc=values["bcc"],
                reply_to=values["reply_to"],
                subject=values["subject"],
                body_text=values["body_text"],
                commitment_id=values["commitment_id"],
                headers=values["headers"],
                attachments=values["attachments"],
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            QMessageBox.warning(self, "Could not edit draft", str(exc))
        finally:
            session.close()
        self._refresh()

    def _approve_email(self) -> None:
        action_id = self._selected_email_id()
        if not action_id:
            return
        session = self.container.session()
        try:
            action = session.get(EmailSendAction, action_id)
            if not action:
                return
            if action.state in {EmailState.SENT, EmailState.DELIVERED, EmailState.CANCELLED}:
                QMessageBox.information(
                    self, "Cannot approve", "This email can no longer be approved."
                )
                return
            dialog = EmailApprovalDialog(self, action)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            approved = self.container.email(session).approve(action_id)
            QMessageBox.information(
                self,
                "Email approved",
                f"Approved exact payload for {', '.join(approved.recipients)}. It is now queued.",
            )
        except Exception as exc:
            session.rollback()
            QMessageBox.warning(self, "Could not approve", str(exc))
        finally:
            session.close()
        self._refresh()

    def _send_email(self) -> None:
        if self.email_worker and self.email_worker.isRunning():
            return
        preferences = self.container.effective_email_settings()
        if not self.container.email_provider or not preferences.sender_email:
            QMessageBox.information(
                self,
                "Resend unavailable",
                "Configure a Resend API key and verified sender in Settings → Email "
                "before sending.",
            )
            return
        worker = EmailQueueWorker(self.container)
        worker.finished.connect(lambda _result: self._email_worker_done(worker))
        worker.failed.connect(lambda error: self._email_worker_failed(worker, error))
        self.email_worker = worker
        worker.start()

    def _email_worker_done(self, worker: EmailQueueWorker) -> None:
        worker.deleteLater()
        if self.email_worker is worker:
            self.email_worker = None
        self._refresh()

    def _email_worker_failed(self, worker: EmailQueueWorker, error: str) -> None:
        self._email_worker_done(worker)
        QMessageBox.warning(self, "Email queue", error)

    def _retry_email(self) -> None:
        action_id = self._selected_email_id()
        if not action_id:
            return
        session = self.container.session()
        try:
            self.container.email(session).retry(action_id)
        except Exception as exc:
            session.rollback()
            QMessageBox.warning(self, "Could not retry", str(exc))
        finally:
            session.close()
        self._refresh()

    def _cancel_email(self) -> None:
        action_id = self._selected_email_id()
        if not action_id:
            return
        session = self.container.session()
        try:
            self.container.email(session).cancel(action_id)
        finally:
            session.close()
        self._refresh()

    def _email_settings_saved(self) -> None:
        self._refresh()
        if hasattr(self, "email_settings_page"):
            self.email_settings_page.refresh_status()

    def _sync_email(self, silent: bool = False) -> None:
        if self.email_sync_worker and self.email_sync_worker.isRunning():
            return
        preferences = self.container.effective_email_settings()
        if silent and not preferences.inbound_enabled:
            return
        if not self.container.email_provider:
            if not silent:
                QMessageBox.information(
                    self,
                    "Resend unavailable",
                    "Configure Resend before synchronising incoming mail.",
                )
            return
        if not preferences.receiving_email:
            if not silent:
                QMessageBox.information(
                    self,
                    "Receiving address missing",
                    "Configure a Resend receiving address in Settings → Email.",
                )
            return
        session = self.container.session()
        try:
            account_id = self.container.email_settings(session).account_id()
        finally:
            session.close()
        worker = EmailSyncWorker(
            self.container,
            account_id=account_id,
            receiving_address=preferences.receiving_email,
            silent=silent,
        )
        worker.finished.connect(lambda result: self._email_sync_done(worker, result))
        worker.failed.connect(lambda error: self._email_sync_failed(worker, error))
        self.email_sync_worker = worker
        worker.start()

    def _maybe_auto_sync(self) -> None:
        if self.email_sync_worker and self.email_sync_worker.isRunning():
            return
        preferences = self.container.effective_email_settings()
        if not preferences.inbound_enabled or not preferences.receiving_email:
            return
        if not self.container.email_provider:
            return
        session = self.container.session()
        try:
            last_sync = self.container.email_settings(session).last_synced_at()
        finally:
            session.close()
        if last_sync is not None:
            elapsed = (datetime.utcnow() - last_sync).total_seconds()
            if elapsed < preferences.sync_interval_minutes * 60:
                return
        self._sync_email(silent=True)

    def _email_sync_done(self, worker: EmailSyncWorker, result: object) -> None:
        worker.deleteLater()
        if self.email_sync_worker is worker:
            self.email_sync_worker = None
        if hasattr(self, "email_settings_page"):
            self.email_settings_page.refresh_status()
        self._refresh()
        if not worker.silent:
            count = result[0] if isinstance(result, tuple) and result else 0
            QMessageBox.information(
                self,
                "Incoming mail",
                f"Synchronised {count} new message{'s' if count != 1 else ''}.",
            )

    def _email_sync_failed(self, worker: EmailSyncWorker, error: str) -> None:
        worker.deleteLater()
        if self.email_sync_worker is worker:
            self.email_sync_worker = None
        if hasattr(self, "email_settings_page"):
            self.email_settings_page.refresh_status()
        self._refresh()
        if not worker.silent:
            QMessageBox.warning(self, "Incoming mail", error)

    def _complete_selected(self) -> None:
        commitment_id = self._selected_commitment_id()
        if not commitment_id:
            return
        session = self.container.session()
        try:
            self.container.commitments(session).complete(commitment_id)
            session.commit()
        finally:
            session.close()
        self._refresh()

    def _edit_selected(self) -> None:
        commitment_id = self._selected_commitment_id()
        if not commitment_id:
            return
        session = self.container.session()
        try:
            commitment = self.container.commitments(session).get(commitment_id)
            if not commitment:
                return
            candidate = CommitmentCandidate(
                title=commitment.title,
                description=commitment.description,
                type=commitment.type,
                person=commitment.person,
                contact_email=commitment.contact_email,
                due_at=commitment.due_at,
                timezone=commitment.timezone,
                reminder_at=commitment.reminder_at,
                confidence=commitment.confidence,
                needs_confirmation=commitment.needs_confirmation,
                evidence=commitment.evidence,
            )
        finally:
            session.close()
        dialog = CommitmentReviewDialog(self, CaptureResult(candidates=[candidate], explanation="Edit the saved commitment"))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edited = dialog.candidates()[0]
        session = self.container.session()
        try:
            self.container.commitments(session).update(
                commitment_id,
                title=edited.title,
                description=edited.description,
                person=edited.person,
                contact_email=edited.contact_email,
                due_at=edited.due_at,
                reminder_at=edited.reminder_at,
            )
            session.commit()
        finally:
            session.close()
        self._refresh()

    def _postpone_selected(self) -> None:
        self._reschedule_selected(postpone=True)

    def _snooze_selected(self) -> None:
        self._reschedule_selected(postpone=False)

    def _reschedule_selected(self, *, postpone: bool) -> None:
        commitment_id = self._selected_commitment_id()
        if not commitment_id:
            return
        value, accepted = QInputDialog.getText(
            self,
            "Postpone commitment" if postpone else "Snooze reminder",
            "Enter an ISO date/time (for example 2026-11-10T17:00+05:30):",
        )
        if not accepted or not value.strip():
            return
        try:
            due_at = CommitmentReviewDialog._parse_datetime(value)
            if due_at is None:
                raise ValueError("A date/time is required")
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid date", str(exc))
            return
        session = self.container.session()
        try:
            service = self.container.commitments(session)
            if postpone:
                service.postpone(commitment_id, due_at)
            else:
                service.snooze(commitment_id, due_at)
            session.commit()
        finally:
            session.close()
        self._refresh()

    def _cancel_selected(self) -> None:
        commitment_id = self._selected_commitment_id()
        if not commitment_id:
            return
        if QMessageBox.question(self, "Cancel commitment", "Cancel this commitment and dismiss its reminders?") != QMessageBox.StandardButton.Yes:
            return
        session = self.container.session()
        try:
            self.container.commitments(session).cancel(commitment_id)
            session.commit()
        finally:
            session.close()
        self._refresh()

    def _history_selected(self) -> None:
        commitment_id = self._selected_commitment_id()
        if not commitment_id:
            return
        session = self.container.session()
        try:
            commitment = self.container.commitments(session).get(commitment_id)
            if not commitment:
                return
            history = "\n".join(
                f"{event.created_at}: {event.event_type} — {event.detail}"
                for event in commitment.events
            ) or "No history yet."
        finally:
            session.close()
        QMessageBox.information(self, "Commitment history", history)

    def _evaluate_reminders(self) -> None:
        session = self.container.session()
        try:
            ReminderScheduler(
                session,
                lambda title, body: self._notify(title, body),
                timezone_name=self.container.settings.default_timezone,
                quiet_hours_start=self.container.settings.quiet_hours_start,
                quiet_hours_end=self.container.settings.quiet_hours_end,
            ).evaluate()
        finally:
            session.close()
        self._refresh()

    def _notify(self, title: str, body: str) -> None:
        if hasattr(self, "tray") and self.tray.supportsMessages():
            self.tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 5000)

    def _setup_tray(self) -> None:
        icon = QIcon(str(Path(__file__).with_name("pactlyn.svg")))
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        menu = self.tray.contextMenu()
        if menu is None:
            from PySide6.QtWidgets import QMenu
            menu = QMenu(self)
            show = QAction("Open Pactlyn", self)
            show.triggered.connect(self.showNormal)
            menu.addAction(show)
            menu.addSeparator()
            quit_action = QAction("Quit", self)
            quit_action.triggered.connect(QApplication.instance().quit)
            menu.addAction(quit_action)
            self.tray.setContextMenu(menu)
        self.tray.show()

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self.hide()
        event.ignore()

    def shutdown(self) -> None:
        if self._shutdown_complete:
            return
        if self.capture_worker and self.capture_worker.isRunning():
            self.capture_worker.quit()
            self.capture_worker.wait(2000)
        if self.email_worker and self.email_worker.isRunning():
            self.email_worker.quit()
            self.email_worker.wait(2000)
        if self.email_sync_worker and self.email_sync_worker.isRunning():
            self.email_sync_worker.quit()
            self.email_sync_worker.wait(2000)
        if self.connectivity_worker and self.connectivity_worker.isRunning():
            self.connectivity_worker.quit()
            self.connectivity_worker.wait(2000)
        if hasattr(self, "email_settings_page"):
            self.email_settings_page.shutdown()
        self._timer.stop()
        self._connectivity_timer.stop()
        self._inbound_timer.stop()
        self.tray.hide()
        self.container.vectors.close()
        self._shutdown_complete = True
