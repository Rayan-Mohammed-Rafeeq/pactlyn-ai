"""Document ingestion service with background processing.

Handles document upload, deduplication, and background extraction pipeline.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from pactlyn.documents import extraction, figures, ocr, vision
from pactlyn.documents.extraction import compute_content_hash
from pactlyn.storage.models import Document, DocumentFigure, ProcessingTask

logger = logging.getLogger(__name__)


class StorageManager:
    """Manages document and figure storage on disk."""

    def __init__(self, data_dir: Path):
        """Initialize storage manager.

        Args:
            data_dir: Base data directory (e.g., ~/.local/share/pactlyn/)
        """
        self.data_dir = data_dir
        self.documents_dir = data_dir / "documents"
        self.processing_dir = data_dir / "processing"

        # Ensure directories exist
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.processing_dir.mkdir(parents=True, exist_ok=True)

    def get_document_dir(self, document_id: str) -> Path:
        """Get storage directory for a document."""
        return self.documents_dir / document_id

    def get_original_path(self, document_id: str) -> Path:
        """Get path to original uploaded file."""
        doc_dir = self.get_document_dir(document_id)
        doc_dir.mkdir(parents=True, exist_ok=True)
        return doc_dir / "original.pdf"

    def get_figures_dir(self, document_id: str) -> Path:
        """Get directory for extracted figures."""
        figures_dir = self.get_document_dir(document_id) / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)
        return figures_dir

    def get_processing_dir(self, task_id: str) -> Path:
        """Get temporary processing directory for a task."""
        proc_dir = self.processing_dir / task_id
        proc_dir.mkdir(parents=True, exist_ok=True)
        return proc_dir

    def cleanup_processing_dir(self, task_id: str):
        """Remove temporary processing directory."""
        proc_dir = self.processing_dir / task_id
        if proc_dir.exists():
            shutil.rmtree(proc_dir, ignore_errors=True)

    def delete_document(self, document_id: str):
        """Delete all files for a document."""
        doc_dir = self.get_document_dir(document_id)
        if doc_dir.exists():
            shutil.rmtree(doc_dir, ignore_errors=True)


class BackgroundProcessor:
    """Background worker for processing document tasks."""

    def __init__(
        self,
        db_session_factory: sessionmaker[Session],
        storage_manager: StorageManager,
        document_indexer: Any | None = None,  # DocumentIndexer (optional)
    ):
        """Initialize background processor.

        Args:
            db_session_factory: Database session factory
            storage_manager: Storage manager for files
            document_indexer: Document indexer for embeddings (optional)
        """
        self.db_factory = db_session_factory
        self.storage = storage_manager
        self.indexer = document_indexer
        self.running = False
        self.worker_thread: threading.Thread | None = None
        self.vision_service: vision.VisionService | None = None

    def start(self):
        """Start background worker thread."""
        if self.running:
            logger.warning("Background processor already running")
            return

        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="DocumentProcessor")
        self.worker_thread.start()
        logger.info("Background processor started")

    def stop(self, timeout: float = 5.0):
        """Stop background worker.

        Args:
            timeout: Timeout for thread join in seconds
        """
        if not self.running:
            return

        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=timeout)
            self.worker_thread = None
        logger.info("Background processor stopped")

    def _worker_loop(self):
        """Main worker loop: poll for tasks and execute."""
        logger.info("Worker loop started")
        while self.running:
            try:
                task = self._fetch_next_task()
                if task:
                    self._execute_task(task)
                else:
                    time.sleep(1)  # No tasks, wait before polling again
            except Exception as e:
                logger.error(f"Worker loop error: {e}", exc_info=True)
                time.sleep(5)  # Back off on error

    def _fetch_next_task(self) -> ProcessingTask | None:
        """Get highest priority queued task.

        Returns:
            Next task to process, or None if queue is empty
        """
        session = self.db_factory()
        try:
            task = (
                session.query(ProcessingTask)
                .filter(ProcessingTask.status == "queued")
                .order_by(ProcessingTask.priority.desc(), ProcessingTask.created_at.asc())
                .first()
            )

            if task:
                # Detach from session so we can use it outside context
                session.expunge(task)

            return task
        finally:
            session.close()

    def _execute_task(self, task: ProcessingTask):
        """Execute a processing task.

        Args:
            task: Task to execute
        """
        logger.info(f"Executing task {task.id}: {task.task_type}")

        try:
            # Mark as running
            self._update_task_status(task.id, "running", started_at=datetime.utcnow())

            # Dispatch by type
            if task.task_type == "extract_document":
                self._process_document(task)
            elif task.task_type == "index_document":
                self._index_document(task)
            elif task.task_type == "analyze_figure":
                self._analyze_figure(task)
            else:
                raise ValueError(f"Unknown task type: {task.task_type}")

            # Mark complete
            self._update_task_status(task.id, "completed", completed_at=datetime.utcnow())
            logger.info(f"Task {task.id} completed successfully")

        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}", exc_info=True)
            self._update_task_status(
                task.id, "failed", error_message=str(e)[:1000], attempts=task.attempts + 1
            )

    def _update_task_status(
        self,
        task_id: str,
        status: str,
        error_message: str | None = None,
        attempts: int | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ):
        """Update task status in database.

        Args:
            task_id: Task ID
            status: New status
            error_message: Error message if failed
            attempts: New attempt count
            started_at: Start timestamp
            completed_at: Completion timestamp
        """
        session = self.db_factory()
        try:
            task = session.query(ProcessingTask).get(task_id)
            if task:
                task.status = status
                if error_message is not None:
                    task.error_message = error_message
                if attempts is not None:
                    task.attempts = attempts
                if started_at is not None:
                    task.started_at = started_at
                if completed_at is not None:
                    task.completed_at = completed_at
                session.commit()
        finally:
            session.close()

    def _process_document(self, task: ProcessingTask):
        """Process complete document: extraction + OCR + figures.

        Args:
            task: Processing task with document_id and file_path in input_data
        """
        document_id = task.input_data["document_id"]
        file_path = Path(task.input_data["file_path"])

        if not file_path.exists():
            raise FileNotFoundError(f"Document file not found: {file_path}")

        session = self.db_factory()
        try:
            doc = session.query(Document).get(document_id)
            if not doc:
                raise ValueError(f"Document {document_id} not found in database")

            # Update status to processing
            doc.status = "processing"
            session.commit()
        finally:
            session.close()

        try:
            # 1. Extract text with OCR
            logger.info(f"Extracting text from {file_path}")
            extraction_result = extraction.extract_text_with_ocr(
                file_path=file_path, ocr_engine=None, ocr_dpi=300  # auto-detect
            )

            # 2. Extract figures
            logger.info(f"Extracting figures from {file_path}")
            
            # Extract figures using FigureExtractor
            extractor = figures.FigureExtractor()
            extracted_figures = extractor.extract_figures_from_pdf(
                pdf_path=file_path,
                max_pages=None,  # Process all pages
            )
            
            logger.info(f"Extracted {len(extracted_figures)} figures from {file_path}")
            
            # Optionally save images to storage
            figures_dir = self.storage.get_figures_dir(document_id)
            for fig in extracted_figures:
                if fig.image:
                    # Save image file
                    image_filename = f"page-{fig.page_number}-img-{fig.image_index}.png"
                    image_path = figures_dir / image_filename
                    fig.image.save(image_path, "PNG")
                    fig.local_path = image_path
                    logger.debug(f"Saved figure to {image_path}")

            # 3. Store results in database
            session = self.db_factory()
            try:
                doc = session.query(Document).get(document_id)

                # Update document metadata
                doc.page_count = extraction_result.page_count
                doc.extraction_metadata = json.dumps(
                    {
                        "extractor": extraction_result.extractor,
                        "warnings": extraction_result.warnings,
                        "diagnostics": extraction_result.diagnostics,
                    }
                )

                # Store figures
                for fig in extracted_figures:
                    db_figure = DocumentFigure(
                        document_id=document_id,
                        page_number=fig.page_number,
                        image_index=fig.image_index,
                        image_hash=fig.image_hash,
                        bbox_x0=fig.bbox.x0,
                        bbox_y0=fig.bbox.y0,
                        bbox_x1=fig.bbox.x1,
                        bbox_y1=fig.bbox.y1,
                        width=fig.width,
                        height=fig.height,
                        format=fig.format,
                        colorspace=fig.colorspace,
                        local_path=str(fig.local_path) if fig.local_path else None,
                        caption=None,  # Phase 4 extractor doesn't provide captions yet
                        nearby_text=None,  # Context detection not integrated yet
                        description=None,  # Vision analysis done separately
                        figure_type=None,
                        vision_model=None,
                        vision_confidence=None,
                        contains_text=False,
                    )
                    session.add(db_figure)

                # Mark as extracted (indexing happens separately)
                doc.status = "extracted"
                doc.processed_at = datetime.utcnow()
                session.commit()

                logger.info(
                    f"Extracted document {document_id}: "
                    f"{extraction_result.page_count} pages, {len(extracted_figures)} figures"
                )

                # Store extracted text for indexing
                extracted_text = extraction_result.text
                extracted_page_count = extraction_result.page_count

            finally:
                session.close()

            # 4. Queue indexing task if indexer available
            if self.indexer is not None:
                self._queue_indexing(document_id, extracted_text, extracted_page_count)

        except Exception as e:
            # Update document status to failed
            session = self.db_factory()
            try:
                doc = session.query(Document).get(document_id)
                if doc:
                    doc.status = "failed"
                    doc.error_message = str(e)[:1000]
                    session.commit()
            finally:
                session.close()
            raise

    def _analyze_figure(self, task: ProcessingTask):
        """Analyze a single figure with vision model.

        Args:
            task: Processing task with figure_id in input_data
        """
        figure_id = task.input_data["figure_id"]

        session = self.db_factory()
        try:
            fig = session.query(DocumentFigure).get(figure_id)
            if not fig:
                raise ValueError(f"Figure {figure_id} not found")

            if not fig.local_path:
                raise ValueError(f"Figure {figure_id} has no local path")

            image_path = Path(fig.local_path)
            if not image_path.exists():
                raise FileNotFoundError(f"Figure image not found: {image_path}")

            # Initialize vision service
            if self.vision_service is None:
                self.vision_service = vision.VisionService()

            # Analyze image
            result = self.vision_service.analyze_image(
                image_path=image_path, prompt="Describe this figure in detail."
            )

            # Update figure
            fig.description = result.description
            fig.vision_model = result.model_name
            fig.vision_confidence = result.confidence
            session.commit()

            logger.info(f"Analyzed figure {figure_id} with {result.model_name}")
        finally:
            session.close()

    def _index_document(self, task: ProcessingTask):
        """Index document for semantic search.

        Args:
            task: Processing task with document_id and text in input_data
        """
        if self.indexer is None:
            logger.warning("Document indexer not available, skipping indexing")
            return

        document_id = task.input_data["document_id"]
        text = task.input_data.get("text", "")
        page_count = task.input_data.get("page_count")

        if not text:
            logger.warning(f"No text provided for indexing document {document_id}")
            return

        try:
            chunk_count = self.indexer.index_document(
                document_id=document_id,
                text=text,
                page_count=page_count,
            )

            # Mark document as indexed after successful chunking
            session = self.db_factory()
            try:
                doc = session.query(Document).get(document_id)
                if doc:
                    doc.status = "indexed"
                    session.commit()
            finally:
                session.close()

            logger.info(f"Indexed {chunk_count} chunks for document {document_id}")

        except Exception as e:
            logger.error(f"Indexing failed for document {document_id}: {e}")
            # Mark document as failed
            session = self.db_factory()
            try:
                doc = session.query(Document).get(document_id)
                if doc:
                    doc.status = "failed"
                    doc.error_message = f"Indexing failed: {str(e)[:900]}"
                    session.commit()
            finally:
                session.close()
            raise

    def _queue_indexing(self, document_id: str, text: str, page_count: int | None):
        """Queue document indexing task.

        Args:
            document_id: Document ID
            text: Extracted text
            page_count: Number of pages
        """
        session = self.db_factory()
        try:
            task = ProcessingTask(
                task_type="index_document",
                document_id=document_id,
                status="queued",
                priority=4,  # Slightly lower priority than extraction
                input_data={
                    "document_id": document_id,
                    "text": text,
                    "page_count": page_count,
                },
                output_data=None,
                error_message=None,
                attempts=0,
                created_at=datetime.utcnow(),
                started_at=None,
                completed_at=None,
            )
            session.add(task)
            session.commit()

            logger.info(f"Queued indexing task for document {document_id}")

        finally:
            session.close()


class DocumentIngestion:
    """Service for ingesting documents into the system."""

    def __init__(
        self,
        db_session_factory: sessionmaker[Session],
        storage_manager: StorageManager,
        background_processor: BackgroundProcessor | None = None,
    ):
        """Initialize document ingestion service.

        Args:
            db_session_factory: Database session factory
            storage_manager: Storage manager for files
            background_processor: Background processor (optional, for immediate processing)
        """
        self.db_factory = db_session_factory
        self.storage = storage_manager
        self.processor = background_processor

    def ingest(self, file_path: Path, filename: str | None = None) -> str:
        """Ingest a document file.

        Args:
            file_path: Path to document file
            filename: Original filename (defaults to file_path.name)

        Returns:
            Document ID

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format not supported
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if filename is None:
            filename = file_path.name

        # Compute content hash for deduplication
        content_hash = compute_content_hash(file_path)

        # Check if document already exists
        session = self.db_factory()
        try:
            existing = session.query(Document).filter(Document.content_hash == content_hash).first()
            if existing:
                logger.info(f"Document already exists: {existing.id}")
                return existing.id

            # Create new document record
            doc = Document(
                filename=filename,
                content_hash=content_hash,
                mime_type="application/pdf",  # TODO: detect from file
                size_bytes=file_path.stat().st_size,
                status="uploaded",
                page_count=None,
                created_at=datetime.utcnow(),
                processed_at=None,
                deleted_at=None,
                error_message=None,
                extraction_metadata=None,
            )
            session.add(doc)
            session.commit()
            session.refresh(doc)
            document_id = doc.id
        finally:
            session.close()

        # Copy file to storage
        storage_path = self.storage.get_original_path(document_id)
        shutil.copy2(file_path, storage_path)
        logger.info(f"Stored document {document_id} at {storage_path}")

        # Queue processing task
        self._queue_extraction(document_id, storage_path)

        return document_id

    def _queue_extraction(self, document_id: str, file_path: Path):
        """Queue document extraction task.

        Args:
            document_id: Document ID
            file_path: Path to document file
        """
        session = self.db_factory()
        try:
            task = ProcessingTask(
                task_type="extract_document",
                document_id=document_id,
                status="queued",
                priority=5,
                input_data={"document_id": document_id, "file_path": str(file_path)},
                output_data=None,
                error_message=None,
                attempts=0,
                created_at=datetime.utcnow(),
                started_at=None,
                completed_at=None,
            )
            session.add(task)
            session.commit()
        finally:
            session.close()

        logger.info(f"Queued extraction task for document {document_id}")

    def get_document_status(self, document_id: str) -> dict[str, Any]:
        """Get document processing status.

        Args:
            document_id: Document ID

        Returns:
            Status dict with document and task info
        """
        session = self.db_factory()
        try:
            doc = session.query(Document).get(document_id)
            if not doc:
                raise ValueError(f"Document {document_id} not found")

            tasks = (
                session.query(ProcessingTask)
                .filter(ProcessingTask.document_id == document_id)
                .order_by(ProcessingTask.created_at.desc())
                .all()
            )

            return {
                "document_id": doc.id,
                "filename": doc.filename,
                "status": doc.status,
                "page_count": doc.page_count,
                "error_message": doc.error_message,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "processed_at": doc.processed_at.isoformat() if doc.processed_at else None,
                "tasks": [
                    {
                        "task_id": t.id,
                        "task_type": t.task_type,
                        "status": t.status,
                        "error_message": t.error_message,
                        "attempts": t.attempts,
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                    }
                    for t in tasks
                ],
            }
        finally:
            session.close()
