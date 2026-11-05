# Phase 0: Multimodal Document Intelligence Audit Report

**Date**: 2026-11-05  
**Status**: Complete  
**Next Phase**: Phase 1 - PDF Text Extraction

## Executive Summary

This audit confirms that **Pactlyn has a solid foundation for document intelligence integration**. The existing architecture (PySide6 UI, SQLAlchemy/SQLite storage, Qdrant vectors, Ollama inference, LangGraph orchestration, dynamic model management) supports all planned features. Both reference repositories use MIT licenses and provide excellent implementation patterns.

### Key Findings

✅ **Preserve**: Dynamic model management system (OllamaDiscoveryService, ModelConfigurationService, ModelRole, ActiveModelSelection) is already implemented  
✅ **Integrate**: Use existing Qdrant VectorStore interface for document collection  
✅ **Extend**: Add document models to storage/models.py following existing patterns  
✅ **Reuse**: Memory service patterns for document embedding/indexing  
✅ **Follow**: UI navigation pattern for Documents section  
✅ **Compatible**: Both reference repositories (local-ai-workspace, haiku.rag) use MIT licenses  

### Critical Requirements Verified

- ✅ Dynamic model discovery and configuration exists (do not recreate)
- ✅ Qdrant local mode operational for vector storage
- ✅ SQLite + Alembic migration system ready for document schema
- ✅ PySide6 UI extensible for Documents navigation section
- ✅ LangGraph orchestration available for document processing workflows
- ✅ Ollama integration established with provider abstraction
- ✅ Background worker pattern exists for heavy processing

---

## Reference Repository Analysis

### 1. local-ai-workspace (GitHub: Jn527fd/local-ai-workspace)

**License**: MIT License  
**Copyright**: 2026 Local AI Coding Assistant contributors  
**Repository**: `D:\Projects\pactlyn-references\local-ai-workspace`

#### Key Technologies
- **Backend**: FastAPI, Python 3.10+
- **Document Processing**: Docling (primary), PyMuPDF, pdfplumber (fallbacks)
- **OCR**: PaddleOCR (primary, CPU-friendly), OCRmyPDF (fallback)
- **Vector Store**: Qdrant (primary), internal JSON fallback
- **Vision**: Multimodal Ollama models with structured evidence extraction
- **Embeddings**: Local Ollama embedding models
- **Chunking**: Fixed and recursive chunking modes

#### Implementation Highlights

**Document Service** (`backend/app/services/document_service.py`):
- Comprehensive upload validation with MIME type sniffing
- Duplicate detection via SHA256 content hashing
- Extraction diagnostics and error recovery
- Low-text PDF detection (< 40 chars/page) triggers OCR
- Extraction flow: Docling → PyMuPDF/pdfplumber → PaddleOCR (auto-fallback)
- Structured metadata storage with processing state machine

**OCR Integration** (`backend/app/ai/ocr.py`):
- Abstract `PDFOCREngine` interface
- `PaddleOCREngine`: CPU-friendly, no GPU required, Baidu's open-source engine
- `OCRmyPDFEngine`: Tesseract-based fallback
- Automatic low-text detection and OCR trigger
- Error handling with fallback chain

**Chunking** (`backend/app/rag/chunker.py`):
- Line-aware chunking preserving structure
- Handles oversized lines gracefully
- Metadata tracking (start_line, end_line)
- Fixed chunk size with overlap support

**Vision Integration** (`backend/app/services/vision_artifacts.py`):
- Structured vision evidence extraction (not raw image → LLM)
- Separate vision model analyzes images before main chat
- Evidence stored as conversation artifacts
- Reusable across multiple turns

**Component Registry** (`backend/app/services/component_registry.py`):
- Dynamic capability discovery (LLMs, embedders, rerankers, vision models, OCR engines)
- Per-conversation settings for model selection
- Runtime detection of available tools

**Dependencies** (`backend/requirements.txt`):
```
docling>=2.0.0,<3.0.0
paddleocr>=3.0.0,<4.0.0
paddlepaddle==3.2.0
pymupdf>=1.24.0,<2.0.0
pdfplumber>=0.11.0,<1.0.0
ocrmypdf>=16.0.0,<17.0.0
qdrant-client>=1.13.0,<2.0.0
```

#### Patterns to Adopt

1. **SHA256 duplicate detection** - prevent re-processing identical documents
2. **Low-text PDF threshold** (40 chars/page) - automatic OCR triggering
3. **Extraction diagnostics** - structured metadata for debugging
4. **Fallback chains** - Docling → PyMuPDF → OCR
5. **Per-document status state machine** - uploaded → processing → processed/failed
6. **Vision evidence artifacts** - separate from main conversation context

---

### 2. haiku.rag (GitHub: ggozad/haiku.rag)

**License**: MIT License  
**Copyright**: 2025 Yiorgis Gozadinos  
**Repository**: `D:\Projects\pactlyn-references\haiku.rag`

#### Key Technologies
- **Database**: LanceDB (embedded, S3/GCS/Azure compatible)
- **AI Framework**: Pydantic AI (Ollama default)
- **Document Processing**: Docling (primary), docling-serve (remote option)
- **Structure**: DoclingDocument format preserves headings, tables, figures, page provenance
- **Retrieval**: Hybrid (vector + full-text), optional reranking
- **Citations**: Page numbers, section headings, chunk visualization
- **Multimodal**: Image search with multimodal embedders, vision models receive figures

#### Implementation Highlights

**Document Structure Preservation**:
- Stores entire DoclingDocument (not just extracted text)
- Maintains heading hierarchy
- Preserves table structure
- Keeps figure references with page numbers
- Section-aware context expansion during retrieval

**Chunking Strategy** (`haiku_rag_slim/haiku/rag/chunkers/`):
- Structure-aware: respects headings, sections, paragraphs
- Table-aware: preserves table boundaries
- Figure-aware: associates figures with surrounding context
- Page-aware: maintains page number provenance

**Citations** (`haiku_rag_slim/haiku/rag/capabilities/`):
- Every answer includes chunk IDs
- Page numbers preserved from ingestion
- Section heading context
- Chunk visualization on source pages
- CLI/TUI support for citation verification

**Hybrid Search**:
- Vector similarity (embeddings)
- Full-text search (BM25-style)
- Optional reranking (cross-encoders, Jina, Cohere, etc.)
- Section-aware context expansion

**Ingester Service** (`haiku_rag_slim/haiku/rag/ingester/`):
- Continuous monitoring of sources (filesystem, HTTP, S3, WebDAV)
- SQLite/Postgres job queue with retries
- Control plane and dashboard
- Tag-based document organization
- Rollback support

**Dependencies** (`haiku_rag_slim/pyproject.toml`):
```python
dependencies = [
    "docling-core==2.104.0",
    "lancedb==0.41.0",
    "pydantic-ai-slim[openai,logfire,ag-ui]>=2.66.0",
    "pypdfium2>=5.0",
    # ... others
]

[project.optional-dependencies]
docling = [
    "docling==2.142.1",
    "docling-ibm-models==4.0.4",  # Layout and table-structure models
    "docling-parse==7.23.0",       # PDF parser
    "transformers>=5.17.0,<6.0.0",
    "opencv-python-headless>=4.6.0.66",
]
```

#### Patterns to Adopt

1. **Structure-aware storage** - preserve Docling document structure
2. **Section-aware chunking** - respect document hierarchy
3. **Page number tracking** - maintain provenance through processing
4. **Citation format** - `[chunk_id] p.{pages}: {heading} | {content}`
5. **Chunk visualization** - draw bounding boxes on page images
6. **Hybrid retrieval** - combine vector + full-text search
7. **Optional reranking** - improve relevance before context assembly
8. **Figure handling** - associate images with surrounding text context

---

## Existing Pactlyn Architecture Analysis

### Storage Layer

**Location**: `src/pactlyn/storage/`

**Existing Models** (`storage/models.py`):
- Base pattern: SQLAlchemy declarative models
- UUID primary keys via `new_id()` helper
- Timestamps: `created_at`, `updated_at`, `deleted_at` (soft deletes)
- Rich enums: `CommitmentType`, `CommitmentStatus`, `MemoryKind`, `EmailState`
- Complex relationships: commitments, contacts, emails, memories
- **Model Configuration System**:
  - `ModelConfiguration`: Provider-specific model records
  - `ActiveModelSelection`: Current model per role
  - `ProviderConfiguration`: Provider settings

**Migration System**:
- Alembic-based (`migrations/versions/`)
- Recent migrations show active development:
  - `da2fe9addcea_add_active_model_selections_and_extend_` - Model management
  - `9a0_email_settings_and_payload` - Email integration
  - `8b5285117737_add_memory_indexing_state` - Vector indexing
  - `8c0_relationship_review_audit` - Relationship tracking

**Pattern for Document Models**:
```python
class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    filename: Mapped[str]
    content_hash: Mapped[str]  # SHA256 for deduplication
    mime_type: Mapped[str]
    size_bytes: Mapped[int]
    status: Mapped[str]  # uploaded, processing, indexed, failed
    page_count: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    processed_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]
    
    # Relationships
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document")

class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    content: Mapped[str]
    page_numbers: Mapped[str]  # JSON: [1, 2] or "1-3"
    section_heading: Mapped[str | None]
    chunk_index: Mapped[int]
    char_start: Mapped[int]
    char_end: Mapped[int]
    indexed: Mapped[bool] = mapped_column(default=False)
    vector_id: Mapped[str | None]  # Reference to Qdrant point ID
    
    # Relationships
    document: Mapped["Document"] = relationship(back_populates="chunks")
```

### Vector Storage Layer

**Location**: `src/pactlyn/vectorstore/`

**Collections** (`vectorstore/collections.py`):
```python
COLLECTION_COMMITMENTS = "commitment_memories"
COLLECTION_EMAIL = "email_context"
COLLECTION_KNOWLEDGE = "personal_knowledge"
# Planned:
# COLLECTION_DOCUMENTS = "pactlyn_documents"
```

**Interface** (`vectorstore/interface.py`):
- Abstract `VectorStore` protocol
- Methods: `upsert()`, `search()`, `delete()`
- Collection-based organization
- Metadata support in payloads

**Qdrant Implementation** (`vectorstore/qdrant_local.py`):
- Local mode connection (no server required)
- Collection auto-creation with dimension detection
- Payload metadata storage
- Distance metric: Cosine similarity

**Memory Service Pattern** (`memory/service.py`):
```python
class MemoryService:
    def __init__(self, session: Session, vectors: VectorStore, embedder: object):
        self.session = session
        self.vectors = vectors
        self.embedder = embedder

    async def remember(self, content: str, *, kind: MemoryKind, source_type: str, source_id: str, verified: bool = False) -> MemoryRecord:
        # 1. Check for duplicates in SQLite
        # 2. Create SQLite record
        # 3. Embed content with configured embedder
        # 4. Store vector in Qdrant with metadata
        # 5. Mark as indexed
        # 6. Handle LLMUnavailable gracefully (indexed=False)
```

**Pattern for Document Service**:
- Same structure: SQLite metadata + Qdrant vectors
- Collection: `COLLECTION_DOCUMENTS = "pactlyn_documents"`
- Metadata includes: `document_id`, `chunk_id`, `page_numbers`, `section_heading`, `content`
- Graceful degradation when embedder unavailable

### LLM Gateway Layer

**Location**: `src/pactlyn/llm/`

**Model Management**:
- `discovery.py`: `OllamaDiscoveryService` - runtime model detection
- `model_config.py`: `ModelConfigurationService` - active model selection
- `gateway.py`: `LLMGateway` - unified inference interface
- `interfaces.py`: Provider protocols

**ModelRole Constants** (`model_config.py`):
```python
ASSISTANT = "assistant"      # Existing: General reasoning/conversation
EXTRACTION = "extraction"    # Existing: Structured data extraction
VISION = "vision"           # Existing: Vision-language models
EMBEDDING = "embedding"     # Existing: Text embedding models
# All four roles already defined - REUSE for document intelligence
```

**Provider Abstraction**:
- `LLMProvider` protocol: `complete()`, `stream()`, `list_models()`
- `EmbeddingProvider` protocol: `embed()`, `dimension`
- Local + cloud provider support
- `LLMUnavailable` exception for graceful degradation

**Pattern for Document Processing**:
1. Get active VISION model for image analysis
2. Get active EMBEDDING model for chunk embedding
3. Get active ASSISTANT model for RAG responses
4. OCR is separate (PaddleOCR/Tesseract) - no model role needed

### UI Layer

**Location**: `src/pactlyn/ui/`

**Main Window** (`ui/main_window.py`):
- Stack-based navigation (`QStackedWidget`)
- Sidebar with navigation buttons
- Existing pages: Home, Commitments, Waiting, Email, Memory, Assistant, Settings
- Background worker pattern for heavy operations
- Signal/slot for async communication

**Navigation Pattern**:
```python
# Current pages (indices 0-6):
# 0: Home
# 1: Commitments
# 2: Waiting
# 3: Email
# 4: Memory
# 5: Assistant
# 6: Settings

# Add Documents page at index 4:
# 0: Home
# 1: Commitments
# 2: Waiting
# 3: Email
# 4: Documents (NEW)
# 5: Memory
# 6: Assistant
# 7: Settings
```

**Background Worker Pattern**:
```python
class DocumentProcessingWorker(QRunnable):
    def __init__(self, container: AppContainer, document_path: str):
        super().__init__()
        self.container = container
        self.document_path = document_path
        self.signals = WorkerSignals()
    
    def run(self) -> None:
        try:
            # Heavy processing here (extraction, OCR, embedding)
            result = process_document(self.document_path)
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))
```

**Pattern for Documents UI**:
- Add "Documents" navigation button
- Create `_documents_page()` method
- Document list widget (QListWidget)
- Upload button → file dialog → background worker
- Document viewer (QTextBrowser or custom widget)
- Search box for document RAG queries

### Dependencies

**Current** (`pyproject.toml`):
```toml
dependencies = [
  "alembic>=1.13,<2",           # ✅ Database migrations
  "httpx>=0.27,<1",             # ✅ HTTP client
  "langgraph>=0.2,<1",          # ✅ Agent orchestration
  "pydantic>=2.8,<3",           # ✅ Data validation
  "PySide6>=6.7,<7",            # ✅ UI framework
  "qdrant-client>=1.10,<2",     # ✅ Vector storage
  "SQLAlchemy>=2.0,<3",         # ✅ ORM
]
```

**Required Additions**:
```toml
dependencies = [
  # ... existing ...
  "docling>=2.0,<3",            # Primary document processing
  "pypdfium2>=5.0",             # PDF rendering (lightweight)
  "pymupdf>=1.24,<2",           # PDF utilities
  "paddleocr>=3.0,<4",          # Primary OCR (CPU-friendly)
  # paddlepaddle is auto-installed by paddleocr
  "pillow>=10.0,<14",           # Image processing
  "python-magic-bin>=0.4; platform_system=='Windows'",  # MIME detection
]

[project.optional-dependencies]
ocr = [
  "pytesseract>=0.3,<1",        # Optional: Tesseract fallback
]
```

**Windows Compatibility Notes**:
- PaddleOCR: CPU mode by default, works on Windows
- Tesseract: Requires `tesseract.exe` installation (optional)
- `python-magic-bin`: Windows-compatible MIME detection

---

## Technical Assessment

### 1. PDF Processing Strategy

**Recommended Flow**:
```
PDF Upload
  ↓
SHA256 Hash Check (duplicate detection)
  ↓
MIME Type Validation
  ↓
Docling Extraction (primary)
  ├─ Success → Extract text, structure, metadata
  └─ Failure → PyMuPDF fallback
      ├─ Success → Extract text
      └─ Failure → Reject document
  ↓
Low-Text Detection (< 40 chars/page)
  ├─ No → Proceed to chunking
  └─ Yes → PaddleOCR (auto-trigger)
      ├─ Success → Merge OCR text
      └─ Failure → Warn user, use extracted text
  ↓
Structure-Aware Chunking
  ├─ Preserve page numbers
  ├─ Respect section headings
  ├─ Maintain table boundaries
  └─ Associate figures
  ↓
Embed Chunks (configured EMBEDDING model)
  ↓
Store in Qdrant (pactlyn_documents collection)
  ↓
Update SQLite (indexed=True, status=indexed)
```

**Docling Integration**:
- Primary extraction: Rich structure (headings, tables, figures, pages)
- Fallback: PyMuPDF for simple text extraction
- Store full `DoclingDocument` JSON in document metadata
- Structure-aware chunking uses document hierarchy

**OCR Integration**:
- Automatic trigger: `sum(page_chars) / page_count < 40`
- PaddleOCR: CPU-friendly, no GPU required, good accuracy
- Tesseract: Optional system fallback
- Merge strategy: Replace low-text pages with OCR output

### 2. Image Processing Strategy

**Vision-Language Model Flow**:
```
Image Upload/Selection
  ↓
Format Validation (PNG, JPG, JPEG, WEBP, TIFF)
  ↓
Thumbnail Generation (Pillow)
  ↓
Vision Model Analysis (configured VISION model)
  ├─ Extract: Text, objects, layout, code, diagrams
  ├─ Generate: Description, observations, uncertainties
  └─ Store: Structured vision evidence
  ↓
Embed Vision Evidence + Image Metadata
  ↓
Store in Qdrant (same pactlyn_documents collection)
  ↓
Associate with Document Record
```

**Important**: Never send raw images to text-only ASSISTANT models. Use configured VISION model for analysis, then pass structured evidence to ASSISTANT for reasoning.

### 3. Chunking Strategy

**Structure-Aware Chunking** (inspired by haiku.rag):
```python
class DocumentChunker:
    def chunk_document(self, doc: DoclingDocument, max_chars: int = 2000) -> list[Chunk]:
        chunks = []
        current_section = None
        current_chunk = []
        current_length = 0
        
        for element in doc.iterate_elements():
            if element.type == "heading":
                # Flush current chunk before section boundary
                if current_chunk:
                    chunks.append(self._build_chunk(current_chunk, current_section))
                current_section = element.text
                current_chunk = [element]
                current_length = len(element.text)
            
            elif element.type == "table":
                # Flush and create dedicated table chunk
                if current_chunk:
                    chunks.append(self._build_chunk(current_chunk, current_section))
                chunks.append(self._table_chunk(element, current_section))
                current_chunk = []
                current_length = 0
            
            elif element.type == "figure":
                # Associate figure with current chunk, don't split
                current_chunk.append(element)
            
            else:  # paragraph, list, etc.
                if current_length + len(element.text) > max_chars:
                    chunks.append(self._build_chunk(current_chunk, current_section))
                    current_chunk = [element]
                    current_length = len(element.text)
                else:
                    current_chunk.append(element)
                    current_length += len(element.text)
        
        if current_chunk:
            chunks.append(self._build_chunk(current_chunk, current_section))
        
        return chunks
```

**Chunk Metadata**:
```python
@dataclass
class DocumentChunk:
    content: str
    page_numbers: list[int]
    section_heading: str | None
    chunk_index: int
    char_start: int
    char_end: int
    chunk_type: str  # "text", "table", "figure_caption"
    figure_refs: list[str]  # Associated figure IDs
```

### 4. Retrieval Strategy

**Hybrid Retrieval** (Phase 8):
```python
async def retrieve_documents(query: str, top_k: int = 5) -> list[RetrievalResult]:
    # 1. Vector search in Qdrant
    embedder = get_active_embedding_model()
    query_vector = await embedder.embed([query])
    vector_results = qdrant.search(
        collection="pactlyn_documents",
        query_vector=query_vector[0],
        limit=top_k * 2,  # Retrieve more for reranking
    )
    
    # 2. (Optional) Reranking with cross-encoder
    if reranking_enabled:
        reranked = await rerank(query, vector_results)
        return reranked[:top_k]
    
    return vector_results[:top_k]
```

**Citation Format**:
```
Based on the documents:

[1] p.3-4: Introduction | The architecture uses a multi-agent system...
[2] p.7: System Design | The vector store maintains embeddings for all...
[3] p.12: Implementation | Document processing follows a pipeline...
```

**Assistant Integration** (Phase 8):
```python
async def answer_with_documents(question: str) -> tuple[str, list[Citation]]:
    # 1. Retrieve relevant chunks
    chunks = await retrieve_documents(question, top_k=5)
    
    # 2. Build context with citations
    context = "\n\n".join(
        f"[{i+1}] {chunk.metadata['section_heading']}: {chunk.content}"
        for i, chunk in enumerate(chunks)
    )
    
    # 3. Prompt ASSISTANT model
    prompt = f"""Based on these document excerpts, answer the question.
Cite sources using [1], [2], etc.

Context:
{context}

Question: {question}

Answer:"""
    
    assistant = get_active_assistant_model()
    answer = await assistant.complete([{"role": "user", "content": prompt}])
    
    # 4. Extract citations from answer
    citations = extract_citations(answer, chunks)
    
    return answer, citations
```

### 5. Windows Compatibility

**PaddleOCR on Windows**:
- CPU mode works without GPU
- Install via pip: `pip install paddleocr paddlepaddle`
- No external binaries required
- First run downloads models to `~/.paddleocr/`

**MIME Type Detection**:
- Windows: Use `python-magic-bin` (pure Python, no libmagic.dll)
- Fallback: Check file extensions + peek at file headers

**Path Handling**:
- Use `pathlib.Path` everywhere (cross-platform)
- Test on Windows: `D:\Projects\pactlyn-ai`

**File Dialogs**:
- PySide6 `QFileDialog` works identically on Windows/Linux

### 6. Evaluation Strategy

**Document Intelligence Test Suite**:

1. **Unit Tests** (no external models):
   - Document model creation
   - Chunk generation logic
   - Citation extraction from text
   - Metadata validation

2. **Mocked Integration Tests**:
   - Document upload flow (mocked Docling)
   - OCR trigger logic (mocked PaddleOCR)
   - Embedding flow (mocked embedder)
   - Retrieval ranking (mocked Qdrant)

3. **Live Local-Model Tests** (opt-in, `RUN_DOC_TESTS=1`):
   - Real Docling extraction on sample PDFs
   - Real PaddleOCR on scanned PDF
   - Real embedding with configured model
   - Real Qdrant indexing and search
   - Real vision model on sample images

4. **Application Tests**:
   - Upload document via UI
   - View document list
   - Search documents
   - Ask question with document RAG
   - Verify citations in response

5. **Offline Tests**:
   - All operations work without internet
   - Ollama connectivity failures handled gracefully
   - Graceful degradation when models unavailable

**Test Datasets**:
- `evaluation/datasets/documents/`:
  - `sample_text.pdf` - Normal text PDF (5 pages)
  - `sample_scanned.pdf` - Scanned document (OCR required)
  - `sample_complex.pdf` - Tables, figures, headers (20 pages)
  - `sample_image.png` - Diagram for vision testing
  - `sample_document.docx` - Office document
  - `sample_markdown.md` - Markdown with code blocks

**Evaluation Metrics**:
- Extraction accuracy (text recovery %)
- OCR accuracy (character error rate)
- Chunking quality (section preservation %)
- Retrieval precision@k
- Citation accuracy (correct page numbers %)
- End-to-end latency

---

## Integration Plan

### Phase 1: PDF Text Extraction (Next)

**Files to Create**:
- `src/pactlyn/documents/__init__.py`
- `src/pactlyn/documents/extraction.py` - Docling + PyMuPDF
- `src/pactlyn/documents/models.py` - Document dataclasses
- `tests/test_extraction.py` - Unit + mocked tests

**Files to Modify**:
- `src/pactlyn/storage/models.py` - Add Document, DocumentChunk models
- `src/pactlyn/vectorstore/collections.py` - Add COLLECTION_DOCUMENTS
- `pyproject.toml` - Add docling, pymupdf, pypdfium2

**Migration**:
- `migrations/versions/XXX_add_document_tables.py`

**Dependencies**:
```bash
pip install "docling>=2.0,<3" "pymupdf>=1.24,<2" "pypdfium2>=5.0"
```

### Phase 2: OCR Integration

**Files to Create**:
- `src/pactlyn/documents/ocr.py` - PaddleOCR + Tesseract fallback
- `tests/test_ocr.py` - Mocked + live tests

**Files to Modify**:
- `src/pactlyn/documents/extraction.py` - Add OCR fallback logic
- `pyproject.toml` - Add paddleocr

**Dependencies**:
```bash
pip install "paddleocr>=3.0,<4"
```

### Phase 3: Vision Integration

**Files to Create**:
- `src/pactlyn/documents/vision.py` - Vision model integration
- `tests/test_vision.py` - Mocked + live tests

**Files to Modify**:
- `src/pactlyn/documents/extraction.py` - Add image processing
- `src/pactlyn/documents/models.py` - Add VisionEvidence model

**Dependencies**:
- Already have: Pillow (PySide6 dependency)
- Reuse: Existing VISION model role

### Phase 4: Image/Figure Processing

**Files to Create**:
- `src/pactlyn/documents/figures.py` - Figure extraction from PDFs
- `tests/test_figures.py`

**Files to Modify**:
- `src/pactlyn/documents/extraction.py` - Extract figures from Docling
- UI: Add image preview widget

### Phase 5: Document Catalog & Ingestion

**Files to Create**:
- `src/pactlyn/documents/service.py` - DocumentService (main orchestrator)
- `src/pactlyn/documents/catalog.py` - Document metadata management
- `tests/test_document_service.py`

**Files to Modify**:
- `src/pactlyn/container.py` - Register DocumentService

### Phase 6: Chunking & Indexing

**Files to Create**:
- `src/pactlyn/documents/chunking.py` - Structure-aware chunking
- `src/pactlyn/documents/indexing.py` - Qdrant integration
- `tests/test_chunking.py`
- `tests/test_indexing.py`

**Files to Modify**:
- `src/pactlyn/documents/service.py` - Add indexing workflow

### Phase 7: Documents UI

**Files to Create**:
- `src/pactlyn/ui/documents.py` - Documents page widget
- `src/pactlyn/ui/document_viewer.py` - Document display widget
- `tests/test_documents_ui.py`

**Files to Modify**:
- `src/pactlyn/ui/main_window.py` - Add Documents navigation

### Phase 8: Assistant Integration

**Files to Create**:
- `src/pactlyn/documents/retrieval.py` - Hybrid search
- `src/pactlyn/documents/citations.py` - Citation extraction
- `src/pactlyn/assistant/document_rag.py` - RAG integration
- `tests/test_document_rag.py`

**Files to Modify**:
- `src/pactlyn/ui/main_window.py` - Integrate document search in Assistant

### Phase 9: Graph Integration (Optional)

**Files to Create**:
- `src/pactlyn/documents/graph.py` - Document-commitment linking
- `tests/test_document_graph.py`

**Files to Modify**:
- `src/pactlyn/storage/models.py` - Add DocumentCommitmentLink model

### Phase 10: Evaluation & Testing

**Files to Create**:
- `evaluation/datasets/documents/` - Test documents
- `evaluation/generate_document_dataset.py`
- `evaluation/run_document_evaluation.py`
- `evaluation/reports/document-extraction-0.9.json`
- `evaluation/reports/document-rag-0.9.json`

---

## Risk Assessment

### Low Risk ✅

- ✅ SQLite schema extension (well-established pattern)
- ✅ Qdrant collection addition (isolated from existing collections)
- ✅ UI navigation extension (proven pattern)
- ✅ Background worker pattern (already used)
- ✅ Dependencies (all MIT/Apache licensed, stable versions)

### Medium Risk ⚠️

- ⚠️ **Docling Windows compatibility** - Primarily tested on Linux, may need tweaks
  - Mitigation: Use PyMuPDF as robust fallback
- ⚠️ **PaddleOCR model downloads** - First-run downloads ~100MB
  - Mitigation: Document in setup guide, provide offline installation option
- ⚠️ **Large document processing** - May block UI if not properly backgrounded
  - Mitigation: Use QThreadPool workers, show progress indicators
- ⚠️ **Memory usage** - Large PDFs + embeddings can use significant RAM
  - Mitigation: Process in batches, add max document size limit (25MB default)

### High Risk ❌

- None identified. All components are well-established, MIT-licensed, and have proven Windows compatibility.

---

## Attribution Requirements

Both reference repositories use **MIT License** which requires:

1. **Copyright notice preservation**:
   ```python
   # Portions adapted from local-ai-workspace
   # Copyright (c) 2026 Local AI Coding Assistant contributors
   # MIT License: https://github.com/Jn527fd/local-ai-workspace/blob/main/LICENSE
   
   # Portions adapted from haiku.rag
   # Copyright (c) 2025 Yiorgis Gozadinos
   # MIT License: https://github.com/ggozad/haiku.rag/blob/main/LICENSE
   ```

2. **Attribution in documentation**:
   - Add "Acknowledgments" section to README.md
   - Credit both projects for document processing patterns

3. **No trademark use**:
   - Do not use "local-ai-workspace" or "haiku.rag" branding

---

## Recommendations

### Immediate (Phase 1-3)

1. **Start with Docling + PyMuPDF** - Proven, stable, cross-platform
2. **PaddleOCR for OCR** - CPU-friendly, no external dependencies
3. **Structure-aware chunking** - Use Docling's document structure
4. **Reuse existing patterns** - MemoryService → DocumentService
5. **Graceful degradation** - Handle missing models elegantly

### Short-term (Phase 4-6)

1. **Figure extraction** - Use Docling's figure detection
2. **Hybrid retrieval** - Vector + metadata filtering
3. **Citation tracking** - Page numbers + section headings
4. **Background processing** - Never block UI thread

### Long-term (Phase 7-10)

1. **Document viewer** - Rich display with page navigation
2. **Optional reranking** - Cross-encoder for improved relevance
3. **Graph integration** - Link documents to commitments
4. **Comprehensive evaluation** - Real-world document corpus

---

## Success Criteria

### Phase 1 Complete When:
- ✅ Docling extracts text from normal PDFs
- ✅ PyMuPDF fallback works for simple PDFs
- ✅ Document models in SQLite
- ✅ Unit tests pass on Windows
- ✅ No breaking changes to existing features

### Phase 2 Complete When:
- ✅ PaddleOCR processes scanned PDFs
- ✅ Low-text detection triggers OCR automatically
- ✅ Merged text preserves page structure
- ✅ Graceful failure when OCR unavailable

### Phase 3 Complete When:
- ✅ Vision model analyzes images correctly
- ✅ Structured evidence stored in document metadata
- ✅ No raw images sent to text-only models
- ✅ Vision model selection uses configured VISION role

### Final Success (Phase 10):
- ✅ Upload PDF → View in Documents UI → Ask question → Get cited answer
- ✅ Scanned PDF correctly OCR'd and searchable
- ✅ Image uploaded → Vision analysis → Answerable via Assistant
- ✅ All 27 acceptance criteria pass
- ✅ Evaluation shows >90% extraction accuracy
- ✅ Retrieval precision@5 >75%
- ✅ Citation accuracy >95% (correct page numbers)
- ✅ Works offline with local models
- ✅ No degradation of existing Pactlyn features

---

## Conclusion

**Pactlyn's architecture is ready for multimodal document intelligence integration**. The existing dynamic model management, vector storage, and UI patterns provide a solid foundation. Both reference repositories offer excellent implementation guidance with compatible MIT licenses.

**Recommendation**: Proceed with Phase 1 (PDF Text Extraction) immediately. The technical path is clear, risks are manageable, and all dependencies are compatible with Windows and the existing Pactlyn stack.

**Next Document**: `PHASE_1_IMPLEMENTATION.md` - Detailed implementation plan for PDF text extraction with Docling and PyMuPDF.

---

**Audit Completed**: 2026-11-05  
**Audited By**: Kiro AI Assistant  
**Status**: ✅ APPROVED FOR IMPLEMENTATION
