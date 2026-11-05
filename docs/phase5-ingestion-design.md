# Phase 5: Document Ingestion & Background Processing Design

**Date**: 2026-11-05  
**Status**: Design Phase  
**Dependencies**: Phase 2 (OCR), Phase 3 (Vision), Phase 4 (Figures) complete

## Overview

Phase 5 integrates Phases 2-4 into a complete document ingestion pipeline with:
1. Background processing for long-running tasks
2. SQLite-backed task queue and progress tracking
3. Storage management for extracted figures
4. Document catalog with status tracking
5. Error handling and recovery

## Design Principles

- **Local-First**: All processing remains on-device
- **Background Tasks**: Long extraction/OCR/vision tasks don't block UI
- **Status Tracking**: User can monitor progress of document processing
- **Error Recovery**: Partial failures don't lose work
- **Deduplication**: Same file uploaded twice reuses existing work

## Architecture

### 1. Document Upload Flow

```
User Upload → DocumentIngestion.ingest() 
    ↓
Save file & compute hash
    ↓
Check if document exists (by content_hash)
    ├─ Exists: return existing document
    └─ New: create Document record (status=uploaded)
        ↓
    Queue ProcessingTask (type=extract_document)
        ↓
    Return document_id immediately
```

### 2. Background Processing

```python
class ProcessingTask(Base):
    """Background task queue for long-running document operations."""
    id: str  # task_id
    task_type: str  # extract_document, ocr_page, analyze_figure
    document_id: str | None
    status: str  # queued, running, completed, failed
    priority: int  # 1-10, higher = sooner
    input_data: dict  # JSON parameters
    output_data: dict | None  # JSON results
    error_message: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
```

**Task Types:**
- `extract_document`: Full extraction (text, OCR, figures)
- `ocr_page`: OCR single page
- `analyze_figure`: Vision analysis of extracted figure
- `reindex_document`: Rebuild vector embeddings

**Worker:**
```python
class BackgroundProcessor:
    """Background thread that processes queued tasks."""
    
    def __init__(self, db_session_factory):
        self.db_factory = db_session_factory
        self.running = False
        self.worker_thread = None
    
    def start(self):
        """Start background worker thread."""
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
    
    def stop(self):
        """Stop background worker."""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
    
    def _worker_loop(self):
        """Main worker loop: poll for tasks and execute."""
        while self.running:
            task = self._fetch_next_task()
            if task:
                self._execute_task(task)
            else:
                time.sleep(1)  # No tasks, wait
    
    def _fetch_next_task(self) -> ProcessingTask | None:
        """Get highest priority queued task."""
        with self.db_factory() as session:
            return session.query(ProcessingTask).filter(
                ProcessingTask.status == "queued"
            ).order_by(
                ProcessingTask.priority.desc(),
                ProcessingTask.created_at.asc()
            ).first()
    
    def _execute_task(self, task: ProcessingTask):
        """Execute a processing task."""
        try:
            # Mark as running
            self._update_task_status(task.id, "running", started_at=datetime.utcnow())
            
            # Dispatch by type
            if task.task_type == "extract_document":
                self._process_document(task)
            elif task.task_type == "analyze_figure":
                self._analyze_figure(task)
            # ... other types
            
            # Mark complete
            self._update_task_status(task.id, "completed", completed_at=datetime.utcnow())
        
        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}")
            self._update_task_status(
                task.id, "failed", 
                error_message=str(e)[:1000],
                attempts=task.attempts + 1
            )
```

### 3. Document Extraction Task

```python
def _process_document(self, task: ProcessingTask):
    """Process complete document: extraction + OCR + figures."""
    document_id = task.input_data["document_id"]
    file_path = Path(task.input_data["file_path"])
    
    with self.db_factory() as session:
        doc = session.query(Document).get(document_id)
        
        # Update status
        doc.status = "processing"
        session.commit()
        
        try:
            # 1. Extract text (with OCR if needed)
            extraction_result = extract_text_with_ocr(
                file_path=file_path,
                ocr_engine=None,  # auto-detect
                ocr_dpi=300
            )
            
            # Update document metadata
            doc.page_count = extraction_result.page_count
            doc.extraction_metadata = json.dumps({
                "extractor": extraction_result.extractor,
                "warnings": extraction_result.warnings,
                "diagnostics": extraction_result.diagnostics,
            })
            
            # 2. Store extracted text (chunking handled later)
            # For now, store full text temporarily
            # TODO: chunking strategy
            
            # 3. Extract figures
            figures = extract_figures_from_pdf(
                pdf_path=file_path,
                output_dir=self._get_figure_storage_dir(document_id),
                extract_images=True,
                detect_context=True,
                vision_service=self.vision_service if hasattr(self, 'vision_service') else None
            )
            
            # Store figures in DB
            for fig in figures:
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
                    caption=fig.caption,
                    nearby_text=json.dumps(fig.nearby_text) if fig.nearby_text else None,
                    description=fig.description,
                    figure_type=fig.figure_type,
                    vision_model=fig.vision_model,
                    vision_confidence=fig.vision_confidence,
                    contains_text=fig.contains_text,
                )
                session.add(db_figure)
            
            # Mark as indexed
            doc.status = "indexed"
            doc.processed_at = datetime.utcnow()
            session.commit()
            
            logger.info(
                f"Processed document {document_id}: "
                f"{extraction_result.page_count} pages, {len(figures)} figures"
            )
        
        except Exception as e:
            doc.status = "failed"
            doc.error_message = str(e)[:1000]
            session.commit()
            raise
```

### 4. Storage Organization

```
{PACTLYN_DATA_DIR}/
├── pactlyn.sqlite3        # Database with Document + DocumentFigure records
├── qdrant/                # Vector storage (existing)
├── documents/             # Uploaded documents
│   └── {document_id}/
│       ├── original.pdf   # Original uploaded file
│       └── figures/       # Extracted figures
│           ├── page-1-img-0.png
│           ├── page-1-img-1.jpg
│           └── page-2-img-0.png
└── processing/            # Temporary processing files
    └── {task_id}/
```

**Path Helpers:**
```python
class StorageManager:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.documents_dir = data_dir / "documents"
        self.processing_dir = data_dir / "processing"
    
    def get_document_dir(self, document_id: str) -> Path:
        """Get storage directory for a document."""
        return self.documents_dir / document_id
    
    def get_original_path(self, document_id: str) -> Path:
        """Get path to original uploaded file."""
        return self.get_document_dir(document_id) / "original.pdf"
    
    def get_figures_dir(self, document_id: str) -> Path:
        """Get directory for extracted figures."""
        return self.get_document_dir(document_id) / "figures"
```

### 5. UI Integration

**Document Management Tab** (new):
- Upload button → file picker → `DocumentIngestion.ingest()`
- Document list with status (uploaded, processing, indexed, failed)
- Click document → view extracted text, figures, metadata
- Delete document (mark deleted_at, remove files)

**Progress Indicators:**
- Processing spinner while status=processing
- Error icon with tooltip if status=failed
- Success checkmark if status=indexed

**Memory Integration:**
- Indexed documents become searchable context
- Figures contribute to visual memory
- Text chunks indexed in Qdrant

## Implementation Plan

### Step 1: Database Models ✅
- `ProcessingTask` model
- Migration for processing_tasks table

### Step 2: Background Processor
- `BackgroundProcessor` class
- Worker thread lifecycle
- Task execution dispatcher

### Step 3: Storage Management
- `StorageManager` class
- Directory creation/cleanup
- File path helpers

### Step 4: Document Ingestion Service
- `DocumentIngestion` class
- Upload handler
- Task queueing

### Step 5: Integration Testing
- Upload PDF
- Monitor processing
- Verify extraction, figures, storage

### Step 6: UI (Future)
- Document management tab
- Upload button
- Status display
- (Not required for Phase 5 completion)

## Success Criteria

✅ **Complete**:
- [ ] ProcessingTask model and migration
- [ ] BackgroundProcessor with worker thread
- [ ] StorageManager for file organization
- [ ] DocumentIngestion service
- [ ] Integration test: upload PDF → extracted text + figures in DB
- [ ] Error handling: failed tasks don't crash processor
- [ ] Deduplication: same file twice returns existing document

✅ **Validation**:
- Upload multi-page PDF with figures
- Verify:
  - Document record created (status=uploaded → processing → indexed)
  - ProcessingTask created and completed
  - Extracted text stored
  - Figures extracted and saved
  - DocumentFigure records in DB with correct metadata
  - Files organized in correct directories
  - Second upload of same file reuses existing document

## Non-Goals (Phase 5)

- UI implementation (future work)
- Advanced chunking strategies (use simple for now)
- Vector indexing (Qdrant integration is Phase 6)
- Multi-document queries
- Figure search

## Next Phase

**Phase 6**: RAG integration - index chunks in Qdrant, query over documents and figures
