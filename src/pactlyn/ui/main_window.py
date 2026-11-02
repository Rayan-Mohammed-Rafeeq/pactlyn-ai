from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from dateutil import parser as date_parser
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
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
from pactlyn.core.commitments import CaptureResult, CommitmentCandidate, CommitmentExtractor
from pactlyn.core.connectivity import ConnectivityMonitor, ConnectivityState
from pactlyn.core.scheduler import ReminderScheduler
from pactlyn.email.inbound_sync import InboundEmailSync
from pactlyn.platform.linux.autostart import LinuxAutostart
from pactlyn.storage.backup import BackupError, BackupService
from pactlyn.storage.models import CommitmentStatus, CommitmentType, EmailSendAction, EmailThread

STYLE = """
QMainWindow, QWidget { background: #f7f8fc; color: #1d2433; font-family: Inter, sans-serif; }
QFrame#sidebar { background: #20283a; }
QLabel#brand { color: #ffffff; font-size: 24px; font-weight: 700; padding: 16px 12px; }
QPushButton#nav { color: #d9e0ef; background: transparent; text-align: left; border: 0; padding: 12px; border-radius: 7px; }
QPushButton#nav:hover, QPushButton#nav:checked { background: #36425b; color: white; }
QLabel#title { font-size: 28px; font-weight: 700; }
QLabel#muted { color: #68738a; }
QFrame#card { background: white; border: 1px solid #e4e8f1; border-radius: 10px; padding: 14px; }
QPushButton#primary { color: white; background: #5267df; border: 0; border-radius: 7px; padding: 10px 16px; font-weight: 600; }
QPushButton#secondary { color: #34405d; background: #e9ecf7; border: 0; border-radius: 7px; padding: 9px 14px; }
QLineEdit, QTextEdit { background: white; border: 1px solid #d9deeb; border-radius: 7px; padding: 9px; }
QListWidget { background: white; border: 1px solid #e4e8f1; border-radius: 8px; padding: 5px; }
"""


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

    def __init__(self, container: AppContainer):
        super().__init__()
        self.container = container

    def run(self) -> None:
        if not self.container.email_provider:
            self.failed.emit("Resend is not configured")
            return
        session = self.container.session()
        try:
            result = asyncio.run(InboundEmailSync(session, self.container.email_provider).sync())
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
        action: EmailSendAction | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit email draft" if action else "New email draft")
        self.resize(700, 620)
        layout = QFormLayout(self)
        self.email_sender = QLineEdit(action.sender if action else "")
        self.recipients = QLineEdit(", ".join(action.recipients) if action else "")
        self.cc = QLineEdit(", ".join(action.cc) if action else "")
        self.bcc = QLineEdit(", ".join(action.bcc) if action else "")
        self.reply_to = QLineEdit(action.reply_to or "" if action else "")
        self.subject = QLineEdit(action.subject if action else "")
        self.body = QTextEdit(action.body_text if action else "")
        self.body.setMinimumHeight(220)
        self.commitment = QComboBox()
        self.commitment.addItem("No related commitment", None)
        for commitment in commitments:
            self.commitment.addItem(commitment.title, commitment.id)
        if action and action.commitment_id:
            index = self.commitment.findData(action.commitment_id)
            if index >= 0:
                self.commitment.setCurrentIndex(index)
        layout.addRow("Sender", self.email_sender)
        layout.addRow("To (comma-separated)", self.recipients)
        layout.addRow("CC", self.cc)
        layout.addRow("BCC", self.bcc)
        layout.addRow("Reply-to", self.reply_to)
        layout.addRow("Subject", self.subject)
        layout.addRow("Related commitment", self.commitment)
        layout.addRow("Body", self.body)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    @staticmethod
    def _addresses(value: str) -> list[str]:
        return [address.strip() for address in value.split(",") if address.strip()]

    def values(self) -> dict[str, Any]:
        return {
            "sender": self.email_sender.text().strip(),
            "recipients": self._addresses(self.recipients.text()),
            "cc": self._addresses(self.cc.text()),
            "bcc": self._addresses(self.bcc.text()),
            "reply_to": self.reply_to.text().strip() or None,
            "subject": self.subject.text().strip(),
            "body_text": self.body.toPlainText(),
            "commitment_id": self.commitment.currentData(),
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
        self.accept()


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
        due = QLineEdit(candidate.due_at.isoformat() if candidate.due_at else "")
        reminder = QLineEdit(candidate.reminder_at.isoformat() if candidate.reminder_at else "")
        kind = QComboBox()
        for value in CommitmentType:
            kind.addItem(value.value, value)
        kind.setCurrentIndex(max(0, list(CommitmentType).index(candidate.type)))
        confirm = QCheckBox("I confirm these extracted details")
        confirm.setChecked(not candidate.needs_confirmation)
        fields.update(title=title, description=description, person=person, email=email, due=due, reminder=reminder, kind=kind, confirm=confirm)
        form.addRow("Title", title)
        form.addRow("Description", description)
        form.addRow("Type", kind)
        form.addRow("Person / organisation", person)
        form.addRow("Email", email)
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
            due = fields["due"]
            reminder = fields["reminder"]
            assert isinstance(title, QLineEdit)
            assert isinstance(description, QTextEdit)
            assert isinstance(person, QLineEdit)
            assert isinstance(email, QLineEdit)
            assert isinstance(due, QLineEdit)
            assert isinstance(reminder, QLineEdit)
            values.append(
                CommitmentCandidate(
                    title=title.text().strip(),
                    description=description.toPlainText().strip(),
                    type=kind.currentData(),
                    person=person.text().strip() or None,
                    contact_email=email.text().strip() or None,
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
        self.setStyleSheet(STYLE)
        self.pages = QStackedWidget()
        self.nav: list[QPushButton] = []
        self.capture_worker: CaptureWorker | None = None
        self.email_worker: EmailQueueWorker | None = None
        self.email_sync_worker: EmailSyncWorker | None = None
        self.connectivity = ConnectivityMonitor()
        self.connectivity_worker: ConnectivityWorker | None = None
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self._sidebar())
        root_layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)
        self._add_pages()
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
        QTimer.singleShot(100, self._probe_connectivity)

    def _sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        brand = QLabel("Pactlyn")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        layout.addWidget(self._nav_button("⌂  Home", 0))
        layout.addWidget(self._nav_button("✓  Commitments", 1))
        layout.addWidget(self._nav_button("◷  Waiting For", 2))
        layout.addWidget(self._nav_button("✉  Email Centre", 3))
        layout.addWidget(self._nav_button("▣  Memory", 4))
        layout.addWidget(self._nav_button("✦  Assistant", 5))
        layout.addStretch()
        layout.addWidget(self._nav_button("⚙  Settings", 6))
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
        title_label = QLabel(title)
        title_label.setObjectName("title")
        layout.addWidget(title_label)
        muted = QLabel(subtitle)
        muted.setObjectName("muted")
        layout.addWidget(muted)
        return layout

    def _home_page(self) -> QWidget:
        page = QWidget()
        layout = self._header("Good morning", "Pactlyn keeps the promises you make to yourself and others.")
        quick = QHBoxLayout()
        self.quick_capture = QLineEdit()
        self.quick_capture.setPlaceholderText("Quick capture — type a commitment and press Enter")
        self.quick_capture.returnPressed.connect(lambda: self._capture(self.quick_capture.text()))
        quick.addWidget(self.quick_capture, 1)
        capture = QPushButton("Capture")
        capture.setObjectName("primary")
        capture.clicked.connect(lambda: self._capture(self.quick_capture.text()))
        quick.addWidget(capture)
        layout.addLayout(quick)
        self.home_summary = QLabel()
        self.home_summary.setWordWrap(True)
        layout.addWidget(self.home_summary)
        self.connectivity_label = QLabel("Connectivity: checking…")
        self.connectivity_label.setObjectName("muted")
        layout.addWidget(self.connectivity_label)
        self.home_list = QListWidget()
        layout.addWidget(self.home_list, 1)
        page.setLayout(layout)
        return page

    def _commitments_page(self) -> QWidget:
        page = QWidget()
        layout = self._header("Commitments", "Every item stays local until you choose an external service.")
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
        self.commitment_list.itemDoubleClicked.connect(lambda _item: self._complete_selected())
        layout.addWidget(QLabel("Double-click an item to mark it complete."))
        layout.addWidget(self.commitment_list, 1)
        page.setLayout(layout)
        return page

    def _waiting_page(self) -> QWidget:
        page = QWidget()
        layout = self._header("Waiting For", "Responses and hand-offs that deserve a gentle follow-up.")
        self.waiting_list = QListWidget()
        layout.addWidget(self.waiting_list, 1)
        page.setLayout(layout)
        return page

    def _email_page(self) -> QWidget:
        page = QWidget()
        layout = self._header("Email Centre", "Drafts need explicit approval before they can enter the delivery queue.")
        self.email_status = QLabel()
        self.email_status.setObjectName("muted")
        layout.addWidget(self.email_status)
        controls = QHBoxLayout()
        for label, handler in (
            ("+ New draft", self._new_email),
            ("Edit", self._edit_email),
            ("Approve", self._approve_email),
            ("Send queue", self._send_email),
            ("Retry failed", self._retry_email),
            ("Cancel", self._cancel_email),
            ("Sync incoming", self._sync_email),
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
        self.memory_list = QListWidget()
        layout.addWidget(self.memory_list, 1)
        page.setLayout(layout)
        return page

    def _assistant_page(self) -> QWidget:
        page = QWidget()
        layout = self._header("Assistant", "Ask about what is due, waiting, or worth doing next.")
        self.assistant_input = QTextEdit()
        self.assistant_input.setPlaceholderText("Capture a commitment or ask: What am I waiting for?")
        layout.addWidget(self.assistant_input)
        send = QPushButton("Remember this")
        send.setObjectName("primary")
        send.clicked.connect(lambda: self._capture(self.assistant_input.toPlainText()))
        layout.addWidget(send, 0, Qt.AlignmentFlag.AlignLeft)
        page.setLayout(layout)
        return page

    def _settings_page(self) -> QWidget:
        page = QWidget()
        layout = self._header("Settings", "Local-first by default. Provider credentials are kept in the OS credential store.")
        layout.addWidget(QLabel(f"Data directory: {self.container.settings.expanded_data_dir()}"))
        layout.addWidget(QLabel(f"Ollama endpoint: {self.container.settings.ollama_url}"))
        provider = QLabel("Local model: Ollama (connection is checked when AI is used)\nCloud model: disabled unless explicitly configured")
        provider.setObjectName("muted")
        layout.addWidget(provider)
        self.autostart = QCheckBox("Start Pactlyn in the system tray when I log in")
        autostart = LinuxAutostart()
        self.autostart.setChecked(autostart.enabled())
        self.autostart.toggled.connect(lambda enabled: self._set_autostart(autostart, enabled))
        layout.addWidget(self.autostart)
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
        layout.addLayout(backup_row)
        layout.addStretch()
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
        self.connectivity.set_state(state)
        self.connectivity_label.setText(f"Connectivity: {state.value}")
        worker.deleteLater()
        if self.connectivity_worker is worker:
            self.connectivity_worker = None
        if was_offline and state == ConnectivityState.ONLINE and self.container.email_provider:
            self._send_email()
            self._sync_email()

    def _capture_failed(self, error: str) -> None:
        QMessageBox.critical(self, "Capture failed", f"The local model workflow failed:\n\n{error}")

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
        session = self.container.session()
        try:
            service = self.container.commitments(session)
            for candidate in dialog.candidates():
                service.create(candidate, confirmed=not candidate.needs_confirmation, source="ollama" if result.used_local_model else "offline_fallback")
            session.commit()
        except Exception as exc:
            session.rollback()
            QMessageBox.critical(self, "Could not save", f"No commitment was saved:\n\n{exc}")
        finally:
            session.close()
        self.quick_capture.clear()
        self.assistant_input.clear()
        self._refresh()

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
                self.home_summary.setText(f"{len(active)} active commitments  ·  {overdue} overdue  ·  {waiting} waiting for a response")
                self.home_list.clear()
                for item in active[:10]:
                    self.home_list.addItem(self._commitment_text(item))
            if hasattr(self, "commitment_list"):
                self.commitment_list.clear()
                for item in commitments:
                    list_item = self._list_item(item)
                    self.commitment_list.addItem(list_item)
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
                self.email_status.setText(
                    "Resend configured — approved messages can be sent."
                    if self.container.email_provider
                    else "Resend is not configured. Drafts remain local and approved messages stay queued."
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
        finally:
            session.close()
        QMessageBox.information(self, thread.subject or "Conversation", messages + association)
        if thread.needs_review:
            self._review_thread_association(str(thread_id))

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

    def _new_email(self) -> None:
        session = self.container.session()
        try:
            commitments = self._email_commitments(session)
        finally:
            session.close()
        dialog = EmailDraftDialog(self, commitments)
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

    def _edit_email(self) -> None:
        action_id = self._selected_email_id()
        if not action_id:
            return
        session = self.container.session()
        try:
            action = session.get(EmailSendAction, action_id)
            commitments = self._email_commitments(session)
        finally:
            session.close()
        if not action:
            return
        dialog = EmailDraftDialog(self, commitments, action)
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
            action = self.container.email(session).approve(action_id)
            QMessageBox.information(self, "Email approved", f"Approved exact payload for {', '.join(action.recipients)}. It is now queued.")
        except Exception as exc:
            session.rollback()
            QMessageBox.warning(self, "Could not approve", str(exc))
        finally:
            session.close()
        self._refresh()

    def _send_email(self) -> None:
        if not self.container.email_provider:
            QMessageBox.information(self, "Resend unavailable", "Configure a Resend API key and verified sender before sending.")
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

    def _sync_email(self) -> None:
        if not self.container.email_provider:
            QMessageBox.information(self, "Resend unavailable", "Configure Resend before synchronising incoming mail.")
            return
        worker = EmailSyncWorker(self.container)
        worker.finished.connect(lambda _result: self._email_sync_done(worker))
        worker.failed.connect(lambda error: self._email_sync_failed(worker, error))
        self.email_sync_worker = worker
        worker.start()

    def _email_sync_done(self, worker: EmailSyncWorker) -> None:
        worker.deleteLater()
        if self.email_sync_worker is worker:
            self.email_sync_worker = None
        self._refresh()

    def _email_sync_failed(self, worker: EmailSyncWorker, error: str) -> None:
        self._email_sync_done(worker)
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
        self._timer.stop()
        self._connectivity_timer.stop()
        self.tray.hide()
        self.container.vectors.close()
