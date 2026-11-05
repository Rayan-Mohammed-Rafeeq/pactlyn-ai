"""Document intelligence module for Pactlyn.

Provides PDF extraction, OCR, vision analysis, structure-aware chunking,
and document RAG integration with citations.
"""

from pactlyn.documents.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    ExtractionResult,
)
from pactlyn.documents.ocr import (
    OCREngine,
    OCREngineUnavailable,
    OCRPageResult,
    PaddleOCREngine,
    get_default_ocr_engine,
)

__all__ = [
    "Document",
    "DocumentChunk",
    "DocumentStatus",
    "ExtractionResult",
    "OCREngine",
    "OCREngineUnavailable",
    "OCRPageResult",
    "PaddleOCREngine",
    "get_default_ocr_engine",
]
