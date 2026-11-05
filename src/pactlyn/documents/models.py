"""Document data models and types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DocumentStatus(str, Enum):
    """Document processing status."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


@dataclass(frozen=True)
class ExtractionResult:
    """Result of document text extraction."""

    text: str
    page_count: int
    char_count: int
    extractor: str  # "docling", "pymupdf", "ocr"
    warnings: list[str]
    diagnostics: dict[str, object]
    structure: dict[str, object] | None = None  # Docling structure if available


@dataclass(frozen=True)
class DocumentMetadata:
    """Document metadata from extraction."""

    title: str | None
    author: str | None
    subject: str | None
    keywords: list[str]
    creation_date: datetime | None
    modification_date: datetime | None
    page_count: int
    has_text: bool
    has_images: bool


@dataclass(frozen=True)
class ChunkMetadata:
    """Metadata for a document chunk."""

    page_numbers: list[int]
    section_heading: str | None
    chunk_type: str  # "text", "table", "figure_caption"
    char_start: int
    char_end: int
    figure_refs: list[str]


@dataclass
class Document:
    """Document record (matches SQLAlchemy model)."""

    id: str
    filename: str
    content_hash: str
    mime_type: str
    size_bytes: int
    status: DocumentStatus
    page_count: int | None
    created_at: datetime
    processed_at: datetime | None
    error_message: str | None
    extraction_metadata: dict[str, object] | None


@dataclass
class DocumentChunk:
    """Document chunk record (matches SQLAlchemy model)."""

    id: str
    document_id: str
    content: str
    page_numbers: str  # JSON: "[1, 2, 3]"
    section_heading: str | None
    chunk_index: int
    char_start: int
    char_end: int
    chunk_type: str
    indexed: bool
    vector_id: str | None
