"""Documents Centre UI - Upload, viewer, search for document intelligence."""

from __future__ import annotations

import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPixmap, QImage
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pactlyn.app.bootstrap import AppContainer
from pactlyn.documents.indexing import DocumentIndexer
from pactlyn.documents.ingestion import DocumentIngestion, StorageManager, BackgroundProcessor
from pactlyn.storage.models import Document, DocumentChunk, DocumentFigure, ProcessingTask
from pactlyn.ui.theme import status_color


class DocumentUploadWorker(QThread):
    """Background worker for document upload."""
    
    finished = Signal(str)  # Emits document_id
    failed = Signal(str)  # Emits error message
    
    def __init__(self, ingestion: DocumentIngestion, file_path: Path) -> None:
        super().__init__()
        self.ingestion = ingestion
        self.file_path = file_path
    
    def run(self) -> None:
        try:
            document_id = self.ingestion.ingest(self.file_path)
            self.finished.emit(document_id)
        except Exception as exc:
            self.failed.emit(f"Upload failed: {exc}")


class DocumentSearchWorker(QThread):
    """Background worker for semantic search."""
    
    finished = Signal(list)  # Emits search results
    failed = Signal(str)  # Emits error message
    
    def __init__(self, indexer: DocumentIndexer, query: str, limit: int = 10) -> None:
        super().__init__()
        self.indexer = indexer
        self.query = query
        self.limit = limit
    
    def run(self) -> None:
        try:
            results = self.indexer.search_documents(self.query, limit=self.limit)
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(f"Search failed: {exc}")


class DocumentListItem(QFrame):
    """List item widget for a document."""
    
    clicked = Signal(str)  # Emits document_id
    deleteRequested = Signal(str)  # Emits document_id
    retryRequested = Signal(str)  # Emits document_id
    
    def __init__(self, doc: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.document_id = doc.id
        
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(80)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        
        # Left side: Document info
        info_layout = QVBoxLayout()
        
        # Filename
        name_label = QLabel(doc.filename)
        name_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        info_layout.addWidget(name_label)
        
        # Metadata row
        meta_parts = []
        if doc.page_count:
            meta_parts.append(f"{doc.page_count} pages")
        if doc.size_bytes:
            size_mb = doc.size_bytes / (1024 * 1024)
            meta_parts.append(f"{size_mb:.1f} MB")
        if doc.created_at:
            meta_parts.append(doc.created_at.strftime("%Y-%m-%d"))
        
        meta_label = QLabel(" • ".join(meta_parts))
        meta_label.setObjectName("muted")
        info_layout.addWidget(meta_label)
        
        # Status
        status_text, status_style = self._get_status_display(doc.status)
        status_label = QLabel(status_text)
        status_label.setStyleSheet(status_style)
        info_layout.addWidget(status_label)
        
        # Error message if failed
        if doc.status == "failed" and doc.error_message:
            error_label = QLabel(f"Error: {doc.error_message[:100]}")
            error_label.setObjectName("muted")
            error_label.setStyleSheet("color: #d9534f;")
            error_label.setWordWrap(True)
            info_layout.addWidget(error_label)
        
        layout.addLayout(info_layout, 1)
        
        # Right side: Actions
        actions_layout = QVBoxLayout()
        actions_layout.setAlignment(Qt.AlignTop)
        
        # Retry button for failed documents
        if doc.status == "failed":
            retry_btn = QPushButton("Retry")
            retry_btn.clicked.connect(lambda: self.retryRequested.emit(self.document_id))
            actions_layout.addWidget(retry_btn)
        
        # Delete button
        delete_btn = QPushButton("Delete")
        delete_btn.setObjectName("dangerous")
        delete_btn.clicked.connect(lambda: self.deleteRequested.emit(self.document_id))
        actions_layout.addWidget(delete_btn)
        
        layout.addLayout(actions_layout)
    
    def _get_status_display(self, status: str) -> tuple[str, str]:
        """Get display text and style for status."""
        if status == "uploaded":
            return "⏳ Queued", "color: #0275d8;"
        elif status == "processing":
            return "⚙ Processing...", "color: #f0ad4e;"
        elif status == "indexed":
            return "✓ Ready", "color: #5cb85c;"
        elif status == "failed":
            return "✗ Failed", "color: #d9534f;"
        return status, ""
    
    def mousePressEvent(self, event):
        """Handle click to open document."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.document_id)
        super().mousePressEvent(event)


class DocumentViewer(QWidget):
    """Document viewer with text, figures, and navigation."""
    
    closed = Signal()  # Emitted when viewer is closed
    
    def __init__(self, container: AppContainer, document_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.container = container
        self.document_id = document_id
        self.current_page = 1
        
        self._init_ui()
        self._load_document()
    
    def _init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header with close button
        header = QHBoxLayout()
        self.title_label = QLabel("Document Viewer")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        header.addWidget(self.title_label)
        header.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.closed.emit)
        header.addWidget(close_btn)
        
        layout.addLayout(header)
        
        # Content splitter: extracted text | figures
        splitter = QSplitter(Qt.Horizontal)
        
        # Left: Extracted text
        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        
        text_layout.addWidget(QLabel("Extracted Text:"))
        
        self.text_view = QTextEdit()
        self.text_view.setReadOnly(True)
        text_layout.addWidget(self.text_view)
        
        # Page navigation
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("< Previous")
        self.prev_btn.clicked.connect(self._prev_page)
        nav_layout.addWidget(self.prev_btn)
        
        self.page_label = QLabel("Page 1 of 1")
        self.page_label.setAlignment(Qt.AlignCenter)
        nav_layout.addWidget(self.page_label, 1)
        
        self.next_btn = QPushButton("Next >")
        self.next_btn.clicked.connect(self._next_page)
        nav_layout.addWidget(self.next_btn)
        
        text_layout.addLayout(nav_layout)
        
        splitter.addWidget(text_widget)
        
        # Right: Figures
        figures_widget = QWidget()
        figures_layout = QVBoxLayout(figures_widget)
        
        figures_layout.addWidget(QLabel("Extracted Figures:"))
        
        self.figures_list = QListWidget()
        self.figures_list.itemClicked.connect(self._show_figure)
        figures_layout.addWidget(self.figures_list)
        
        splitter.addWidget(figures_widget)
        
        splitter.setSizes([600, 400])
        layout.addWidget(splitter)
    
    def _load_document(self):
        """Load document data."""
        session = self.container.session()
        try:
            # Load document
            doc = session.query(Document).get(self.document_id)
            if not doc:
                self.text_view.setPlainText("Document not found")
                return
            
            self.title_label.setText(f"{doc.filename}")
            self.page_count = doc.page_count or 1
            
            # Load chunks (text)
            self.chunks = session.query(DocumentChunk).filter(
                DocumentChunk.document_id == self.document_id
            ).order_by(DocumentChunk.chunk_index).all()
            
            # Load figures
            self.figures = session.query(DocumentFigure).filter(
                DocumentFigure.document_id == self.document_id
            ).order_by(DocumentFigure.page_number, DocumentFigure.image_index).all()
            
            # Populate figures list
            self.figures_list.clear()
            for fig in self.figures:
                desc = fig.description or "No description"
                item_text = f"Page {fig.page_number}, Image {fig.image_index}: {desc[:50]}..."
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, fig.id)
                self.figures_list.addItem(item)
            
            # Show first page
            self._update_page_display()
            
        finally:
            session.close()
    
    def _update_page_display(self):
        """Update text display for current page."""
        # Find chunks for current page
        page_chunks = [
            chunk for chunk in self.chunks
            if self.current_page in json.loads(chunk.page_numbers or "[]")
        ]
        
        if page_chunks:
            text = "\n\n---\n\n".join(chunk.content for chunk in page_chunks)
            self.text_view.setPlainText(text)
        else:
            self.text_view.setPlainText(f"[No text extracted for page {self.current_page}]")
        
        # Update navigation
        self.page_label.setText(f"Page {self.current_page} of {self.page_count}")
        self.prev_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(self.current_page < self.page_count)
    
    def _prev_page(self):
        """Go to previous page."""
        if self.current_page > 1:
            self.current_page -= 1
            self._update_page_display()
    
    def _next_page(self):
        """Go to next page."""
        if self.current_page < self.page_count:
            self.current_page += 1
            self._update_page_display()
    
    def _show_figure(self, item: QListWidgetItem):
        """Show figure details."""
        figure_id = item.data(Qt.UserRole)
        session = self.container.session()
        try:
            fig = session.query(DocumentFigure).get(figure_id)
            if fig:
                msg = QMessageBox(self)
                msg.setWindowTitle(f"Figure - Page {fig.page_number}")
                
                details = []
                details.append(f"Size: {fig.width}x{fig.height}")
                if fig.figure_type:
                    details.append(f"Type: {fig.figure_type}")
                if fig.description:
                    details.append(f"\nDescription (AI-generated):\n{fig.description}")
                
                msg.setText("\n".join(details))
                
                # Load and show image if available
                if fig.local_path and Path(fig.local_path).exists():
                    pixmap = QPixmap(str(fig.local_path))
                    if not pixmap.isNull():
                        # Scale to reasonable size
                        scaled = pixmap.scaled(400, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        msg.setIconPixmap(scaled)
                
                msg.exec()
        finally:
            session.close()


class SearchResultsWidget(QWidget):
    """Widget displaying search results."""
    
    resultClicked = Signal(str, int)  # Emits (document_id, page_number)
    
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        
        self.results_list = QListWidget()
        self.results_list.itemClicked.connect(self._result_clicked)
        layout.addWidget(self.results_list)
        
        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        layout.addWidget(self.status_label)
    
    def set_results(self, results: list[dict[str, Any]]):
        """Display search results."""
        self.results_list.clear()
        
        if not results:
            self.status_label.setText("No results found")
            return
        
        self.status_label.setText(f"Found {len(results)} results")
        
        for result in results:
            score = result.get("score", 0)
            filename = result.get("filename", "Unknown")
            pages = result.get("page_numbers", [])
            text = result.get("text", "")[:200]
            
            item_text = f"[{score:.3f}] {filename} (Pages {pages})\n{text}..."
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, (result.get("document_id"), pages[0] if pages else 1))
            self.results_list.addItem(item)
    
    def _result_clicked(self, item: QListWidgetItem):
        """Handle result click."""
        document_id, page_num = item.data(Qt.UserRole)
        self.resultClicked.emit(document_id, page_num)


class DocumentsPage(QWidget):
    """Main documents page with upload, list, viewer, and search."""
    
    def __init__(self, container: AppContainer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.container = container
        
        # Initialize services
        self._init_services()
        
        # Initialize UI
        self._init_ui()
        
        # Start refresh timer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_document_list)
        self.refresh_timer.start(2000)  # Refresh every 2 seconds
        
        # Load initial documents
        self._refresh_document_list()
    
    def _init_services(self):
        """Initialize document services."""
        # Storage manager
        data_dir = Path.home() / ".local" / "share" / "pactlyn"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.storage = StorageManager(data_dir)
        
        # Document indexer
        self.indexer = DocumentIndexer(
            db_session_factory=self.container.session_factory,
            vector_store=self.container.vectors,
            embedding_provider=self.container.embedder,
        )
        
        # Background processor (if not already running)
        self.processor = BackgroundProcessor(
            db_session_factory=self.container.session_factory,
            storage_manager=self.storage,
            document_indexer=self.indexer,
        )
        self.processor.start()
        
        # Document ingestion
        self.ingestion = DocumentIngestion(
            db_session_factory=self.container.session_factory,
            storage_manager=self.storage,
            background_processor=self.processor,
        )
    
    def _init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout(self)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("Documents")
        title.setStyleSheet("font-weight: bold; font-size: 18px;")
        header.addWidget(title)
        header.addStretch()
        
        # Upload button
        upload_btn = QPushButton("Upload Document")
        upload_btn.clicked.connect(self._upload_document)
        header.addWidget(upload_btn)
        
        layout.addLayout(header)
        
        # Search bar
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter search query...")
        self.search_input.returnPressed.connect(self._search_documents)
        search_layout.addWidget(self.search_input, 1)
        
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self._search_documents)
        search_layout.addWidget(search_btn)
        
        layout.addLayout(search_layout)
        
        # Main content: stacked widget for list/viewer/search
        self.stack = QStackedWidget()
        
        # Document list view
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        
        # Enable drag and drop
        list_widget.setAcceptDrops(True)
        list_widget.dragEnterEvent = self._drag_enter
        list_widget.dropEvent = self._drop_file
        
        self.document_list = QWidget()
        self.document_list_layout = QVBoxLayout(self.document_list)
        self.document_list_layout.setAlignment(Qt.AlignTop)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.document_list)
        list_layout.addWidget(scroll)
        
        self.stack.addWidget(list_widget)
        
        # Search results view
        self.search_results = SearchResultsWidget()
        self.search_results.resultClicked.connect(self._open_document_at_page)
        
        search_container = QWidget()
        search_container_layout = QVBoxLayout(search_container)
        
        back_to_list_btn = QPushButton("< Back to Documents")
        back_to_list_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        search_container_layout.addWidget(back_to_list_btn)
        search_container_layout.addWidget(self.search_results)
        
        self.stack.addWidget(search_container)
        
        layout.addWidget(self.stack)
    
    def _drag_enter(self, event: QDragEnterEvent):
        """Handle drag enter for file drops."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def _drop_file(self, event: QDropEvent):
        """Handle file drop."""
        urls = event.mimeData().urls()
        if urls:
            file_path = Path(urls[0].toLocalFile())
            if file_path.suffix.lower() == ".pdf":
                self._upload_file(file_path)
            else:
                QMessageBox.warning(self, "Invalid File", "Only PDF files are supported")
    
    def _upload_document(self):
        """Open file picker to upload document."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select PDF Document",
            "",
            "PDF Files (*.pdf)"
        )
        
        if file_path:
            self._upload_file(Path(file_path))
    
    def _upload_file(self, file_path: Path):
        """Upload a document file."""
        worker = DocumentUploadWorker(self.ingestion, file_path)
        worker.finished.connect(self._upload_finished)
        worker.failed.connect(self._upload_failed)
        worker.start()
        
        # Store worker to prevent garbage collection
        self._current_worker = worker
    
    def _upload_finished(self, document_id: str):
        """Handle successful upload."""
        QMessageBox.information(self, "Upload Complete", f"Document uploaded: {document_id[:8]}...")
        self._refresh_document_list()
    
    def _upload_failed(self, error: str):
        """Handle upload failure."""
        QMessageBox.critical(self, "Upload Failed", error)
    
    def refresh_list(self):
        """Public method to refresh the document list when the page is navigated to."""
        self._refresh_document_list()
    
    def _refresh_document_list(self):
        """Refresh the document list."""
        session = self.container.session()
        try:
            documents = session.query(Document).filter(
                Document.deleted_at.is_(None)
            ).order_by(Document.created_at.desc()).all()
            
            # Clear existing items
            while self.document_list_layout.count():
                item = self.document_list_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            
            # Add document items
            for doc in documents:
                item = DocumentListItem(doc)
                item.clicked.connect(self._open_document)
                item.deleteRequested.connect(self._delete_document)
                item.retryRequested.connect(self._retry_document)
                self.document_list_layout.addWidget(item)
            
            # Add stretch
            self.document_list_layout.addStretch()
            
        finally:
            session.close()
    
    def _open_document(self, document_id: str):
        """Open document viewer."""
        viewer = DocumentViewer(self.container, document_id, self)
        viewer.closed.connect(lambda: self.stack.setCurrentIndex(0))
        
        # Add viewer to stack
        self.stack.addWidget(viewer)
        self.stack.setCurrentWidget(viewer)
    
    def _open_document_at_page(self, document_id: str, page_num: int):
        """Open document viewer at specific page."""
        viewer = DocumentViewer(self.container, document_id, self)
        viewer.current_page = page_num
        viewer._update_page_display()
        viewer.closed.connect(lambda: self.stack.setCurrentIndex(0))
        
        self.stack.addWidget(viewer)
        self.stack.setCurrentWidget(viewer)
    
    def open_document_by_id(self, document_id: int, page_number: int | None = None):
        """Public method to open document by ID with optional page number.
        
        Called by assistant when citation is clicked.
        """
        session = self.container.session()
        try:
            # Get document by integer ID
            from pactlyn.storage.models import Document
            doc = session.get(Document, document_id)
            if not doc:
                QMessageBox.warning(self, "Document Not Found", f"Document ID {document_id} not found")
                return
            
            # Open at specific page if provided
            if page_number is not None:
                self._open_document_at_page(doc.id, page_number)
            else:
                self._open_document(doc.id)
                
        finally:
            session.close()
    
    def _delete_document(self, document_id: str):
        """Delete a document."""
        reply = QMessageBox.question(
            self,
            "Delete Document",
            "Are you sure you want to delete this document?\nThis will remove all extracted data.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            session = self.container.session()
            try:
                # Mark as deleted
                doc = session.query(Document).get(document_id)
                if doc:
                    doc.deleted_at = datetime.utcnow()
                    session.commit()
                
                # Delete from index
                self.indexer.delete_document_index(document_id)
                
                # Delete files
                self.storage.delete_document(document_id)
                
                QMessageBox.information(self, "Deleted", "Document deleted successfully")
                self._refresh_document_list()
                
            except Exception as e:
                session.rollback()
                QMessageBox.critical(self, "Delete Failed", f"Failed to delete document: {e}")
            finally:
                session.close()
    
    def _retry_document(self, document_id: str):
        """Retry processing a failed document."""
        # TODO: Implement retry logic
        QMessageBox.information(self, "Retry", "Retry feature coming soon")
    
    def _search_documents(self):
        """Search documents semantically."""
        query = self.search_input.text().strip()
        if not query:
            return
        
        worker = DocumentSearchWorker(self.indexer, query, limit=10)
        worker.finished.connect(self._search_finished)
        worker.failed.connect(self._search_failed)
        worker.start()
        
        # Store worker
        self._search_worker = worker
        
        # Show search view
        self.stack.setCurrentIndex(1)
        self.search_results.status_label.setText("Searching...")
    
    def _search_finished(self, results: list):
        """Handle search results."""
        self.search_results.set_results(results)
    
    def _search_failed(self, error: str):
        """Handle search failure."""
        self.search_results.status_label.setText(f"Search failed: {error}")
    
    def closeEvent(self, event):
        """Clean up on close."""
        self.refresh_timer.stop()
        self.processor.stop()
        super().closeEvent(event)
