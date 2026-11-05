"""Local OCR integration for scanned documents.

Portions adapted from local-ai-workspace
Copyright (c) 2026 Local AI Coding Assistant contributors
MIT License: https://github.com/Jn527fd/local-ai-workspace/blob/main/LICENSE
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF for PDF rendering
from PIL import Image

logger = logging.getLogger(__name__)

# Try importing PaddleOCR (primary OCR engine)
try:
    from paddleocr import PaddleOCR

    PADDLEOCR_AVAILABLE = True
except ImportError:
    PADDLEOCR_AVAILABLE = False
    logger.info("PaddleOCR not available")

# Try importing Tesseract (optional fallback)
try:
    import pytesseract

    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.info("Tesseract not available")


class OCRError(Exception):
    """Base exception for OCR errors."""


class OCREngineUnavailable(OCRError):
    """OCR engine is not installed or cannot initialize."""


class OCRProcessingError(OCRError):
    """OCR processing failed."""


@dataclass(frozen=True)
class BoundingBox:
    """Text bounding box coordinates.
    
    Coordinates are relative to the rendered image dimensions.
    """

    x_min: float
    y_min: float
    x_max: float
    y_max: float
    confidence: float | None = None


@dataclass(frozen=True)
class OCRTextBlock:
    """OCR-recognized text block with location."""

    text: str
    confidence: float
    bbox: BoundingBox | None = None


@dataclass(frozen=True)
class OCRPageResult:
    """OCR result for a single page."""

    page_number: int  # 1-indexed
    text: str
    blocks: list[OCRTextBlock]
    confidence: float  # Average confidence
    engine: str
    engine_version: str | None
    warnings: list[str]


@dataclass(frozen=True)
class PageClassification:
    """Classification of whether a page needs OCR."""

    page_number: int  # 1-indexed
    needs_ocr: bool
    reason: str
    char_count: int
    has_meaningful_text: bool
    has_large_image: bool
    is_blank: bool


def classify_page_for_ocr(
    page: fitz.Page,
    page_number: int,
    page_text: str,
    min_chars: int = 40,
    meaningful_word_ratio: float = 0.3,
) -> PageClassification:
    """Determine if a page needs OCR processing.
    
    Args:
        page: PyMuPDF page object
        page_number: Page number (1-indexed)
        page_text: Already-extracted native text
        min_chars: Minimum character threshold
        meaningful_word_ratio: Minimum ratio of dictionary-like words
        
    Returns:
        PageClassification with decision and reasoning
    """
    char_count = len(page_text.strip())
    
    # Check for meaningful text (not just symbols/garbage)
    words = re.findall(r'\b[a-zA-Z]{2,}\b', page_text)
    meaningful_ratio = len(words) / max(1, len(page_text.split()))
    has_meaningful_text = meaningful_ratio >= meaningful_word_ratio and len(words) >= 3
    
    # Check for large images using get_image_info (more reliable than get_image_bbox)
    has_large_image = False
    try:
        img_list = page.get_image_info()
        if img_list:
            page_area = page.rect.width * page.rect.height
            for img in img_list:
                bbox = img.get('bbox')
                if bbox:
                    img_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                    # Image covers >50% of page
                    if img_area > (page_area * 0.5):
                        has_large_image = True
                        break
    except Exception as e:
        logger.debug(f"Could not check image size on page {page_number}: {e}")
    
    # Check if page is effectively blank (no text AND no large images)
    if char_count < 5 and not has_large_image:
        return PageClassification(
            page_number=page_number,
            needs_ocr=False,
            reason="Page is blank or near-blank",
            char_count=char_count,
            has_meaningful_text=False,
            has_large_image=False,
            is_blank=True,
        )
    
    # Decision logic
    if char_count >= min_chars and has_meaningful_text:
        return PageClassification(
            page_number=page_number,
            needs_ocr=False,
            reason=f"Page has {char_count} chars of meaningful native text",
            char_count=char_count,
            has_meaningful_text=True,
            has_large_image=has_large_image,
            is_blank=False,
        )
    
    if has_large_image and char_count < min_chars:
        return PageClassification(
            page_number=page_number,
            needs_ocr=True,
            reason=f"Page contains large image(s) with minimal text ({char_count} chars)",
            char_count=char_count,
            has_meaningful_text=has_meaningful_text,
            has_large_image=True,
            is_blank=False,
        )
    
    if not has_meaningful_text and char_count < min_chars:
        return PageClassification(
            page_number=page_number,
            needs_ocr=True,
            reason=f"Page has {char_count} chars but no meaningful text",
            char_count=char_count,
            has_meaningful_text=False,
            has_large_image=has_large_image,
            is_blank=False,
        )
    
    return PageClassification(
        page_number=page_number,
        needs_ocr=False,
        reason=f"Page has {char_count} chars (above threshold)",
        char_count=char_count,
        has_meaningful_text=has_meaningful_text,
        has_large_image=has_large_image,
        is_blank=False,
    )


def render_pdf_page(pdf_path: Path, page_number: int, dpi: int = 300) -> Image.Image:
    """Render a PDF page to an image for OCR.
    
    Args:
        pdf_path: Path to PDF file
        page_number: Page number (1-indexed)
        dpi: Resolution for rendering (default 300 for OCR)
        
    Returns:
        PIL Image of the rendered page
        
    Raises:
        OCRProcessingError: If rendering fails
    """
    try:
        doc = fitz.open(str(pdf_path))
        
        if page_number < 1 or page_number > len(doc):
            doc.close()
            raise OCRProcessingError(
                f"Invalid page number {page_number} (document has {len(doc)} pages)"
            )
        
        page = doc[page_number - 1]  # Convert to 0-indexed
        
        # Render at specified DPI (default 300 for good OCR quality)
        zoom = dpi / 72  # 72 DPI is default
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        
        # Convert to PIL Image
        img_bytes = pix.tobytes("png")
        img = Image.open(BytesIO(img_bytes))
        
        doc.close()
        return img
        
    except Exception as e:
        raise OCRProcessingError(f"Failed to render page {page_number}: {e}") from e


class OCREngine(ABC):
    """Abstract base class for OCR engines."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Engine name."""
        ...
    
    @property
    @abstractmethod
    def version(self) -> str | None:
        """Engine version if available."""
        ...
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if engine is available."""
        ...
    
    @abstractmethod
    def process_image(self, image: Image.Image, page_number: int) -> OCRPageResult:
        """Process an image and extract text.
        
        Args:
            image: PIL Image to process
            page_number: Original page number (1-indexed)
            
        Returns:
            OCRPageResult with extracted text and metadata
            
        Raises:
            OCRProcessingError: If processing fails
        """
        ...


class PaddleOCREngine(OCREngine):
    """PaddleOCR engine (CPU-friendly, good accuracy)."""
    
    def __init__(self, lang: str = "en"):
        """Initialize PaddleOCR engine.
        
        Args:
            lang: Language code (default "en" for English)
        """
        self._ocr: PaddleOCR | None = None
        self._lang = lang
        self._initialized = False
        self._init_error: str | None = None
        
    def _initialize(self) -> None:
        """Lazy initialization of PaddleOCR."""
        if self._initialized:
            return
            
        if not PADDLEOCR_AVAILABLE:
            self._init_error = "PaddleOCR is not installed"
            self._initialized = True
            return
        
        try:
            # Initialize PaddleOCR (CPU mode by default in 3.7+)
            # First run will download models (~8MB for det, ~10MB for rec)
            self._ocr = PaddleOCR(
                use_angle_cls=True,  # Enable rotation detection
                lang=self._lang,
            )
            self._initialized = True
            logger.info("PaddleOCR initialized successfully")
        except Exception as e:
            self._init_error = f"Failed to initialize PaddleOCR: {e}"
            self._initialized = True
            logger.error(self._init_error)
    
    @property
    def name(self) -> str:
        return "paddleocr"
    
    @property
    def version(self) -> str | None:
        if not PADDLEOCR_AVAILABLE:
            return None
        try:
            import paddleocr
            return getattr(paddleocr, "__version__", None)
        except Exception:
            return None
    
    def is_available(self) -> bool:
        self._initialize()
        return self._ocr is not None and self._init_error is None
    
    def process_image(self, image: Image.Image, page_number: int) -> OCRPageResult:
        """Process image with PaddleOCR.
        
        Args:
            image: PIL Image to process
            page_number: Page number (1-indexed)
            
        Returns:
            OCRPageResult with recognized text
            
        Raises:
            OCREngineUnavailable: If engine not available
            OCRProcessingError: If processing fails
        """
        self._initialize()
        
        if not self.is_available():
            raise OCREngineUnavailable(
                self._init_error or "PaddleOCR is not available"
            )
        
        try:
            # Convert PIL Image to numpy array
            import numpy as np
            img_array = np.array(image)
            
            # Run OCR (cls parameter not supported in PaddleOCR 3.7+)
            result = self._ocr.ocr(img_array)  # type: ignore[attr-defined]
            
            if not result or not result[0]:
                return OCRPageResult(
                    page_number=page_number,
                    text="",
                    blocks=[],
                    confidence=0.0,
                    engine=self.name,
                    engine_version=self.version,
                    warnings=["No text detected on page"],
                )
            
            # Parse PaddleOCR results
            blocks: list[OCRTextBlock] = []
            text_parts: list[str] = []
            confidences: list[float] = []
            
            for line in result[0]:
                if not line or len(line) < 2:
                    continue
                
                bbox_points = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                text_info = line[1]  # (text, confidence)
                
                if not text_info or len(text_info) < 2:
                    continue
                
                text = text_info[0]
                confidence = float(text_info[1])
                
                # Extract bounding box (use min/max of 4 points)
                xs = [p[0] for p in bbox_points]
                ys = [p[1] for p in bbox_points]
                bbox = BoundingBox(
                    x_min=min(xs),
                    y_min=min(ys),
                    x_max=max(xs),
                    y_max=max(ys),
                    confidence=confidence,
                )
                
                blocks.append(OCRTextBlock(text=text, confidence=confidence, bbox=bbox))
                text_parts.append(text)
                confidences.append(confidence)
            
            full_text = " ".join(text_parts)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            warnings = []
            if avg_confidence < 0.6:
                warnings.append(
                    f"Low OCR confidence ({avg_confidence:.2f}) - text may be unreliable"
                )
            
            return OCRPageResult(
                page_number=page_number,
                text=full_text,
                blocks=blocks,
                confidence=avg_confidence,
                engine=self.name,
                engine_version=self.version,
                warnings=warnings,
            )
            
        except Exception as e:
            raise OCRProcessingError(
                f"PaddleOCR processing failed on page {page_number}: {e}"
            ) from e


class TesseractEngine(OCREngine):
    """Tesseract OCR engine (optional fallback)."""
    
    @property
    def name(self) -> str:
        return "tesseract"
    
    @property
    def version(self) -> str | None:
        if not TESSERACT_AVAILABLE:
            return None
        try:
            return pytesseract.get_tesseract_version().split()[0]
        except Exception:
            return None
    
    def is_available(self) -> bool:
        if not TESSERACT_AVAILABLE:
            return False
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False
    
    def process_image(self, image: Image.Image, page_number: int) -> OCRPageResult:
        """Process image with Tesseract.
        
        Args:
            image: PIL Image to process
            page_number: Page number (1-indexed)
            
        Returns:
            OCRPageResult with recognized text
            
        Raises:
            OCREngineUnavailable: If engine not available
            OCRProcessingError: If processing fails
        """
        if not self.is_available():
            raise OCREngineUnavailable("Tesseract is not available")
        
        try:
            # Get detailed data with bounding boxes
            data = pytesseract.image_to_data(
                image, output_type=pytesseract.Output.DICT
            )
            
            # Extract text blocks with confidence
            blocks: list[OCRTextBlock] = []
            text_parts: list[str] = []
            confidences: list[float] = []
            
            for i, text in enumerate(data["text"]):
                text = text.strip()
                if not text:
                    continue
                
                conf = float(data["conf"][i])
                if conf < 0:  # Tesseract uses -1 for no confidence
                    conf = 0.0
                
                bbox = BoundingBox(
                    x_min=float(data["left"][i]),
                    y_min=float(data["top"][i]),
                    x_max=float(data["left"][i] + data["width"][i]),
                    y_max=float(data["top"][i] + data["height"][i]),
                    confidence=conf,
                )
                
                blocks.append(OCRTextBlock(text=text, confidence=conf, bbox=bbox))
                text_parts.append(text)
                if conf > 0:
                    confidences.append(conf)
            
            full_text = " ".join(text_parts)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            warnings = []
            if avg_confidence < 60:  # Tesseract uses 0-100 scale
                warnings.append(
                    f"Low OCR confidence ({avg_confidence:.1f}/100) - text may be unreliable"
                )
            
            return OCRPageResult(
                page_number=page_number,
                text=full_text,
                blocks=blocks,
                confidence=avg_confidence / 100,  # Normalize to 0-1
                engine=self.name,
                engine_version=self.version,
                warnings=warnings,
            )
            
        except Exception as e:
            raise OCRProcessingError(
                f"Tesseract processing failed on page {page_number}: {e}"
            ) from e


def get_default_ocr_engine() -> OCREngine:
    """Get the default OCR engine (PaddleOCR preferred).
    
    Returns:
        OCREngine instance
        
    Raises:
        OCREngineUnavailable: If no OCR engine is available
    """
    # Try PaddleOCR first (CPU-friendly, good accuracy, no external dependencies)
    paddle = PaddleOCREngine()
    if paddle.is_available():
        return paddle
    
    # Fall back to Tesseract if available
    tesseract = TesseractEngine()
    if tesseract.is_available():
        logger.info("Using Tesseract as OCR fallback")
        return tesseract
    
    raise OCREngineUnavailable(
        "No OCR engine available. Install paddleocr (recommended) or tesseract."
    )


def process_page_with_ocr(
    pdf_path: Path,
    page_number: int,
    engine: OCREngine | None = None,
    dpi: int = 300,
) -> OCRPageResult:
    """Process a single PDF page with OCR.
    
    Args:
        pdf_path: Path to PDF file
        page_number: Page number (1-indexed)
        engine: OCR engine to use (default: auto-detect)
        dpi: Rendering DPI (default 300)
        
    Returns:
        OCRPageResult with extracted text
        
    Raises:
        OCREngineUnavailable: If no OCR engine available
        OCRProcessingError: If processing fails
    """
    if engine is None:
        engine = get_default_ocr_engine()
    
    # Render page to image
    image = render_pdf_page(pdf_path, page_number, dpi=dpi)
    
    # Run OCR
    return engine.process_image(image, page_number)
