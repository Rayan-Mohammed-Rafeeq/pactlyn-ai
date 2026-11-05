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
from pactlyn.documents.vision import (
    VisionResult,
    VisionService,
    VisionError,
    VisionModelUnavailable,
    VisionProcessingError,
    get_default_vision_service,
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
    "VisionResult",
    "VisionService",
    "VisionError",
    "VisionModelUnavailable",
    "VisionProcessingError",
    "get_default_vision_service",
]
