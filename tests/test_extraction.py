"""Tests for document text extraction."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pactlyn.documents.extraction import (
    ExtractionError,
    ExtractionFailedError,
    UnsupportedDocumentError,
    compute_content_hash,
    extract_text,
    is_low_text_pdf,
)
from pactlyn.documents.models import ExtractionResult


class TestContentHash:
    """Test content hash computation."""

    def test_compute_content_hash(self, tmp_path: Path) -> None:
        """Test SHA256 hash computation."""
        test_file = tmp_path / "test.txt"
        test_content = b"Hello, World!"
        test_file.write_bytes(test_content)

        result = compute_content_hash(test_file)
        expected = hashlib.sha256(test_content).hexdigest()

        assert result == expected

    def test_same_content_same_hash(self, tmp_path: Path) -> None:
        """Test that identical content produces identical hash."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        content = b"Same content"

        file1.write_bytes(content)
        file2.write_bytes(content)

        hash1 = compute_content_hash(file1)
        hash2 = compute_content_hash(file2)

        assert hash1 == hash2


class TestLowTextDetection:
    """Test low-text PDF detection."""

    def test_low_text_detection(self) -> None:
        """Test that low text content is detected."""
        result = ExtractionResult(
            text="abc",  # 3 chars
            page_count=10,  # 0.3 chars/page
            char_count=3,
            extractor="pymupdf",
            warnings=[],
            diagnostics={"avg_chars_per_page": 0.3},
        )

        assert is_low_text_pdf(result, threshold=40) is True

    def test_normal_text_not_low(self) -> None:
        """Test that normal text content is not flagged."""
        result = ExtractionResult(
            text="A" * 1000,  # 1000 chars
            page_count=10,  # 100 chars/page
            char_count=1000,
            extractor="pymupdf",
            warnings=[],
            diagnostics={"avg_chars_per_page": 100},
        )

        assert is_low_text_pdf(result, threshold=40) is False

    def test_zero_pages_not_low(self) -> None:
        """Test that zero-page documents are not flagged."""
        result = ExtractionResult(
            text="",
            page_count=0,
            char_count=0,
            extractor="pymupdf",
            warnings=[],
            diagnostics={},
        )

        assert is_low_text_pdf(result, threshold=40) is False


class TestExtractionErrors:
    """Test extraction error handling."""

    def test_unsupported_format(self, tmp_path: Path) -> None:
        """Test that unsupported file formats raise appropriate error."""
        unsupported_file = tmp_path / "test.xyz"
        unsupported_file.write_text("content")

        with pytest.raises(UnsupportedDocumentError, match="Unsupported file format"):
            extract_text(unsupported_file)

    def test_missing_file(self, tmp_path: Path) -> None:
        """Test that missing files raise appropriate error."""
        missing_file = tmp_path / "nonexistent.pdf"

        with pytest.raises(ExtractionFailedError, match="File not found"):
            extract_text(missing_file)


class TestExtractTextMocked:
    """Test extract_text with mocked backends."""

    @patch("pactlyn.documents.extraction.DOCLING_AVAILABLE", True)
    @patch("pactlyn.documents.extraction.extract_text_docling")
    def test_uses_docling_when_available(
        self, mock_docling: Mock, tmp_path: Path
    ) -> None:
        """Test that Docling is used when available."""
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_bytes(b"%PDF-1.4 fake pdf")

        expected_result = ExtractionResult(
            text="Extracted text",
            page_count=1,
            char_count=14,
            extractor="docling",
            warnings=[],
            diagnostics={},
            structure={"sections": []},
        )
        mock_docling.return_value = expected_result

        result = extract_text(test_pdf)

        assert result == expected_result
        mock_docling.assert_called_once_with(test_pdf)

    @patch("pactlyn.documents.extraction.DOCLING_AVAILABLE", False)
    @patch("pactlyn.documents.extraction.PYMUPDF_AVAILABLE", True)
    @patch("pactlyn.documents.extraction.extract_text_pymupdf")
    def test_falls_back_to_pymupdf(
        self, mock_pymupdf: Mock, tmp_path: Path
    ) -> None:
        """Test fallback to PyMuPDF when Docling unavailable."""
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_bytes(b"%PDF-1.4 fake pdf")

        expected_result = ExtractionResult(
            text="Fallback text",
            page_count=1,
            char_count=13,
            extractor="pymupdf",
            warnings=[],
            diagnostics={},
        )
        mock_pymupdf.return_value = expected_result

        result = extract_text(test_pdf)

        # Should have added fallback warning
        assert "PyMuPDF fallback" in result.warnings[0]
        mock_pymupdf.assert_called_once_with(test_pdf)

    @patch("pactlyn.documents.extraction.DOCLING_AVAILABLE", True)
    @patch("pactlyn.documents.extraction.PYMUPDF_AVAILABLE", True)
    @patch("pactlyn.documents.extraction.extract_text_docling")
    @patch("pactlyn.documents.extraction.extract_text_pymupdf")
    def test_pymupdf_fallback_on_docling_failure(
        self, mock_pymupdf: Mock, mock_docling: Mock, tmp_path: Path
    ) -> None:
        """Test PyMuPDF fallback when Docling fails."""
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_bytes(b"%PDF-1.4 fake pdf")

        mock_docling.side_effect = ExtractionFailedError("Docling error")
        pymupdf_result = ExtractionResult(
            text="Fallback text",
            page_count=1,
            char_count=13,
            extractor="pymupdf",
            warnings=[],
            diagnostics={},
        )
        mock_pymupdf.return_value = pymupdf_result

        result = extract_text(test_pdf)

        assert "PyMuPDF fallback" in result.warnings[0]
        mock_docling.assert_called_once()
        mock_pymupdf.assert_called_once()

    @patch("pactlyn.documents.extraction.DOCLING_AVAILABLE", False)
    @patch("pactlyn.documents.extraction.PYMUPDF_AVAILABLE", False)
    def test_all_methods_unavailable(self, tmp_path: Path) -> None:
        """Test error when no extraction methods available."""
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_bytes(b"%PDF-1.4 fake pdf")

        with pytest.raises(ExtractionFailedError, match="All extraction methods failed"):
            extract_text(test_pdf)
