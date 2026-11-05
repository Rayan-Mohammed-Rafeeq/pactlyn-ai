"""Tests for OCR integration.

Tests are divided into:
- Unit tests (no external OCR engines, mocked)
- Integration tests (mocked OCR responses)
- Live tests (real PaddleOCR, opt-in with RUN_OCR_TESTS=1)
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from PIL import Image

from pactlyn.documents.ocr import (
    BoundingBox,
    OCREngineUnavailable,
    OCRPageResult,
    OCRProcessingError,
    OCRTextBlock,
    PaddleOCREngine,
    PageClassification,
    classify_page_for_ocr,
    get_default_ocr_engine,
    process_page_with_ocr,
    render_pdf_page,
)


# Marker for live OCR tests (requires actual PaddleOCR installation)
RUN_OCR_TESTS = os.environ.get("RUN_OCR_TESTS", "0") == "1"
live_ocr = pytest.mark.skipif(
    not RUN_OCR_TESTS,
    reason="Live OCR tests require RUN_OCR_TESTS=1 and PaddleOCR installation"
)


class TestPageClassification:
    """Test page-level OCR decision logic."""

    def test_blank_page_no_ocr(self) -> None:
        """Blank pages should not require OCR."""
        mock_page = MagicMock()
        mock_page.rect = MagicMock(width=600, height=800)
        mock_page.get_images.return_value = []

        classification = classify_page_for_ocr(
            page=mock_page,
            page_number=1,
            page_text="",
        )

        assert classification.needs_ocr is False
        assert classification.is_blank is True
        assert "blank" in classification.reason.lower()

    def test_sufficient_native_text_no_ocr(self) -> None:
        """Pages with sufficient native text don't need OCR."""
        mock_page = MagicMock()
        mock_page.rect = MagicMock(width=600, height=800)
        mock_page.get_images.return_value = []

        # 100 chars of meaningful text
        text = "This is a normal page with plenty of readable text content. " * 2

        classification = classify_page_for_ocr(
            page=mock_page,
            page_number=1,
            page_text=text,
        )

        assert classification.needs_ocr is False
        assert classification.has_meaningful_text is True
        assert classification.char_count >= 40

    def test_low_text_with_large_image_needs_ocr(self) -> None:
        """Pages with minimal text and large images need OCR."""
        mock_page = MagicMock()
        mock_page.rect = MagicMock(width=600, height=800)
        
        # Mock large image covering > 50% of page
        mock_page.get_images.return_value = [(123, 0, 0, 0, 0, 0, 0, 0)]
        mock_bbox = MagicMock()
        mock_bbox.x0 = 0
        mock_bbox.y0 = 0
        mock_bbox.x1 = 600  # Full width
        mock_bbox.y1 = 500  # > 50% height
        mock_page.get_image_bbox.return_value = mock_bbox

        classification = classify_page_for_ocr(
            page=mock_page,
            page_number=1,
            page_text="Fig 1",  # Only 5 chars
        )

        assert classification.needs_ocr is True
        assert classification.has_large_image is True
        assert classification.char_count < 40

    def test_garbage_text_needs_ocr(self) -> None:
        """Pages with non-meaningful characters need OCR."""
        mock_page = MagicMock()
        mock_page.rect = MagicMock(width=600, height=800)
        mock_page.get_images.return_value = []

        # 30 chars but no meaningful words
        text = "@@@ ### $$$ !!! ??? ^^^ *** "

        classification = classify_page_for_ocr(
            page=mock_page,
            page_number=1,
            page_text=text,
        )

        assert classification.needs_ocr is True
        assert classification.has_meaningful_text is False

    def test_short_heading_with_image_needs_ocr(self) -> None:
        """Page with just a short heading and image needs OCR."""
        mock_page = MagicMock()
        mock_page.rect = MagicMock(width=600, height=800)
        mock_page.get_images.return_value = [(1, 0, 0, 0, 0, 0, 0, 0)]
        mock_bbox = MagicMock()
        mock_bbox.x0 = 0
        mock_bbox.y0 = 100
        mock_bbox.x1 = 600
        mock_bbox.y1 = 700  # Large image
        mock_page.get_image_bbox.return_value = mock_bbox

        classification = classify_page_for_ocr(
            page=mock_page,
            page_number=1,
            page_text="Chapter 3",  # Only 9 chars
        )

        assert classification.needs_ocr is True
        assert "minimal text" in classification.reason.lower()


class TestOCREngines:
    """Test OCR engine abstraction."""

    @patch("pactlyn.documents.ocr.PADDLEOCR_AVAILABLE", True)
    def test_paddleocr_engine_name(self) -> None:
        """Test PaddleOCR engine properties."""
        engine = PaddleOCREngine()
        assert engine.name == "paddleocr"

    @patch("pactlyn.documents.ocr.PADDLEOCR_AVAILABLE", False)
    def test_paddleocr_unavailable(self) -> None:
        """Test PaddleOCR reports unavailable when not installed."""
        engine = PaddleOCREngine()
        assert engine.is_available() is False

    @patch("pactlyn.documents.ocr.PADDLEOCR_AVAILABLE", True)
    @patch("pactlyn.documents.ocr.PaddleOCR")
    def test_paddleocr_initialization(self, mock_paddle_class: Mock) -> None:
        """Test PaddleOCR initializes correctly."""
        mock_instance = Mock()
        mock_paddle_class.return_value = mock_instance

        engine = PaddleOCREngine(lang="en")
        assert engine.is_available() is True

        # Check initialization parameters
        mock_paddle_class.assert_called_once_with(
            use_angle_cls=True,
            lang="en",
        )

    @patch("pactlyn.documents.ocr.PADDLEOCR_AVAILABLE", False)
    @patch("pactlyn.documents.ocr.TESSERACT_AVAILABLE", False)
    def test_get_default_engine_raises_when_none_available(self) -> None:
        """Test error when no OCR engine available."""
        with pytest.raises(OCREngineUnavailable, match="No OCR engine available"):
            get_default_ocr_engine()


class TestOCRProcessing:
    """Test OCR processing with mocked engines."""

    @patch("pactlyn.documents.ocr.PADDLEOCR_AVAILABLE", True)
    @patch("pactlyn.documents.ocr.PaddleOCR")
    def test_paddleocr_process_image(self, mock_paddle_class: Mock) -> None:
        """Test PaddleOCR image processing with mocked engine."""
        # Mock OCR result structure
        mock_ocr_instance = Mock()
        mock_ocr_result = [
            [
                [  # First text line
                    [[10, 10], [100, 10], [100, 30], [10, 30]],  # Bounding box
                    ("Hello World", 0.95),  # Text and confidence
                ],
                [  # Second text line
                    [[10, 40], [120, 40], [120, 60], [10, 60]],
                    ("Test Page", 0.92),
                ],
            ]
        ]
        mock_ocr_instance.ocr.return_value = mock_ocr_result
        mock_paddle_class.return_value = mock_ocr_instance

        # Create engine and process test image
        engine = PaddleOCREngine()
        test_image = Image.new("RGB", (200, 100), color="white")

        result = engine.process_image(test_image, page_number=1)

        assert result.page_number == 1
        assert result.engine == "paddleocr"
        assert "Hello World" in result.text
        assert "Test Page" in result.text
        assert len(result.blocks) == 2
        assert result.confidence > 0.9
        assert 0.0 <= result.confidence <= 1.0

    @patch("pactlyn.documents.ocr.PADDLEOCR_AVAILABLE", True)
    @patch("pactlyn.documents.ocr.PaddleOCR")
    def test_paddleocr_no_text_detected(self, mock_paddle_class: Mock) -> None:
        """Test PaddleOCR handles blank pages gracefully."""
        mock_ocr_instance = Mock()
        mock_ocr_instance.ocr.return_value = [[]]  # No text detected
        mock_paddle_class.return_value = mock_ocr_instance

        engine = PaddleOCREngine()
        test_image = Image.new("RGB", (200, 100), color="white")

        result = engine.process_image(test_image, page_number=1)

        assert result.text == ""
        assert len(result.blocks) == 0
        assert result.confidence == 0.0
        assert "No text detected" in result.warnings[0]

    @patch("pactlyn.documents.ocr.PADDLEOCR_AVAILABLE", True)
    @patch("pactlyn.documents.ocr.PaddleOCR")
    def test_paddleocr_low_confidence_warning(self, mock_paddle_class: Mock) -> None:
        """Test low confidence triggers warning."""
        mock_ocr_instance = Mock()
        mock_ocr_result = [
            [
                [
                    [[10, 10], [100, 10], [100, 30], [10, 30]],
                    ("unclear text", 0.45),  # Low confidence
                ],
            ]
        ]
        mock_ocr_instance.ocr.return_value = mock_ocr_result
        mock_paddle_class.return_value = mock_ocr_instance

        engine = PaddleOCREngine()
        test_image = Image.new("RGB", (200, 100), color="white")

        result = engine.process_image(test_image, page_number=1)

        assert result.confidence < 0.6
        assert any("Low OCR confidence" in w for w in result.warnings)


class TestBoundingBox:
    """Test bounding box structure."""

    def test_bounding_box_creation(self) -> None:
        """Test bounding box can be created."""
        bbox = BoundingBox(
            x_min=10.0,
            y_min=20.0,
            x_max=100.0,
            y_max=50.0,
            confidence=0.95,
        )

        assert bbox.x_min == 10.0
        assert bbox.y_min == 20.0
        assert bbox.x_max == 100.0
        assert bbox.y_max == 50.0
        assert bbox.confidence == 0.95


# Live OCR tests (opt-in)


@live_ocr
class TestLiveOCR:
    """Live tests with real PaddleOCR engine.
    
    Run with: RUN_OCR_TESTS=1 pytest tests/test_ocr.py::TestLiveOCR -v
    """

    def test_paddleocr_real_initialization(self) -> None:
        """Test PaddleOCR can initialize with real engine."""
        engine = PaddleOCREngine(use_gpu=False, lang="en")
        assert engine.is_available() is True
        assert engine.name == "paddleocr"
        assert engine.version is not None

    def test_paddleocr_real_process_simple_image(self) -> None:
        """Test PaddleOCR can process a simple text image."""
        # Create a simple test image with text
        from PIL import ImageDraw, ImageFont
        
        img = Image.new("RGB", (400, 100), color="white")
        draw = ImageDraw.Draw(img)
        
        # Use default font (may not be perfect but sufficient for basic test)
        try:
            # Try to use a better font if available
            font = ImageFont.truetype("arial.ttf", 32)
        except Exception:
            # Fall back to default
            font = ImageFont.load_default()
        
        draw.text((20, 30), "Hello OCR Test", fill="black", font=font)
        
        engine = PaddleOCREngine()
        result = engine.process_image(img, page_number=1)
        
        assert result.page_number == 1
        assert result.engine == "paddleocr"
        # PaddleOCR should recognize at least some text
        assert len(result.text) > 0
        # Should have detected text blocks
        assert len(result.blocks) > 0
        # Should have reasonable confidence
        assert result.confidence > 0.0

    def test_paddleocr_real_blank_image(self) -> None:
        """Test PaddleOCR handles blank image correctly."""
        img = Image.new("RGB", (400, 100), color="white")
        
        engine = PaddleOCREngine()
        result = engine.process_image(img, page_number=1)
        
        assert result.page_number == 1
        assert result.text == ""  # Should detect no text
        assert len(result.blocks) == 0
        assert "No text detected" in result.warnings[0]

    def test_get_default_engine_real(self) -> None:
        """Test default engine selection with real engines."""
        engine = get_default_ocr_engine()
        assert engine is not None
        assert engine.is_available() is True
        # Should prefer PaddleOCR if available
        assert engine.name in ("paddleocr", "tesseract")


@live_ocr
class TestLivePDFOCR:
    """Live tests with real PDF OCR processing.
    
    Requires actual PDF files to test against.
    """

    def test_render_pdf_page_real(self, tmp_path: Path) -> None:
        """Test PDF page rendering with real PDF."""
        # Create a minimal PDF for testing
        try:
            import fitz
            
            # Create test PDF
            pdf_path = tmp_path / "test.pdf"
            doc = fitz.open()
            page = doc.new_page(width=200, height=100)
            page.insert_text((20, 50), "Test Page")
            doc.save(str(pdf_path))
            doc.close()
            
            # Render the page
            img = render_pdf_page(pdf_path, page_number=1, dpi=150)
            
            assert isinstance(img, Image.Image)
            assert img.width > 0
            assert img.height > 0
            
        except ImportError:
            pytest.skip("PyMuPDF not available for live PDF test")

    def test_process_pdf_page_with_ocr_real(self, tmp_path: Path) -> None:
        """Test complete PDF OCR pipeline with real processing."""
        try:
            import fitz
            from PIL import ImageDraw
            
            # Create test PDF with text
            pdf_path = tmp_path / "test_ocr.pdf"
            doc = fitz.open()
            page = doc.new_page(width=400, height=200)
            page.insert_text((50, 100), "OCR Test Document", fontsize=24)
            doc.save(str(pdf_path))
            doc.close()
            
            # Process with OCR
            result = process_page_with_ocr(pdf_path, page_number=1)
            
            assert result.page_number == 1
            assert result.engine == "paddleocr"
            # Should extract some text (may not be perfect)
            assert len(result.text) > 0
            # Should have some confidence
            assert result.confidence >= 0.0
            
        except ImportError:
            pytest.skip("Required libraries not available for live PDF OCR test")
