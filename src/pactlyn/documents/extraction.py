"""Document text extraction with Docling and PyMuPDF.

Portions adapted from local-ai-workspace
Copyright (c) 2026 Local AI Coding Assistant contributors
MIT License: https://github.com/Jn527fd/local-ai-workspace/blob/main/LICENSE
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from pactlyn.documents.models import DocumentMetadata, ExtractionResult
from pactlyn.documents import ocr

logger = logging.getLogger(__name__)

# Try importing Docling (primary extractor)
try:
    from docling.document_converter import DocumentConverter
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions

    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False
    logger.warning("Docling not available, will use PyMuPDF fallback")

# Try importing PyMuPDF (fallback extractor)
try:
    import fitz  # PyMuPDF

    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    logger.warning("PyMuPDF not available")


class ExtractionError(Exception):
    """Base exception for document extraction errors."""


class UnsupportedDocumentError(ExtractionError):
    """Document format is not supported."""


class ExtractionFailedError(ExtractionError):
    """Text extraction failed for all available methods."""


def compute_content_hash(file_path: Path) -> str:
    """Compute SHA256 hash of file content for deduplication."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def extract_text_docling(file_path: Path) -> ExtractionResult:
    """Extract text and structure using Docling.

    Args:
        file_path: Path to PDF or document file

    Returns:
        ExtractionResult with text, structure, and metadata

    Raises:
        ExtractionFailedError: If Docling extraction fails
    """
    if not DOCLING_AVAILABLE:
        raise ExtractionFailedError("Docling is not installed")

    try:
        # Configure Docling pipeline
        # Handle API changes gracefully - backend attribute may not exist in all versions
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False  # OCR handled separately in Phase 2
        pipeline_options.do_table_structure = True
        
        # Try to set backend if available (newer API)
        if hasattr(pipeline_options, 'backend'):
            try:
                from docling.backend.pypdfium2_backend import PyPdfiumBackend
                pipeline_options.backend = PyPdfiumBackend
            except (ImportError, AttributeError):
                # Backend setting not supported or backend class not available
                pass

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: pipeline_options,
            }
        )

        # Convert document
        result = converter.convert(str(file_path))
        doc = result.document

        # Extract text content
        text = doc.export_to_markdown()

        # Extract structure
        structure: dict[str, Any] = {
            "sections": [],
            "tables": [],
            "figures": [],
        }

        # Parse document structure
        for element in doc.iterate_elements():
            if element.label == "section_header":
                structure["sections"].append(
                    {
                        "level": getattr(element, "level", 1),
                        "text": element.text,
                        "page": getattr(element, "prov", [{}])[0].get("page", 0),
                    }
                )
            elif element.label == "table":
                structure["tables"].append(
                    {
                        "page": getattr(element, "prov", [{}])[0].get("page", 0),
                        "caption": getattr(element, "caption", None),
                    }
                )
            elif element.label == "picture":
                structure["figures"].append(
                    {
                        "page": getattr(element, "prov", [{}])[0].get("page", 0),
                        "caption": getattr(element, "caption", None),
                    }
                )

        # Count pages
        page_count = len(doc.pages) if hasattr(doc, "pages") else 1

        return ExtractionResult(
            text=text,
            page_count=page_count,
            char_count=len(text),
            extractor="docling",
            warnings=[],
            diagnostics={
                "sections_found": len(structure["sections"]),
                "tables_found": len(structure["tables"]),
                "figures_found": len(structure["figures"]),
            },
            structure=structure,
        )

    except Exception as e:
        logger.warning(f"Docling extraction failed: {e}")
        raise ExtractionFailedError(f"Docling extraction failed: {e}") from e


def extract_text_pymupdf(file_path: Path) -> ExtractionResult:
    """Extract text using PyMuPDF (fallback method).

    Args:
        file_path: Path to PDF file

    Returns:
        ExtractionResult with extracted text

    Raises:
        ExtractionFailedError: If PyMuPDF extraction fails
    """
    if not PYMUPDF_AVAILABLE:
        raise ExtractionFailedError("PyMuPDF is not installed")

    try:
        doc = fitz.open(str(file_path))
        page_count = len(doc)
        text_parts: list[str] = []
        page_char_counts: list[int] = []

        for page_num in range(page_count):
            page = doc[page_num]
            page_text = page.get_text()
            text_parts.append(f"\n--- Page {page_num + 1} ---\n\n{page_text}")
            page_char_counts.append(len(page_text.strip()))

        doc.close()

        full_text = "\n".join(text_parts)
        avg_chars_per_page = sum(page_char_counts) / page_count if page_count > 0 else 0

        warnings = []
        if avg_chars_per_page < 40:
            warnings.append(
                f"Low text content detected (avg {avg_chars_per_page:.1f} chars/page). "
                "Document may be scanned and require OCR."
            )

        return ExtractionResult(
            text=full_text,
            page_count=page_count,
            char_count=len(full_text),
            extractor="pymupdf",
            warnings=warnings,
            diagnostics={
                "avg_chars_per_page": avg_chars_per_page,
                "page_char_counts": page_char_counts,
            },
            structure=None,
        )

    except Exception as e:
        logger.warning(f"PyMuPDF extraction failed: {e}")
        raise ExtractionFailedError(f"PyMuPDF extraction failed: {e}") from e


def extract_metadata_pymupdf(file_path: Path) -> DocumentMetadata:
    """Extract document metadata using PyMuPDF.

    Args:
        file_path: Path to PDF file

    Returns:
        DocumentMetadata with available metadata fields
    """
    if not PYMUPDF_AVAILABLE:
        return DocumentMetadata(
            title=None,
            author=None,
            subject=None,
            keywords=[],
            creation_date=None,
            modification_date=None,
            page_count=0,
            has_text=False,
            has_images=False,
        )

    try:
        doc = fitz.open(str(file_path))
        metadata = doc.metadata
        page_count = len(doc)

        # Check for text and images
        has_text = False
        has_images = False
        for page_num in range(min(3, page_count)):  # Check first 3 pages
            page = doc[page_num]
            if page.get_text().strip():
                has_text = True
            if page.get_images():
                has_images = True
            if has_text and has_images:
                break

        doc.close()

        # Parse keywords
        keywords_str = metadata.get("keywords", "")
        keywords = [k.strip() for k in keywords_str.split(",") if k.strip()] if keywords_str else []

        return DocumentMetadata(
            title=metadata.get("title") or None,
            author=metadata.get("author") or None,
            subject=metadata.get("subject") or None,
            keywords=keywords,
            creation_date=None,  # PyMuPDF dates need parsing
            modification_date=None,
            page_count=page_count,
            has_text=has_text,
            has_images=has_images,
        )

    except Exception as e:
        logger.warning(f"Failed to extract metadata: {e}")
        return DocumentMetadata(
            title=None,
            author=None,
            subject=None,
            keywords=[],
            creation_date=None,
            modification_date=None,
            page_count=0,
            has_text=False,
            has_images=False,
        )


def extract_text(file_path: Path) -> ExtractionResult:
    """Extract text from document using best available method.

    Tries Docling first (structure-aware), falls back to PyMuPDF.

    Args:
        file_path: Path to document file

    Returns:
        ExtractionResult with extracted text and metadata

    Raises:
        UnsupportedDocumentError: If file format is not supported
        ExtractionFailedError: If all extraction methods fail
    """
    if not file_path.exists():
        raise ExtractionFailedError(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix not in {".pdf"}:
        raise UnsupportedDocumentError(
            f"Unsupported file format: {suffix}. Currently only PDF is supported."
        )

    # Try Docling first (structure-aware extraction)
    if DOCLING_AVAILABLE:
        try:
            return extract_text_docling(file_path)
        except ExtractionFailedError as e:
            logger.info(f"Docling extraction failed, trying PyMuPDF fallback: {e}")

    # Fall back to PyMuPDF
    if PYMUPDF_AVAILABLE:
        try:
            result = extract_text_pymupdf(file_path)
            result.warnings.append(
                "Used PyMuPDF fallback extraction (no structure information available)"
            )
            return result
        except ExtractionFailedError as e:
            logger.error(f"PyMuPDF extraction also failed: {e}")

    # All methods failed
    raise ExtractionFailedError(
        "All extraction methods failed. Please ensure Docling or PyMuPDF is installed."
    )


def is_low_text_pdf(result: ExtractionResult, threshold: int = 40) -> bool:
    """Determine if PDF has low text content and likely needs OCR.

    Args:
        result: Extraction result to check
        threshold: Average characters per page threshold

    Returns:
        True if document appears to be scanned/image-based
    """
    if result.page_count == 0:
        return False

    avg_chars_per_page = result.char_count / result.page_count

    # Also check diagnostics if available
    if "avg_chars_per_page" in result.diagnostics:
        avg_chars_per_page = float(result.diagnostics["avg_chars_per_page"])

    return avg_chars_per_page < threshold


def extract_text_with_ocr(
    file_path: Path,
    ocr_engine: ocr.OCREngine | None = None,
    ocr_dpi: int = 300,
) -> ExtractionResult:
    """Extract text from PDF with page-level OCR decisions.
    
    This is the main entry point for extraction with OCR support.
    It performs native extraction first, then applies OCR only to pages
    that need it based on intelligent page-level classification.
    
    Args:
        file_path: Path to PDF file
        ocr_engine: OCR engine to use (None = auto-detect)
        ocr_dpi: DPI for page rendering (default 300)
        
    Returns:
        ExtractionResult with merged native + OCR text
        
    Raises:
        UnsupportedDocumentError: If file format not supported
        ExtractionFailedError: If extraction fails
    """
    if not file_path.exists():
        raise ExtractionFailedError(f"File not found: {file_path}")
    
    suffix = file_path.suffix.lower()
    if suffix not in {".pdf"}:
        raise UnsupportedDocumentError(
            f"Unsupported file format: {suffix}. Currently only PDF is supported."
        )
    
    # First, try native extraction
    try:
        native_result = extract_text(file_path)
    except ExtractionFailedError as e:
        logger.warning(f"Native extraction failed: {e}")
        # If native extraction completely fails, try OCR on all pages
        return _extract_text_ocr_only(file_path, ocr_engine, ocr_dpi)
    
    # Check if we need OCR at all
    if not PYMUPDF_AVAILABLE:
        logger.warning("PyMuPDF not available, cannot perform page-level OCR")
        return native_result
    
    # Classify each page for OCR
    try:
        doc = fitz.open(str(file_path))
        page_classifications: list[ocr.PageClassification] = []
        pages_needing_ocr: list[int] = []
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = page.get_text()
            
            classification = ocr.classify_page_for_ocr(
                page=page,
                page_number=page_num + 1,  # 1-indexed
                page_text=page_text,
            )
            page_classifications.append(classification)
            
            if classification.needs_ocr:
                pages_needing_ocr.append(page_num + 1)
        
        doc.close()
        
        # If no pages need OCR, return native result
        if not pages_needing_ocr:
            logger.info("No pages require OCR, using native extraction only")
            return native_result
        
        # Initialize OCR engine if needed
        if ocr_engine is None:
            try:
                ocr_engine = ocr.get_default_ocr_engine()
            except ocr.OCREngineUnavailable as e:
                logger.warning(f"OCR engine unavailable: {e}")
                native_result.warnings.append(
                    f"OCR unavailable for {len(pages_needing_ocr)} pages that may need it"
                )
                return native_result
        
        # Process pages with OCR
        logger.info(f"Processing {len(pages_needing_ocr)} pages with OCR")
        ocr_results: dict[int, ocr.OCRPageResult] = {}
        ocr_warnings: list[str] = []
        
        for page_num in pages_needing_ocr:
            try:
                ocr_result = ocr.process_page_with_ocr(
                    pdf_path=file_path,
                    page_number=page_num,
                    engine=ocr_engine,
                    dpi=ocr_dpi,
                )
                ocr_results[page_num] = ocr_result
                ocr_warnings.extend(ocr_result.warnings)
            except (ocr.OCREngineUnavailable, ocr.OCRProcessingError) as e:
                logger.error(f"OCR failed on page {page_num}: {e}")
                ocr_warnings.append(f"OCR failed on page {page_num}: {str(e)[:100]}")
        
        # Merge native and OCR results
        merged_result = _merge_native_and_ocr(
            native_result=native_result,
            ocr_results=ocr_results,
            page_classifications=page_classifications,
            ocr_warnings=ocr_warnings,
        )
        
        return merged_result
        
    except Exception as e:
        logger.error(f"Error during OCR processing: {e}")
        native_result.warnings.append(f"OCR processing error: {str(e)[:100]}")
        return native_result


def _extract_text_ocr_only(
    file_path: Path,
    ocr_engine: ocr.OCREngine | None,
    ocr_dpi: int,
) -> ExtractionResult:
    """Extract text using OCR only (when native extraction fails).
    
    Args:
        file_path: Path to PDF
        ocr_engine: OCR engine to use
        ocr_dpi: DPI for rendering
        
    Returns:
        ExtractionResult from OCR
        
    Raises:
        ExtractionFailedError: If OCR also fails
    """
    if ocr_engine is None:
        try:
            ocr_engine = ocr.get_default_ocr_engine()
        except ocr.OCREngineUnavailable as e:
            raise ExtractionFailedError(
                f"Native extraction failed and OCR unavailable: {e}"
            ) from e
    
    try:
        doc = fitz.open(str(file_path))
        page_count = len(doc)
        doc.close()
        
        text_parts: list[str] = []
        all_warnings: list[str] = []
        confidences: list[float] = []
        
        for page_num in range(1, page_count + 1):
            try:
                result = ocr.process_page_with_ocr(
                    pdf_path=file_path,
                    page_number=page_num,
                    engine=ocr_engine,
                    dpi=ocr_dpi,
                )
                text_parts.append(f"\n--- Page {page_num} (OCR) ---\n\n{result.text}")
                confidences.append(result.confidence)
                all_warnings.extend(result.warnings)
            except (ocr.OCREngineUnavailable, ocr.OCRProcessingError) as e:
                logger.error(f"OCR failed on page {page_num}: {e}")
                all_warnings.append(f"Page {page_num} OCR failed: {str(e)[:100]}")
        
        full_text = "\n".join(text_parts)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        
        return ExtractionResult(
            text=full_text,
            page_count=page_count,
            char_count=len(full_text),
            extractor="ocr_only",
            warnings=all_warnings,
            diagnostics={
                "ocr_engine": ocr_engine.name,
                "ocr_confidence": avg_confidence,
                "pages_processed": len(confidences),
            },
        )
        
    except Exception as e:
        raise ExtractionFailedError(f"OCR-only extraction failed: {e}") from e


def _merge_native_and_ocr(
    native_result: ExtractionResult,
    ocr_results: dict[int, ocr.OCRPageResult],
    page_classifications: list[ocr.PageClassification],
    ocr_warnings: list[str],
) -> ExtractionResult:
    """Merge native extraction with OCR results for mixed PDFs.
    
    Args:
        native_result: Native extraction result
        ocr_results: OCR results by page number
        page_classifications: Classification for each page
        ocr_warnings: Warnings from OCR processing
        
    Returns:
        Merged ExtractionResult
    """
    # Rebuild text with OCR content for pages that needed it
    if not PYMUPDF_AVAILABLE:
        return native_result
    
    try:
        # Parse native text by page (if it has page markers)
        native_text_by_page: dict[int, str] = {}
        if "--- Page" in native_result.text:
            parts = native_result.text.split("--- Page ")
            for part in parts[1:]:  # Skip before first marker
                lines = part.split("\n", 1)
                if lines:
                    page_marker = lines[0].strip()
                    page_num = int(page_marker.split()[0])
                    page_text = lines[1] if len(lines) > 1 else ""
                    native_text_by_page[page_num] = page_text
        
        # Merge: use OCR for pages that needed it, native for others
        merged_parts: list[str] = []
        ocr_page_count = 0
        native_page_count = 0
        
        for classification in page_classifications:
            page_num = classification.page_number
            
            if page_num in ocr_results:
                # Use OCR content
                ocr_result = ocr_results[page_num]
                merged_parts.append(
                    f"\n--- Page {page_num} (OCR) ---\n\n{ocr_result.text}"
                )
                ocr_page_count += 1
            elif page_num in native_text_by_page:
                # Use native content
                merged_parts.append(
                    f"\n--- Page {page_num} ---\n\n{native_text_by_page[page_num]}"
                )
                native_page_count += 1
            else:
                # Fallback: blank or couldn't extract
                merged_parts.append(f"\n--- Page {page_num} ---\n\n[No text extracted]")
        
        merged_text = "\n".join(merged_parts)
        
        # Combine warnings
        all_warnings = list(native_result.warnings) + ocr_warnings
        
        # Combine diagnostics
        merged_diagnostics = dict(native_result.diagnostics)
        merged_diagnostics["ocr_pages_processed"] = ocr_page_count
        merged_diagnostics["native_pages_used"] = native_page_count
        merged_diagnostics["total_pages"] = len(page_classifications)
        
        if ocr_results:
            confidences = [r.confidence for r in ocr_results.values()]
            merged_diagnostics["ocr_avg_confidence"] = (
                sum(confidences) / len(confidences) if confidences else 0.0
            )
        
        return ExtractionResult(
            text=merged_text,
            page_count=native_result.page_count,
            char_count=len(merged_text),
            extractor=f"{native_result.extractor}+ocr",
            warnings=all_warnings,
            diagnostics=merged_diagnostics,
            structure=native_result.structure,
        )
        
    except Exception as e:
        logger.error(f"Error merging native and OCR results: {e}")
        # Return native result with warning
        native_result.warnings.append(f"Failed to merge OCR results: {str(e)[:100]}")
        return native_result
