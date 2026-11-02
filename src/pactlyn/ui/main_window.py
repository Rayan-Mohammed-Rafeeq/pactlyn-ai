from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pactlyn.app.bootstrap import AppContainer
from pactlyn.core.commitments import CaptureResult
from pactlyn.core.scheduler import ReminderScheduler
from pactlyn.storage.models import CommitmentStatus

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


class PactlynWindow(QMainWindow):
    def __init__(self, container: AppContainer):
        super().__init__()
        self.container = container
        self.setWindowTitle("Pactlyn — Remember what matters")
        self.resize(1180, 760)
        self.setStyleSheet(STYLE)
        self.pages = QStackedWidget()
        self.nav: list[QPushButton] = []
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
        self.commitment_list = QListWidget()
        self.commitment_list.itemDoubleClicked.connect(self._complete_selected)
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
        self.email_status = QLabel("No email provider configured. Drafts can still be prepared locally.")
        self.email_status.setObjectName("muted")
        layout.addWidget(self.email_status)
        layout.addStretch()
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
        layout.addStretch()
        page.setLayout(layout)
        return page

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
        result = self._run_capture(text)
        if not result.candidates:
            QMessageBox.warning(self, "Nothing captured", "Pactlyn could not find a commitment in that text.")
            return
        candidate = result.candidates[0]
        message = f"{candidate.title}\n\n{candidate.description}"
        if candidate.due_at:
            message += f"\n\nDeadline: {candidate.due_at.astimezone().strftime('%d %b %Y, %H:%M')}"
        if candidate.person:
            message += f"\nPerson: {candidate.person}"
        message += "\n\nThis will be saved as needing confirmation." if candidate.needs_confirmation else "\n\nSave this commitment?"
        if QMessageBox.question(self, "Review commitment", message, QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Save:
            session = self.container.session()
            try:
                self.container.commitments(session).create(candidate, confirmed=not candidate.needs_confirmation)
                session.commit()
            finally:
                session.close()
            self.quick_capture.clear()
            self.assistant_input.clear()
            self._refresh()

    def _run_capture(self, text: str) -> CaptureResult:
        # The deterministic extractor is always available; users can select the
        # Ollama async path from the service layer without making the UI depend
        # on a running event loop.
        from pactlyn.core.commitments import CommitmentExtractor
        return CommitmentExtractor().extract(text, timezone_name=self.container.settings.default_timezone)

    def _refresh(self) -> None:
        session = self.container.session()
        try:
            commitments = self.container.commitments(session).list()
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
                    self.commitment_list.addItem(self._commitment_text(item))
            if hasattr(self, "waiting_list"):
                self.waiting_list.clear()
                for item in commitments:
                    if item.status == CommitmentStatus.WAITING or item.type.value == "waiting_for":
                        self.waiting_list.addItem(self._commitment_text(item))
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

    def _complete_selected(self) -> None:
        item = self.commitment_list.currentItem()
        if not item:
            return
        session = self.container.session()
        try:
            commitments = self.container.commitments(session).list()
            index = self.commitment_list.currentRow()
            if index < len(commitments):
                self.container.commitments(session).complete(commitments[index].id)
                session.commit()
        finally:
            session.close()
        self._refresh()

    def _evaluate_reminders(self) -> None:
        session = self.container.session()
        try:
            ReminderScheduler(session, lambda title, body: self._notify(title, body)).evaluate()
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
