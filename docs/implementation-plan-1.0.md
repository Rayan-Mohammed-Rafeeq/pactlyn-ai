# Pactlyn 1.0 Implementation Plan: Multimodal Personal AI and Dynamic Model Management

**Status:** Planning phase  
**Created:** 2026-11-05  
**Goal:** Transform Pactlyn into a local-first multimodal personal AI assistant with dynamic model discovery, document intelligence, and intelligent local model management.

---

## 0. Reference Repository Analysis

### 0.1 haiku.rag (MIT License)

**Repository:** D:\Projects\pactlyn-references\haiku.rag  
**License:** MIT (Copyright 2025 Yiorgis Gozadinos)  
**Attribution requirement:** Include MIT license notice and copyright in any reused code

**Key technical learnings:**

1. **Docling Integration:**
   - Primary document extraction framework
   - Preserves structure: headings, tables, figures, page boundaries
   - Located in `haiku_rag_slim/haiku/rag/` package
   - Uses Pydantic AI for agent capabilities

2. **Multimodal Retrieval:**
   - Hybrid vector and full-text search
   - Reranking with multiple providers
   - Section-aware context expansion
   - Image search with multimodal embedders
   - Citation tracking with page numbers

3. **LanceDB Vector Store:**
   - haiku.rag uses LanceDB (we'll continue using Qdrant)
   - Demonstrates structure-aware chunking patterns
   - Shows metadata preservation for provenance

4. **Architecture Patterns:**
   - Document → DoclingDocument → structured chunks → vectors
   - Citations preserve page numbers, section headings
   - Sandboxed Python for counting/aggregation over documents
   - MCP server for Claude integration

**Reusable patterns (NOT direct code copy):**
- Document processing pipeline concept
- Citation and provenance tracking approach
- Structure-aware chunking methodology
- Multimodal retrieval orchestration

### 0.2 local-ai-workspace (MIT License)

**Repository:** D:\Projects\pactlyn-references\local-ai-workspace  
**License:** MIT (Copyright 2026 contributors)  
**Attribution requirement:** Include MIT license notice in any reused code

**Key technical learnings:**

1. **Ollama Model Discovery:**
   - `/components/capabilities` endpoint for dynamic discovery
   - Categorizes: LLMs, embedders, rerankers, vision models, OCR engines
   - Per-conversation model settings
   - Model capability validation before selection

2. **PDF Processing Stack:**
   - Docling (primary)
   - PyMuPDF (fallback)
   - pdfplumber (compatibility)
   - PaddleOCR for scanned/low-text PDFs
   - Automatic OCR fallback detection

3. **Vision Model Integration:**
   - Structured vision-evidence extraction
   - Separate vision model from chat model
   - Sequential loading for memory constraints
   - Image attachment support

4. **Document RAG Architecture:**
   - FastAPI backend
   - Qdrant vector storage (same as Pactlyn!)
   - Document upload, processing, chunking, embedding
   - Automatic context management
   - Source attribution with scores

5. **Dependencies (backend/requirements.txt):**
   ```
   fastapi>=0.115.0
   httpx>=0.28.0
   ocrmypdf>=16.0.0
   paddleocr>=3.0.0
   paddlepaddle==3.2.0
   docling>=2.0.0
   pdfplumber>=0.11.0
   pymupdf>=1.24.0
   chromadb>=1.5.9  # Pactlyn uses Qdrant instead
   qdrant-client>=1.13.0
   ```

**Reusable patterns:**
- Ollama API integration for model discovery
- Model capability classification
- PDF extraction fallback chain
- OCR automatic activation
- Vision model workflow
- Document processing pipeline

---

## 1. Current Pactlyn Architecture (Preserved)

### 1.1 Technology Stack
- **Language:** Python 3.11+ (3.12+ recommended)
- **Desktop:** PySide6
- **Agent orchestration:** LangGraph
- **Structured database:** SQLite + SQLAlchemy
- **Migrations:** Alembic
- **Vector database:** Qdrant (local mode)
- **Local inference:** Ollama
- **Email:** Resend
- **Project structure:** `uv` package manager

### 1.2 Existing Features (Must Continue Working)
- Commitments and personal facts
- Contact management
- Waiting-for relationships
- Persistent memory and knowledge graph
- Assistant interface
- Email Centre with approval workflow
- Proactive reminders
- Local-first operation
- Offline fallback

### 1.3 Current Data Models (src/pactlyn/storage/models.py)
- `UserProfile`, `UserPreference`
- `ModelConfiguration`, `ProviderConfiguration`
- `Commitment`, `CommitmentRelationship`, `CommitmentStatus`
- `Contact`, `ContactRelationship`
- `EmailThread`, `EmailMessage`, `EmailDraft`, `EmailSendAction`
- `MemoryRecord`, `MemorySource`, `MemoryFeedback`
- `AuditEvent`, `AgentRun`, `AgentCheckpoint`

### 1.4 Current Vector Collections (src/pactlyn/vectorstore/)
- Personal facts
- Commitments
- Contact memories
- Episodic memory

---

## 2. Implementation Phases

### Phase 1: Reference Repository Investigation ✓ COMPLETED
**Status:** Analysis complete  
**Duration:** Current session

**Deliverables:**
- [x] Inspect both reference repositories
- [x] Document licenses and attribution requirements
- [x] Identify reusable patterns (not code)
- [x] Map dependencies and compatibility
- [x] Create implementation plan

**Findings:**
- Both repos use MIT license - compatible with reuse
- haiku.rag: Docling + LanceDB patterns
- local-ai-workspace: Ollama discovery + Qdrant + PaddleOCR
- No conflicting architectural assumptions
- Clear separation: discovery vs. document processing

---

### Phase 2: Dynamic AI Model Management
**Status:** Not started  
**Priority:** Highest  
**Duration:** 3-5 sessions

#### 2.1 Ollama Model Discovery Service

**New module:** `src/pactlyn/llm/discovery.py`

```python
class OllamaDiscoveryService:
    """Discover and categorize locally installed Ollama models."""
    
    async def discover_models() -> ModelInventory
    async def get_model_details(model_name: str) -> ModelDetails
    async def categorize_model(model: ModelDetails) -> ModelCategory
    async def check_ollama_connection() -> ConnectionStatus
    async def refresh_inventory() -> ModelInventory
```

**Features:**
- Query Ollama API (`/api/tags`, `/api/show`)
- Retrieve: name, tag, digest, family, parameter size, quantization, context length, embedding dimensions
- Categorize: text/reasoning, vision-language, embedding, unknown
- Detect loaded models
- Connection status monitoring

#### 2.2 Model Capability Classification

**New module:** `src/pactlyn/llm/capabilities.py`

```python
class ModelCapability(StrEnum):
    TEXT_REASONING = "text_reasoning"
    VISION_LANGUAGE = "vision_language"
    EMBEDDING = "embedding"
    UNKNOWN = "unknown"

class ModelClassifier:
    """Classify models by capability using provider metadata."""
    
    def classify(model: ModelDetails) -> ModelCapability
    def is_compatible_for_task(model: str, task: TaskType) -> bool
    def validate_vision_support(model: str) -> bool
    def get_embedding_dimensions(model: str) -> int | None
```

#### 2.3 OCR Engine Detection

**New module:** `src/pactlyn/llm/ocr_detection.py`

```python
class OCREngine(StrEnum):
    PADDLEOCR = "paddleocr"
    TESSERACT = "tesseract"
    NONE = "none"

class OCRDetector:
    """Detect installed OCR engines."""
    
    def detect_available_engines() -> list[OCREngine]
    def check_paddleocr() -> bool
    def check_tesseract() -> bool
```

#### 2.4 Settings → AI Models UI

**New module:** `src/pactlyn/ui/model_settings.py`

**UI Components:**
- Ollama connection status indicator
- **Refresh Models** button
- Text model dropdown (populated dynamically)
- Vision model dropdown (populated dynamically)
- Embedding model dropdown (populated dynamically)
- OCR engine dropdown (populated dynamically)
- Model details display (size, parameters, context length)
- **Save Configuration** button
- Optional: **Download Model** interface

#### 2.5 Model Configuration Persistence

**Database extensions:**

```python
# Update existing ModelConfiguration in models.py
class ModelConfiguration(Base):
    # Add fields:
    model_type: Mapped[str]  # "text", "vision", "embedding"
    context_length: Mapped[int | None]
    parameter_count: Mapped[str | None]  # "7B", "3B"
    quantization: Mapped[str | None]  # "Q4_0"
    
class ActiveModelSelection(Base):
    """Currently active model for each purpose."""
    __tablename__ = "active_model_selections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    model_type: Mapped[str]  # "text", "vision", "embedding", "ocr"
    selected_model: Mapped[str]
    updated_at: Mapped[datetime]
```

**Alembic migration:**
- Create `active_model_selections` table
- Add new fields to `model_configurations`

#### 2.6 Assistant Model Selector

**Update:** `src/pactlyn/ui/main_window.py`

Add inline model dropdown to Assistant interface:
```python
# Conceptual:
# Model: [ Qwen2.5 7B ▼ ]
# Ask Pactlyn...
```

Dropdown populated from discovered text models.

#### 2.7 Embedding Model Migration Handler

**New module:** `src/pactlyn/vectorstore/migration.py`

```python
class EmbeddingMigrationService:
    """Handle embedding model changes safely."""
    
    async def check_dimension_compatibility(
        new_model: str,
        existing_collections: list[str]
    ) -> CompatibilityReport
    
    async def reindex_collection(
        collection: str,
        new_embedding_model: str,
        backup: bool = True
    ) -> ReindexResult
    
    async def validate_new_index(
        collection: str,
        sample_queries: list[str]
    ) -> ValidationResult
```

#### 2.8 Testing

**New tests:**
- `tests/llm/test_discovery.py` - Mock Ollama API responses
- `tests/llm/test_capabilities.py` - Model classification logic
- `tests/llm/test_ocr_detection.py` - OCR engine detection
- `tests/ui/test_model_settings.py` - UI interaction tests
- `tests/vectorstore/test_migration.py` - Embedding migration

**Test scenarios:**
- Ollama available vs. unavailable
- Models discovered correctly
- Incompatible model rejection
- Model configuration persistence
- Embedding dimension changes
- Reindex safety

---

### Phase 3: PDF Intelligence Foundation
**Status:** Not started  
**Duration:** 2-3 sessions

#### 3.1 Dependencies

**Add to pyproject.toml:**
```toml
[project.dependencies]
docling = "^2.0.0"
pymupdf = "^1.24.0"
pdfplumber = "^0.11.0"
paddleocr = "^3.0.0"
```

**Note:** PaddlePaddle CPU version requires special index
```bash
uv pip install paddlepaddle==3.2.0 --extra-index-url https://www.paddlepaddle.org.cn/packages/stable/cpu/
```

#### 3.2 PDF Extraction Service

**New module:** `src/pactlyn/documents/pdf_extractor.py`

```python
class PDFExtractor:
    """Extract structured content from PDFs using Docling."""
    
    async def extract(
        pdf_path: Path
    ) -> DocumentStructure
    
    async def extract_with_fallback(
        pdf_path: Path
    ) -> DocumentStructure
```

**DocumentStructure:**
- Pages with boundaries
- Headings and sections
- Paragraphs with context
- Tables with structure
- Figures with captions and bounding boxes
- Embedded images

#### 3.3 Fallback Chain

```
1. Docling (primary)
   ↓ (if fails or low text detected)
2. PyMuPDF
   ↓ (if still insufficient)
3. pdfplumber
```

---

### Phase 4: OCR Integration
**Status:** Not started  
**Duration:** 2 sessions

#### 4.1 OCR Service

**New module:** `src/pactlyn/documents/ocr_service.py`

```python
class OCRService:
    """Local OCR for scanned documents and images."""
    
    async def ocr_image(
        image_path: Path,
        engine: OCREngine = OCREngine.PADDLEOCR
    ) -> OCRResult
    
    async def ocr_pdf_page(
        pdf_path: Path,
        page_num: int
    ) -> OCRResult
    
    async def detect_scanned_pdf(
        pdf_path: Path
    ) -> bool
```

**OCRResult:**
- Extracted text
- Confidence scores
- Bounding boxes
- Language detection
- Processing metadata

#### 4.2 Automatic OCR Activation

Trigger OCR when:
- PDF text extraction yields < 50 words per page
- User uploads image file (.png, .jpg, .webp, .tiff)
- Explicit OCR request

---

### Phase 5: Vision Model Integration
**Status:** Not started  
**Duration:** 2-3 sessions

#### 5.1 Vision Service

**New module:** `src/pactlyn/llm/vision.py`

```python
class VisionService:
    """Process images using dynamically selected vision models."""
    
    async def analyze_image(
        image_path: Path,
        query: str | None = None,
        model: str | None = None  # Uses selected vision model if None
    ) -> VisionAnalysis
    
    async def extract_diagram_description(
        image_path: Path
    ) -> str
    
    async def extract_table_from_image(
        image_path: Path
    ) -> TableStructure
```

**VisionAnalysis:**
- Description
- Extracted text
- Identified objects
- Chart/diagram understanding
- Table structure
- Confidence scores

#### 5.2 Sequential Model Loading

**New module:** `src/pactlyn/llm/model_manager.py`

```python
class ModelResourceManager:
    """Coordinate model loading for memory-constrained hardware."""
    
    async def request_model(
        model_name: str,
        task_id: str
    ) -> ModelLock
    
    async def release_model(model_name: str, task_id: str) -> None
    
    def get_loaded_models() -> list[str]
    
    def estimate_memory_available() -> int
```

---

### Phase 6: Document Ingestion Pipeline
**Status:** Not started  
**Duration:** 3-4 sessions

#### 6.1 Database Extensions

**New models in models.py:**

```python
class DocumentStatus(StrEnum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    OCR_PROCESSING = "ocr_processing"
    VISION_PROCESSING = "vision_processing"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(500))
    file_hash: Mapped[str] = mapped_column(String(64), unique=True)
    file_type: Mapped[str] = mapped_column(String(50))
    file_size: Mapped[int] = mapped_column(Integer)
    upload_path: Mapped[str] = mapped_column(String(1000))
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus))
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(80))
    embedding_model: Mapped[str] = mapped_column(String(200))
    embedding_dimension: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_type: Mapped[str] = mapped_column(String(80))  # "text", "table", "figure"
    content: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bounding_box: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    vector_id: Mapped[str] = mapped_column(String(100))

class DocumentFigure(Base):
    __tablename__ = "document_figures"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_id: Mapped[str] = mapped_column(ForeignKey("document_chunks.id", ondelete="CASCADE"))
    figure_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    caption: Mapped[str] = mapped_column(Text, default="")
    image_path: Mapped[str] = mapped_column(String(1000))
    vision_description: Mapped[str] = mapped_column(Text, default="")
    vision_model: Mapped[str] = mapped_column(String(200))
    page_number: Mapped[int] = mapped_column(Integer)
```

#### 6.2 Document Processing Service

**New module:** `src/pactlyn/documents/processor.py`

```python
class DocumentProcessor:
    """Orchestrate document ingestion pipeline."""
    
    async def process_document(
        file_path: Path,
        embedding_model: str
    ) -> Document
    
    async def validate_file(file_path: Path) -> ValidationResult
    
    async def compute_file_hash(file_path: Path) -> str
    
    async def check_duplicate(file_hash: str) -> Document | None
```

#### 6.3 Structure-Aware Chunking

**New module:** `src/pactlyn/documents/chunker.py`

```python
class DocumentChunker:
    """Chunk documents preserving structure."""
    
    def chunk_text(
        content: str,
        page_number: int,
        section_title: str | None
    ) -> list[TextChunk]
    
    def chunk_table(
        table: TableStructure,
        page_number: int
    ) -> TableChunk
    
    def prepare_figure_chunk(
        figure: FigureExtraction,
        vision_description: str
    ) -> FigureChunk
```

#### 6.4 Background Processing

**New module:** `src/pactlyn/documents/worker.py`

```python
class DocumentWorker:
    """Background async document processing."""
    
    async def start_processing(document_id: str) -> None
    
    async def update_progress(
        document_id: str,
        status: DocumentStatus
    ) -> None
```

Integrate with existing PySide6 async patterns.

---

### Phase 7: Qdrant Document Collections
**Status:** Not started  
**Duration:** 2 sessions

#### 7.1 New Collection

**Collection name:** `pactlyn_documents_v1`

**Vector payload schema:**
```python
{
    "document_id": str,
    "chunk_id": str,
    "chunk_type": str,  # "text", "table", "figure"
    "filename": str,
    "file_hash": str,
    "page_number": int | None,
    "section_title": str | None,
    "content": str,
    "embedding_model": str,
    "embedding_dimension": int,
    "bounding_box": dict | None,
    "figure_reference": str | None,
    "table_reference": str | None,
    "extraction_method": str,
    "created_at": str
}
```

#### 7.2 Indexing Service

**New module:** `src/pactlyn/vectorstore/document_indexer.py`

```python
class DocumentIndexer:
    """Index documents in Qdrant."""
    
    async def index_document(
        document: Document,
        chunks: list[DocumentChunk]
    ) -> IndexResult
    
    async def delete_document(document_id: str) -> None
    
    async def reindex_document(document_id: str) -> IndexResult
```

#### 7.3 Separate Collections

Maintain separation:
- `pactlyn_documents_v1` - Documents
- Existing collections - Personal facts, commitments, contacts, episodic memory

Never mix document vectors with personal memory vectors.

---

### Phase 8: Documents Desktop UI
**Status:** Not started  
**Duration:** 3-4 sessions

#### 8.1 New UI Module

**New file:** `src/pactlyn/ui/documents_view.py`

**Components:**
- Documents library (grid/list view)
- Upload button and drag-drop zone
- Processing status indicators
- Document preview pane
- Search and filter
- Actions: Reprocess, Reindex, Delete

#### 8.2 Document Viewer

**New file:** `src/pactlyn/ui/document_viewer.py`

**PDF Viewer features:**
- Page navigation
- Zoom controls
- Search within document
- Extracted text overlay
- Table highlighting
- Figure preview
- Citation navigation (click citation → jump to page)

**Image Viewer features:**
- Zoom and pan
- OCR results overlay
- Vision description display
- Bounding boxes visualization

#### 8.3 Integration with Main Window

**Update:** `src/pactlyn/ui/main_window.py`

Add "Documents" tab alongside:
- Dashboard
- Commitments
- Contacts
- Memory
- Email
- Settings

---

### Phase 9: Multimodal RAG in Assistant
**Status:** Not started  
**Duration:** 3-4 sessions

#### 9.1 Retrieval Service

**New module:** `src/pactlyn/rag/document_retrieval.py`

```python
class DocumentRetriever:
    """Retrieve relevant document chunks."""
    
    async def search(
        query: str,
        top_k: int = 5,
        filters: dict | None = None
    ) -> list[RetrievedChunk]
    
    async def hybrid_search(
        query: str,
        vector_weight: float = 0.7,
        fts_weight: float = 0.3
    ) -> list[RetrievedChunk]
```

#### 9.2 Citation Service

**New module:** `src/pactlyn/rag/citations.py`

```python
class CitationTracker:
    """Track and validate citations."""
    
    def extract_citations(
        answer: str,
        retrieved_chunks: list[RetrievedChunk]
    ) -> list[Citation]
    
    def validate_citations(
        citations: list[Citation],
        retrieved_chunks: list[RetrievedChunk]
    ) -> ValidationResult
    
    def format_citation(citation: Citation) -> str
```

**Citation format:**
```
Source: document_name.pdf
Page: 14
Section: Neural Networks
Chunk: chunk_id_12345
```

#### 9.3 Assistant Integration

**Update:** `src/pactlyn/agents/assistant.py`

Add document RAG capability:
1. Detect document-related queries
2. Retrieve relevant chunks
3. Include chunks in LangGraph context
4. Generate grounded answer
5. Extract and validate citations
6. Return answer with clickable citations

**Query examples:**
- "Summarize my uploaded notes on inheritance"
- "What does the diagram on page 8 show?"
- "Find the deadline mentioned in project_brief.pdf"
- "Compare the two uploaded PDFs"

---

### Phase 10: Knowledge Graph Integration
**Status:** Not started  
**Duration:** 2-3 sessions

#### 10.1 Document Entities

**New models:**

```python
class DocumentEntity(Base):
    __tablename__ = "document_entities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    entity_type: Mapped[str] = mapped_column(String(80))  # "person", "concept", "date", "event"
    entity_value: Mapped[str] = mapped_column(String(500))
    confidence: Mapped[float] = mapped_column(default=0.0)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

class DocumentRelationship(Base):
    __tablename__ = "document_relationships"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    relationship_type: Mapped[str] = mapped_column(String(120))
    target_type: Mapped[str] = mapped_column(String(80))  # "commitment", "contact", "document"
    target_id: Mapped[str] = mapped_column(String(36))
    evidence: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(default=0.0)
```

#### 10.2 Graph Extension

Extend existing Memory graph with document nodes and relationships:

```
Document → CONTAINS → Figure
Document → CONTAINS → Table
Document → MENTIONS → Person (Contact)
Document → SUPPORTS → Commitment
Document → RELATED_TO → Document
```

Only create validated, user-confirmed relationships.

#### 10.3 Personal Memory Integration

When user says:
- "Remember that my exam is on December 18"
- "Create a commitment from this deadline"
- "Save the contact mentioned in this PDF"

Extract candidate, show source document/page, confirm with user, create personal fact or commitment with document provenance.

---

### Phase 11: Evaluation and Testing
**Status:** Not started  
**Duration:** 2-3 sessions

#### 11.1 Test Datasets

**Create:** `evaluation/datasets/documents-1.0.json`

Test cases:
- Native PDFs (text-based)
- Scanned PDFs
- Mixed PDFs
- Multi-page documents
- Documents with tables
- Documents with diagrams
- Images (screenshots, photos)
- Handwritten notes (if OCR supports)

#### 11.2 Evaluation Metrics

**New script:** `evaluation/run_1_0_evaluation.py`

Measure:
- Text extraction quality
- OCR accuracy
- Table extraction accuracy
- Vision description relevance
- Retrieval Recall@5 and Precision@5
- Citation accuracy
- Answer correctness
- Abstention accuracy
- Processing latency
- Model latency
- Memory usage (RAM, VRAM)

#### 11.3 Model Discovery Tests

Verify:
- Ollama models discovered correctly
- Model capabilities classified properly
- Incompatible models rejected
- Selected model actually used for inference
- Model settings persist across restarts
- Embedding changes trigger safe reindexing
- Model switching doesn't corrupt data

#### 11.4 Integration Tests

Test complete workflows:
- Upload PDF → Process → Index → Query → Cited answer
- Upload image → OCR → Index → Query → Answer
- Change embedding model → Reindex → Verify integrity
- Offline operation (after model setup)
- Model unavailable → Clear error → Fallback option

---

## 3. Technical Specifications

### 3.1 New Dependencies

**Add to pyproject.toml:**
```toml
[project.dependencies]
# Existing dependencies...
docling = "^2.0.0"
pymupdf = "^1.24.0"
pdfplumber = "^0.11.0"
paddleocr = "^3.0.0"
pillow = "^11.0.0"  # Image processing
python-magic = "^0.4.27"  # File type detection
```

**Special installation notes:**
- PaddlePaddle requires extra index for Windows CPU version
- Tesseract is optional system binary (not Python package)

### 3.2 File Structure Extensions

```
src/pactlyn/
├── documents/           # NEW
│   ├── __init__.py
│   ├── processor.py     # Main document processor
│   ├── pdf_extractor.py # PDF extraction (Docling, PyMuPDF, pdfplumber)
│   ├── ocr_service.py   # Local OCR (PaddleOCR, Tesseract)
│   ├── chunker.py       # Structure-aware chunking
│   └── worker.py        # Background processing
├── llm/
│   ├── discovery.py     # NEW: Ollama model discovery
│   ├── capabilities.py  # NEW: Model capability classification
│   ├── ocr_detection.py # NEW: OCR engine detection
│   ├── vision.py        # NEW: Vision model integration
│   └── model_manager.py # NEW: Resource management
├── vectorstore/
│   ├── document_indexer.py  # NEW: Document-specific indexing
│   └── migration.py         # NEW: Embedding migration
├── rag/
│   ├── document_retrieval.py  # NEW: Document RAG
│   └── citations.py           # NEW: Citation tracking
├── ui/
│   ├── model_settings.py      # NEW: AI Models settings
│   ├── documents_view.py      # NEW: Documents library
│   └── document_viewer.py     # NEW: Document viewer
```

### 3.3 Database Migrations

**Create Alembic migrations for:**
1. `active_model_selections` table
2. `documents` table
3. `document_chunks` table
4. `document_figures` table
5. `document_entities` table
6. `document_relationships` table
7. Extensions to `model_configurations`

### 3.4 Configuration

**New settings in Settings → AI Models:**
- Ollama endpoint (default: http://127.0.0.1:11434)
- Selected text model
- Selected vision model
- Selected embedding model
- Selected OCR engine
- Model refresh interval
- Context length preferences
- Memory management settings

**New settings in Settings → Documents:**
- Upload size limit (default: 25 MB)
- Chunk size (default: 2000 chars)
- Max chunks per document (default: 500)
- Auto-OCR threshold (default: 50 words/page)
- Vision processing enabled
- Reindex on model change (default: ask)

---

## 4. Security and Privacy

### 4.1 Local-First Principles

- All document processing happens locally
- No automatic cloud uploads
- No silent fallback to cloud models
- Explicit user consent for any cloud operation
- Documents stored in `~/.local/share/pactlyn/documents/`
- Vectors remain in local Qdrant

### 4.2 File Security

- SHA-256 file hashing for deduplication
- File type validation (magic numbers, not just extension)
- Upload size limits
- Path traversal protection
- Malformed file handling
- Decompression bomb protection
- Sandboxed processing

### 4.3 Prompt Injection Protection

- Sanitize extracted text before embedding
- Validate citations before display
- Separate user queries from document content in context
- No automatic code execution from documents

---

## 5. Windows Compatibility

### 5.1 Current Development Environment
- **OS:** Windows 10/11
- **Shell:** PowerShell
- **GPU:** NVIDIA RTX 4050 Laptop (6 GB VRAM)
- **System RAM:** 24 GB

### 5.2 Windows-Specific Considerations

**Path handling:**
- Use `pathlib.Path` everywhere
- Windows path separators (`\\` vs `/`)
- Case-insensitive filesystem

**Dependencies:**
- PaddlePaddle CPU version for Windows
- Tesseract binary installation (optional)
- CUDA drivers for GPU acceleration (already installed)

**PySide6:**
- Native Windows UI integration
- File dialogs use Windows native dialogs
- Drag-and-drop support

### 5.3 Linux Compatibility

Must remain compatible with Linux for future deployment:
- Use cross-platform paths
- No Windows-only system calls
- Test on both Windows (development) and Linux (CI/deployment)

---

## 6. Performance and Resource Management

### 6.1 Target Hardware Constraints

**Current machine:**
- 6 GB VRAM (RTX 4050)
- 24 GB system RAM
- Can run Qwen2.5 7B
- Can run Qwen2.5-VL 3B
- Sequential loading required for multiple models

**General users:**
- May have less VRAM (4 GB)
- May be CPU-only
- Model size matters

### 6.2 Resource Management Strategies

**Model loading:**
- Load text model for chat
- Load vision model only when needed
- Load embedding model for batch processing
- Unload models when idle (configurable keep-alive)
- Never load incompatible combinations

**Document processing:**
- Async background workers
- Process one document at a time
- Chunk large documents
- Batch embeddings (configurable batch size)
- Progress indicators

**Memory efficiency:**
- Stream large files
- Process page-by-page for PDFs
- Cache OCR results
- Reuse vision descriptions
- Cleanup temporary files

### 6.3 Performance Targets

- Document upload response: < 1 second (validation + queue)
- PDF extraction: < 30 seconds for 50-page PDF
- OCR processing: < 5 seconds per page
- Vision analysis: < 10 seconds per image
- Embedding: < 1 second per chunk (batched)
- RAG query: < 3 seconds (retrieval + generation)
- UI responsiveness: No freezing during processing

---

## 7. Offline Operation

### 7.1 Offline-Capable Features

After initial setup (models downloaded):
- Document upload and validation
- PDF extraction (Docling, PyMuPDF, pdfplumber)
- OCR (PaddleOCR)
- Vision analysis (local Qwen2.5-VL)
- Embedding (local nomic-embed-text)
- Qdrant indexing (local mode)
- RAG queries
- Assistant answers
- Model discovery (cached)

### 7.2 Online-Required Features

- Initial Ollama model downloads
- OpenRouter queries (explicit opt-in)
- Email sending (Resend)
- Model metadata refresh (optional)

### 7.3 Graceful Degradation

When offline:
- Use cached model list
- Show "Offline mode" indicator
- Disable model download UI
- Disable email sending
- Local features continue working
- No silent failures

---

## 8. Testing Strategy

### 8.1 Unit Tests

- Model discovery service (mocked Ollama API)
- Capability classification logic
- PDF extraction (sample PDFs)
- OCR service (sample images)
- Vision service (mocked vision model)
- Chunking logic
- Citation extraction
- Embedding migration

### 8.2 Integration Tests

- Complete document pipeline
- RAG end-to-end
- Model switching workflow
- Embedding model migration
- UI interactions (Qt test framework)

### 8.3 Evaluation Tests

- Retrieval quality
- Citation accuracy
- Answer correctness
- Model discovery accuracy
- Resource usage

### 8.4 Test Data

**Create test files:**
- `tests/fixtures/documents/sample.pdf` (text-based)
- `tests/fixtures/documents/scanned.pdf` (image-based)
- `tests/fixtures/documents/mixed.pdf` (text + images)
- `tests/fixtures/documents/tables.pdf` (structured tables)
- `tests/fixtures/images/diagram.png`
- `tests/fixtures/images/screenshot.png`
- `tests/fixtures/images/handwritten.jpg`

---

## 9. Documentation Plan

### 9.1 New Documentation Files

**Create:**
- `docs/model-management.md` - AI model discovery and selection
- `docs/model-selection.md` - Guide for choosing models
- `docs/document-intelligence.md` - Document processing architecture
- `docs/multimodal-rag.md` - Multimodal RAG implementation
- `docs/offline-documents.md` - Offline document processing
- `docs/validation-1.0.md` - 1.0 validation report

**Update:**
- `docs/architecture.md` - Add document and model management
- `docs/offline-mode.md` - Add document offline capabilities
- `README.md` - Add 1.0 features
- `docs/setup-linux.md` - Add new dependencies

### 9.2 Documentation Content

Each document should cover:
- Architecture and design decisions
- Implementation details
- Configuration options
- Usage examples
- Troubleshooting
- Limitations and known issues
- Future improvements

### 9.3 API Documentation

Document:
- `OllamaDiscoveryService` API
- `DocumentProcessor` API
- `DocumentRetriever` API
- `VisionService` API
- UI widget APIs

---

## 10. Acceptance Criteria

### 10.1 Dynamic Model Management ✓

User can:
- [ ] Open Settings → AI Models
- [ ] See Ollama connection status
- [ ] See list of installed models with details
- [ ] Refresh model list
- [ ] Select text model from dropdown
- [ ] Select vision model from dropdown
- [ ] Select embedding model from dropdown
- [ ] Select OCR engine from dropdown
- [ ] Save model configuration
- [ ] Restart Pactlyn and see saved selections
- [ ] Change assistant model inline
- [ ] Download new model (optional)

System:
- [ ] Discovers models via Ollama API (not shell commands)
- [ ] Classifies models correctly
- [ ] Rejects incompatible model selections
- [ ] Persists selections to SQLite
- [ ] Uses selected model for actual inference
- [ ] Handles embedding model changes safely
- [ ] Triggers reindex when needed
- [ ] Shows clear warnings for missing models

### 10.2 Document Intelligence ✓

User can:
- [ ] Upload PDF document
- [ ] Upload image file
- [ ] Drag and drop files
- [ ] See processing progress
- [ ] View document library
- [ ] Preview document
- [ ] Navigate PDF pages
- [ ] See extracted tables
- [ ] See extracted figures
- [ ] Ask questions about documents
- [ ] Receive answers with citations
- [ ] Click citation to view source page
- [ ] Delete document and verify vectors removed
- [ ] Reprocess document
- [ ] Reindex after embedding model change

System:
- [ ] Validates files safely
- [ ] Detects duplicates via SHA-256
- [ ] Extracts PDF text (Docling primary, fallbacks)
- [ ] Runs OCR for scanned PDFs automatically
- [ ] Processes images with vision model
- [ ] Chunks with structure preservation
- [ ] Embeds with selected model
- [ ] Indexes in separate Qdrant collection
- [ ] Retrieves relevant chunks
- [ ] Generates grounded answers
- [ ] Validates citations
- [ ] Operates locally (offline after setup)

### 10.3 Offline Operation ✓

After initial setup:
- [ ] Process documents without internet
- [ ] Generate embeddings locally
- [ ] Query documents locally
- [ ] Get RAG answers locally
- [ ] Model discovery uses cached data
- [ ] No silent cloud fallback

### 10.4 Existing Features Still Work ✓

- [ ] Commitments
- [ ] Personal facts
- [ ] Contacts
- [ ] Memory
- [ ] Email Centre
- [ ] Assistant (existing features)
- [ ] Knowledge graph
- [ ] Reminders

---

## 11. Risk Mitigation

### 11.1 Technical Risks

**Risk:** Model discovery fails  
**Mitigation:** Graceful error handling, use cached list, clear error messages

**Risk:** Large PDFs crash system  
**Mitigation:** File size limits, streaming, pagination, memory monitoring

**Risk:** OCR quality insufficient  
**Mitigation:** Multiple OCR engines, confidence scores, user verification option

**Risk:** Embedding model change corrupts index  
**Mitigation:** Versioned collections, backups before reindex, validation after

**Risk:** VRAM insufficient for models  
**Mitigation:** Sequential loading, clear warnings, CPU fallback, model size display

**Risk:** Windows/Linux compatibility breaks  
**Mitigation:** Cross-platform paths, test both platforms, no OS-specific APIs

### 11.2 UX Risks

**Risk:** Model selection too complex  
**Mitigation:** Smart defaults, clear categorization, help text

**Risk:** Processing too slow  
**Mitigation:** Background workers, progress indicators, cancellation option

**Risk:** Citations confusing  
**Mitigation:** Clear format, clickable navigation, preview on hover

**Risk:** Offline mode unclear  
**Mitigation:** Explicit offline indicator, feature availability list

---

## 12. Future Enhancements (Post-1.0)

### 12.1 Not in 1.0 Scope

- Web interface
- Mobile app
- Cloud sync
- Collaborative features
- Audio processing
- Video processing
- Code execution from documents
- External vector databases (Pinecone, Weaviate)
- Commercial model providers (Anthropic, OpenAI as primary)
- Fine-tuning models
- Model quantization
- Distributed processing

### 12.2 Potential 1.1+ Features

- Advanced reranking
- Query expansion
- Semantic search across all content types
- Document comparison tools
- Batch document processing
- Template extraction
- Form filling from documents
- Document generation
- Mind map visualization of knowledge graph
- Export knowledge graph
- API for external integrations

---

## 13. License and Attribution

### 13.1 Pactlyn License

**License:** MIT (existing)  
**Copyright:** Pactlyn contributors

### 13.2 Reference Repository Attribution

**When reusing patterns or code from:**

**haiku.rag (MIT):**
```
# Portions inspired by haiku.rag (https://github.com/ggozad/haiku.rag)
# Copyright 2025 Yiorgis Gozadinos
# Licensed under the MIT License
```

**local-ai-workspace (MIT):**
```
# Portions inspired by local-ai-workspace (https://github.com/Jn527fd/local-ai-workspace)  
# Copyright 2026 Local AI Coding Assistant contributors
# Licensed under the MIT License
```

Add attribution in:
- Source code comments (where patterns used)
- `docs/attribution.md` (comprehensive list)
- Dependency documentation

### 13.3 Third-Party Licenses

**Dependencies to verify:**
- Docling - Check license
- PaddleOCR - Apache 2.0
- PyMuPDF - AGPL (use carefully, commercial alternative exists)
- pdfplumber - MIT
- Ollama - MIT (client library)

---

## 14. Implementation Timeline

### 14.1 Estimated Sessions

- **Phase 1:** Reference analysis - 1 session ✓ COMPLETED
- **Phase 2:** Dynamic model management - 3-5 sessions
- **Phase 3:** PDF extraction - 2-3 sessions
- **Phase 4:** OCR - 2 sessions
- **Phase 5:** Vision models - 2-3 sessions
- **Phase 6:** Document pipeline - 3-4 sessions
- **Phase 7:** Qdrant indexing - 2 sessions
- **Phase 8:** Documents UI - 3-4 sessions
- **Phase 9:** Multimodal RAG - 3-4 sessions
- **Phase 10:** Knowledge graph - 2-3 sessions
- **Phase 11:** Evaluation - 2-3 sessions

**Total estimated:** 25-36 sessions

### 14.2 Milestones

- **Milestone 1:** Model discovery and selection working (Phase 2 complete)
- **Milestone 2:** PDF and image processing functional (Phases 3-5 complete)
- **Milestone 3:** Documents indexed and searchable (Phases 6-7 complete)
- **Milestone 4:** User can upload and query documents (Phases 8-9 complete)
- **Milestone 5:** Full integration and evaluation (Phases 10-11 complete)
- **Milestone 6:** Documentation and release prep

---

## 15. Next Steps

### 15.1 Immediate Actions (Next Session)

1. **Begin Phase 2: Dynamic Model Management**
   - Create `src/pactlyn/llm/discovery.py`
   - Implement `OllamaDiscoveryService.discover_models()`
   - Research official Ollama API documentation
   - Create tests with mocked responses

2. **Update dependencies:**
   - Add httpx dependency (likely already present)
   - No new dependencies needed yet for discovery phase

3. **Database preparation:**
   - Create Alembic migration for `active_model_selections` table
   - Extend `model_configurations` table

### 15.2 Verification Before Proceeding

- [ ] Confirm Ollama is installed and accessible at http://127.0.0.1:11434
- [ ] Confirm Qwen2.5 7B is installed: `ollama list`
- [ ] Confirm nomic-embed-text is installed
- [ ] Confirm Qwen2.5-VL is installed (or will be for vision phase)
- [ ] Review existing LLM gateway in `src/pactlyn/llm/gateway.py`
- [ ] Review existing provider structure in `src/pactlyn/llm/providers/`

---

## 16. Success Metrics

### 16.1 Functionality Metrics

- [ ] 100% of existing features still work
- [ ] Model discovery detects 100% of installed Ollama models
- [ ] Model classification accuracy > 95%
- [ ] PDF text extraction success rate > 98% (text-based PDFs)
- [ ] OCR accuracy > 90% (printed text)
- [ ] Document upload success rate > 99%
- [ ] RAG retrieval Recall@5 > 80%
- [ ] Citation accuracy > 95%

### 16.2 Performance Metrics

- [ ] PDF extraction < 1 second per page (native)
- [ ] OCR < 5 seconds per page
- [ ] Vision analysis < 10 seconds per image
- [ ] Embedding < 1 second per chunk (batched)
- [ ] RAG query < 3 seconds total
- [ ] UI never freezes > 100ms
- [ ] Memory usage < 8 GB (excluding models)

### 16.3 User Experience Metrics

- [ ] Model selection requires zero code editing
- [ ] Document upload is drag-and-drop simple
- [ ] Citations are one click away from source
- [ ] Offline mode is clearly indicated
- [ ] Error messages are actionable
- [ ] Settings are discoverable
- [ ] First-time setup < 15 minutes

---

## Conclusion

This implementation plan transforms Pactlyn from a commitment tracking assistant into a comprehensive local-first multimodal personal AI desktop application.

**Key innovations:**
1. **Dynamic model management** - No hardcoded model names
2. **True multimodal RAG** - Documents, images, vision, OCR
3. **Local-first intelligence** - Everything runs on-device
4. **Graceful resource management** - Works on 6 GB VRAM laptops
5. **Seamless integration** - Extends existing architecture, doesn't replace it

**Ready to proceed with Phase 2: Dynamic AI Model Management.**

