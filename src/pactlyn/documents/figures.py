"""PDF figure extraction and visual intelligence.

Extracts embedded images, charts, diagrams and other visual elements from PDFs.
Generates descriptions using local vision models.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

# Try importing PyMuPDF
try:
    import pymupdf as fitz

    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    logger.warning("PyMuPDF not available - figure extraction disabled")


class FigureExtractionError(Exception):
    """Error during figure extraction."""


@dataclass
class BoundingBox:
    """Bounding box coordinates in PDF points."""

    x0: float
    y0: float
    x1: float
    y1: float
    width: float
    height: float

    @property
    def area(self) -> float:
        """Calculate bounding box area."""
        return self.width * self.height

    def overlaps(self, other: BoundingBox, threshold: float = 0.9) -> bool:
        """Check if this bbox significantly overlaps another.

        Args:
            other: Another bounding box
            threshold: Overlap ratio threshold (0-1)

        Returns:
            True if overlap ratio > threshold
        """
        # Calculate intersection
        x_left = max(self.x0, other.x0)
        y_top = max(self.y0, other.y0)
        x_right = min(self.x1, other.x1)
        y_bottom = min(self.y1, other.y1)

        if x_right < x_left or y_bottom < y_top:
            return False  # No overlap

        intersection_area = (x_right - x_left) * (y_bottom - y_top)
        smaller_area = min(self.area, other.area)

        if smaller_area == 0:
            return False

        overlap_ratio = intersection_area / smaller_area
        return overlap_ratio >= threshold


@dataclass
class ExtractedFigure:
    """A figure extracted from a PDF page."""

    image: Image.Image
    page_number: int  # 1-indexed
    bbox: BoundingBox
    image_hash: str  # SHA256 of image bytes
    image_index: int  # Index on this page
    xref: int | None  # PDF object reference
    width: int  # Original width in pixels
    height: int  # Original height in pixels
    format: str | None  # Image format (JPEG, PNG, etc.)
    colorspace: str | None  # Color space
    bpc: int | None  # Bits per component

    @staticmethod
    def compute_hash(image: Image.Image) -> str:
        """Compute SHA256 hash of image bytes."""
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return hashlib.sha256(buffer.read()).hexdigest()


@dataclass
class FigureContext:
    """Contextual information around a figure."""

    caption: str | None = None
    nearby_headings: list[str] | None = None
    nearby_paragraphs: list[str] | None = None
    distance_to_caption: float | None = None  # Distance in points


@dataclass
class FigureIntelligence:
    """AI-generated understanding of a figure."""

    description: str
    model_used: str
    confidence: float | None = None
    figure_type: str | None = None  # "chart", "diagram", "photo", "screenshot", "table"
    contains_text: bool = False
    warnings: list[str] | None = None


class FigureExtractor:
    """Extract figures from PDF documents."""

    def __init__(
        self,
        min_width: int = 100,
        min_height: int = 100,
        min_area: int = 10000,
        skip_small: bool = True,
    ):
        """Initialize figure extractor.

        Args:
            min_width: Minimum figure width in pixels
            min_height: Minimum figure height in pixels
            min_area: Minimum figure area in pixels²
            skip_small: Whether to skip figures below minimums
        """
        if not PYMUPDF_AVAILABLE:
            raise FigureExtractionError("PyMuPDF not available")

        self.min_width = min_width
        self.min_height = min_height
        self.min_area = min_area
        self.skip_small = skip_small

    def extract_figures_from_pdf(
        self, pdf_path: Path, max_pages: int | None = None
    ) -> list[ExtractedFigure]:
        """Extract all figures from a PDF.

        Args:
            pdf_path: Path to PDF file
            max_pages: Maximum number of pages to process (None = all)

        Returns:
            List of extracted figures with metadata

        Raises:
            FigureExtractionError: If extraction fails
        """
        try:
            doc = fitz.open(pdf_path)
            all_figures: list[ExtractedFigure] = []
            seen_hashes: set[str] = set()  # Track duplicates

            pages_to_process = min(len(doc), max_pages) if max_pages else len(doc)

            for page_num in range(pages_to_process):
                page = doc[page_num]
                figures = self._extract_figures_from_page(page, page_num + 1)

                # Deduplicate across pages
                for figure in figures:
                    if figure.image_hash not in seen_hashes:
                        all_figures.append(figure)
                        seen_hashes.add(figure.image_hash)
                    else:
                        logger.debug(
                            f"Skipping duplicate figure on page {page_num + 1} "
                            f"(hash: {figure.image_hash[:16]}...)"
                        )

            doc.close()
            logger.info(
                f"Extracted {len(all_figures)} unique figures from {pdf_path.name} "
                f"({pages_to_process} pages)"
            )
            return all_figures

        except Exception as e:
            raise FigureExtractionError(f"Failed to extract figures: {e}") from e

    def _extract_figures_from_page(
        self, page: fitz.Page, page_number: int
    ) -> list[ExtractedFigure]:
        """Extract figures from a single PDF page.

        Args:
            page: PyMuPDF page object
            page_number: Page number (1-indexed)

        Returns:
            List of figures on this page
        """
        figures: list[ExtractedFigure] = []
        image_list = page.get_images(full=True)

        if not image_list:
            return figures

        page_rect = page.rect
        page_area = page_rect.width * page_rect.height

        # Get bounding boxes for all images
        image_info_list = page.get_image_info()

        for img_index, img_info in enumerate(image_info_list):
            try:
                # Get image bounding box
                bbox_tuple = img_info.get("bbox")
                if not bbox_tuple:
                    continue

                bbox = BoundingBox(
                    x0=bbox_tuple[0],
                    y0=bbox_tuple[1],
                    x1=bbox_tuple[2],
                    y1=bbox_tuple[3],
                    width=bbox_tuple[2] - bbox_tuple[0],
                    height=bbox_tuple[3] - bbox_tuple[1],
                )

                # Skip if too small
                if self.skip_small:
                    if (
                        bbox.width < self.min_width
                        or bbox.height < self.min_height
                        or bbox.area < self.min_area
                    ):
                        logger.debug(
                            f"Skipping small figure on page {page_number}: "
                            f"{bbox.width:.0f}x{bbox.height:.0f}px"
                        )
                        continue

                # Skip if covers >95% of page (likely full-page scan)
                coverage = bbox.area / page_area
                if coverage > 0.95:
                    logger.debug(
                        f"Skipping full-page image on page {page_number} "
                        f"(coverage: {coverage:.1%})"
                    )
                    continue

                # Extract the actual image
                xref = img_info.get("xref")
                if xref is None:
                    # Try to get from image_list
                    if img_index < len(image_list):
                        xref = image_list[img_index][0]

                if xref is None:
                    logger.warning(f"Could not get xref for image {img_index} on page {page_number}")
                    continue

                # Get image data
                pix = fitz.Pixmap(page.parent, xref)

                # Convert to RGB if necessary
                if pix.n - pix.alpha > 3:  # CMYK or similar
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                # Convert to PIL Image
                img_bytes = pix.tobytes("png")
                image = Image.open(BytesIO(img_bytes))

                # Compute hash
                image_hash = ExtractedFigure.compute_hash(image)

                # Check for duplicates on same page
                duplicate_on_page = any(
                    fig.image_hash == image_hash for fig in figures
                )
                if duplicate_on_page:
                    logger.debug(
                        f"Skipping duplicate on page {page_number} "
                        f"(hash: {image_hash[:16]}...)"
                    )
                    continue

                # Create figure
                figure = ExtractedFigure(
                    image=image,
                    page_number=page_number,
                    bbox=bbox,
                    image_hash=image_hash,
                    image_index=img_index,
                    xref=xref,
                    width=pix.width,
                    height=pix.height,
                    format=img_info.get("ext", "").upper() or None,
                    colorspace=img_info.get("colorspace") or None,
                    bpc=img_info.get("bpc"),
                )

                figures.append(figure)
                logger.debug(
                    f"Extracted figure from page {page_number}: "
                    f"{figure.width}x{figure.height}px, "
                    f"bbox=({bbox.x0:.0f},{bbox.y0:.0f},{bbox.x1:.0f},{bbox.y1:.0f})"
                )

            except Exception as e:
                logger.warning(
                    f"Failed to extract image {img_index} from page {page_number}: {e}"
                )
                continue

        return figures

    def deduplicate_figures(
        self, figures: list[ExtractedFigure]
    ) -> list[ExtractedFigure]:
        """Remove duplicate figures based on image hash.

        Args:
            figures: List of extracted figures

        Returns:
            List with duplicates removed
        """
        seen_hashes: set[str] = set()
        unique_figures: list[ExtractedFigure] = []

        for figure in figures:
            if figure.image_hash not in seen_hashes:
                unique_figures.append(figure)
                seen_hashes.add(figure.image_hash)

        removed = len(figures) - len(unique_figures)
        if removed > 0:
            logger.info(f"Removed {removed} duplicate figures")

        return unique_figures


def extract_context_for_figure(
    page: fitz.Page, figure_bbox: BoundingBox, search_radius: float = 100
) -> FigureContext:
    """Extract contextual text around a figure.

    Args:
        page: PyMuPDF page object
        figure_bbox: Figure bounding box
        search_radius: Radius in points to search for context

    Returns:
        FigureContext with captions and nearby text
    """
    context = FigureContext()

    # Extract all text blocks on the page
    text_blocks = page.get_text("blocks")

    # Look for captions (typically right below the figure)
    caption_candidates = []
    heading_candidates = []
    paragraph_candidates = []

    for block in text_blocks:
        if len(block) < 5:
            continue

        x0, y0, x1, y1, text, block_no, block_type = block[:7]
        text = text.strip()

        if not text:
            continue

        block_bbox = BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1, width=x1 - x0, height=y1 - y0)

        # Calculate distance from figure
        # Distance from figure bottom to text top
        vertical_distance = block_bbox.y0 - figure_bbox.y1

        # Check if below figure and within search radius
        if 0 < vertical_distance < search_radius:
            # Check horizontal alignment
            horizontal_overlap = (
                min(block_bbox.x1, figure_bbox.x1) - max(block_bbox.x0, figure_bbox.x0)
            )
            if horizontal_overlap > 0:
                # Likely caption if starts with "Figure", "Fig", "Table", etc.
                text_lower = text.lower()
                if any(
                    text_lower.startswith(prefix)
                    for prefix in ["figure", "fig.", "fig ", "table", "chart", "diagram"]
                ):
                    caption_candidates.append((vertical_distance, text))
                else:
                    paragraph_candidates.append((vertical_distance, text))

        # Check if above figure (potential heading)
        elif -search_radius < vertical_distance < 0:
            horizontal_overlap = (
                min(block_bbox.x1, figure_bbox.x1) - max(block_bbox.x0, figure_bbox.x0)
            )
            if horizontal_overlap > 0:
                # Short text above might be a heading
                if len(text) < 100:
                    heading_candidates.append((-vertical_distance, text))

    # Select best caption (closest)
    if caption_candidates:
        caption_candidates.sort(key=lambda x: x[0])
        context.caption = caption_candidates[0][1]
        context.distance_to_caption = caption_candidates[0][0]

    # Select nearby headings
    if heading_candidates:
        heading_candidates.sort(key=lambda x: x[0])
        context.nearby_headings = [text for _, text in heading_candidates[:3]]

    # Select nearby paragraphs
    if paragraph_candidates:
        paragraph_candidates.sort(key=lambda x: x[0])
        context.nearby_paragraphs = [text for _, text in paragraph_candidates[:2]]

    return context


async def generate_figure_intelligence(
    figure: ExtractedFigure,
    vision_service,  # VisionService from Phase 3
    include_context: FigureContext | None = None,
) -> FigureIntelligence:
    """Generate AI-powered understanding of a figure.

    Args:
        figure: Extracted figure
        vision_service: VisionService instance
        include_context: Optional context to inform the description

    Returns:
        FigureIntelligence with description and metadata

    Raises:
        VisionError: If vision processing fails
    """
    from pactlyn.documents.vision import VisionProcessingError

    # Build prompt based on context
    if include_context and include_context.caption:
        prompt = (
            f"Describe this figure in detail. "
            f"The document caption is: '{include_context.caption}'. "
            f"Explain what the figure shows, including any charts, diagrams, "
            f"labels, trends, or key information."
        )
    else:
        prompt = (
            "Describe this figure in detail. "
            "Identify the type of visual (chart, diagram, photo, screenshot, table). "
            "Explain what it shows, including any labels, trends, relationships, "
            "or key information. Be specific about values and data when visible."
        )

    try:
        result = await vision_service.describe_image(
            figure.image,
            prompt=prompt,
            page_number=figure.page_number,
        )

        # Classify figure type from description
        description_lower = result.description.lower()
        figure_type = None
        if any(word in description_lower for word in ["chart", "graph", "plot"]):
            figure_type = "chart"
        elif any(word in description_lower for word in ["diagram", "flowchart", "schematic"]):
            figure_type = "diagram"
        elif any(word in description_lower for word in ["table", "spreadsheet"]):
            figure_type = "table"
        elif any(word in description_lower for word in ["screenshot", "interface", "ui"]):
            figure_type = "screenshot"
        elif any(word in description_lower for word in ["photo", "photograph", "image"]):
            figure_type = "photo"

        # Check if vision model detected text
        contains_text = any(
            word in description_lower
            for word in ["text", "label", "title", "heading", "caption", "word"]
        )

        intelligence = FigureIntelligence(
            description=result.description,
            model_used=result.model,
            confidence=result.confidence,
            figure_type=figure_type,
            contains_text=contains_text,
            warnings=result.warnings if result.warnings else None,
        )

        logger.info(
            f"Generated intelligence for figure on page {figure.page_number}: "
            f"type={figure_type}, model={result.model}"
        )

        return intelligence

    except VisionProcessingError as e:
        logger.error(f"Vision processing failed for figure: {e}")
        raise
