"""Intelligent document chunking with section awareness and provenance.

Preserves page numbers, headings, section hierarchy, and source metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF


@dataclass
class DocumentChunk:
    """A chunk of document text with provenance metadata."""

    text: str
    chunk_index: int
    char_start: int
    char_end: int
    page_numbers: list[int]  # 1-indexed page numbers
    section_heading: str | None
    chunk_type: str  # "text", "table", "figure_caption"
    metadata: dict[str, Any]  # Additional context (e.g., figure refs)


@dataclass
class ChunkingConfig:
    """Configuration for document chunking."""

    target_chunk_size: int = 300  # Target characters per chunk (reduced for better page attribution)
    max_chunk_size: int = 500  # Maximum chunk size
    min_chunk_size: int = 100  # Minimum chunk size
    overlap: int = 50  # Character overlap between chunks
    preserve_sections: bool = True  # Try not to split sections
    preserve_paragraphs: bool = True  # Try not to split paragraphs


class DocumentChunker:
    """Chunk documents intelligently with section awareness."""

    def __init__(self, config: ChunkingConfig | None = None):
        """Initialize chunker.

        Args:
            config: Chunking configuration (uses defaults if None)
        """
        self.config = config or ChunkingConfig()

    def chunk_document(
        self,
        text: str,
        page_count: int | None = None,
        pdf_path: Path | None = None,
    ) -> list[DocumentChunk]:
        """Chunk a document's text intelligently.

        Args:
            text: Extracted document text
            page_count: Number of pages (for validation)
            pdf_path: Optional PDF path for structure extraction

        Returns:
            List of document chunks with metadata
        """
        # Extract page boundaries if available
        page_boundaries = self._extract_page_boundaries(text)

        # Extract section headings
        sections = self._extract_sections(text)

        # Split into paragraphs
        paragraphs = self._split_into_paragraphs(text)

        # Build chunks
        chunks: list[DocumentChunk] = []
        current_chunk: list[str] = []
        current_char_start = 0
        current_char_pos = 0
        chunk_index = 0

        for para in paragraphs:
            para_start = text.find(para, current_char_pos)
            para_end = para_start + len(para)

            # Determine page numbers for this paragraph
            page_nums = self._get_page_numbers(para_start, para_end, page_boundaries)

            # Determine section heading
            section = self._get_section_for_position(para_start, sections)

            # Check if adding this paragraph would exceed max size
            current_text = "\n\n".join(current_chunk)
            if current_chunk and len(current_text) + len(para) + 2 > self.config.max_chunk_size:
                # Flush current chunk
                chunk = DocumentChunk(
                    text=current_text,
                    chunk_index=chunk_index,
                    char_start=current_char_start,
                    char_end=current_char_start + len(current_text),
                    page_numbers=self._get_page_numbers(
                        current_char_start,
                        current_char_start + len(current_text),
                        page_boundaries,
                    ),
                    section_heading=self._get_section_for_position(current_char_start, sections),
                    chunk_type="text",
                    metadata={},
                )
                chunks.append(chunk)

                # Start new chunk with overlap
                if self.config.overlap > 0 and current_chunk:
                    # Keep last paragraph for overlap
                    overlap_text = current_chunk[-1]
                    if len(overlap_text) > self.config.overlap:
                        # Truncate to overlap size
                        overlap_text = overlap_text[-self.config.overlap :]

                    current_chunk = [overlap_text, para]
                    current_char_start = para_start - len(overlap_text)
                else:
                    current_chunk = [para]
                    current_char_start = para_start

                chunk_index += 1
            else:
                # Add paragraph to current chunk
                current_chunk.append(para)
                if not current_chunk or len(current_chunk) == 1:
                    current_char_start = para_start

            current_char_pos = para_end

        # Flush final chunk
        if current_chunk:
            current_text = "\n\n".join(current_chunk)
            if len(current_text) >= self.config.min_chunk_size:
                chunk = DocumentChunk(
                    text=current_text,
                    chunk_index=chunk_index,
                    char_start=current_char_start,
                    char_end=current_char_start + len(current_text),
                    page_numbers=self._get_page_numbers(
                        current_char_start,
                        current_char_start + len(current_text),
                        page_boundaries,
                    ),
                    section_heading=self._get_section_for_position(current_char_start, sections),
                    chunk_type="text",
                    metadata={},
                )
                chunks.append(chunk)

        return chunks

    def _extract_page_boundaries(self, text: str) -> list[int]:
        """Extract character positions of page boundaries.

        Args:
            text: Document text with page markers

        Returns:
            List of character positions where pages start (1-indexed page boundaries)
        """
        boundaries: list[int] = []

        # Look for page markers like "--- Page N ---"
        # Each marker indicates where that page's content starts
        page_pattern = re.compile(r"--- Page (\d+) ---")
        for match in page_pattern.finditer(text):
            page_num = int(match.group(1))
            # Ensure we have enough slots (fill gaps with None if needed)
            while len(boundaries) < page_num:
                boundaries.append(None)
            # Store the position right after this marker + newline
            boundaries[page_num - 1] = match.end()

        # Fill any None values with 0 (shouldn't happen with proper extraction)
        boundaries = [b if b is not None else 0 for b in boundaries]
        
        return boundaries

    def _get_page_numbers(
        self, char_start: int, char_end: int, page_boundaries: list[int]
    ) -> list[int]:
        """Determine which pages a text range spans.

        Args:
            char_start: Start character position
            char_end: End character position
            page_boundaries: Page boundary positions (boundaries[i] = start of page i+1)

        Returns:
            List of 1-indexed page numbers
        """
        if not page_boundaries:
            return [1]

        pages: list[int] = []
        for i, boundary in enumerate(page_boundaries):
            page_num = i + 1
            next_boundary = (
                page_boundaries[i + 1] if i + 1 < len(page_boundaries) else float("inf")
            )

            # Check if this chunk overlaps with this page
            # A chunk overlaps page N if it has any content between boundary[N-1] and boundary[N]
            if char_start < next_boundary and char_end > boundary:
                pages.append(page_num)

        return pages if pages else [1]

    def _extract_sections(self, text: str) -> list[tuple[int, str]]:
        """Extract section headings and their positions.

        Args:
            text: Document text

        Returns:
            List of (position, heading) tuples
        """
        sections: list[tuple[int, str]] = []

        # Pattern 1: Markdown-style headings
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        for match in heading_pattern.finditer(text):
            sections.append((match.start(), match.group(2).strip()))

        # Pattern 2: All-caps lines (common in PDFs)
        caps_pattern = re.compile(r"^([A-Z][A-Z\s]{10,})$", re.MULTILINE)
        for match in caps_pattern.finditer(text):
            heading = match.group(1).strip()
            if len(heading.split()) >= 2:  # At least 2 words
                sections.append((match.start(), heading))

        # Pattern 3: Numbered sections (e.g., "1. Introduction", "2.1 Background")
        numbered_pattern = re.compile(r"^(\d+(?:\.\d+)*\.?\s+)([A-Z][^\.!?]+)$", re.MULTILINE)
        for match in numbered_pattern.finditer(text):
            heading = match.group(2).strip()
            if 5 <= len(heading) <= 100:  # Reasonable heading length
                sections.append((match.start(), heading))

        # Sort by position
        sections.sort(key=lambda x: x[0])

        return sections

    def _get_section_for_position(
        self, position: int, sections: list[tuple[int, str]]
    ) -> str | None:
        """Find the section heading for a given text position.

        Args:
            position: Character position
            sections: List of (position, heading) tuples

        Returns:
            Section heading or None
        """
        if not sections:
            return None

        # Find the last section before this position
        current_section = None
        for sec_pos, heading in sections:
            if sec_pos <= position:
                current_section = heading
            else:
                break

        return current_section

    def _split_into_paragraphs(self, text: str) -> list[str]:
        """Split text into paragraphs.

        Args:
            text: Document text

        Returns:
            List of paragraph strings
        """
        # Split on double newlines or paragraph boundaries
        paragraphs = re.split(r"\n\n+", text)

        # Clean and filter
        cleaned: list[str] = []
        for para in paragraphs:
            para = para.strip()

            # Skip empty or very short paragraphs
            if len(para) < 10:
                continue

            # Skip page markers
            if para.startswith("--- Page") and para.endswith("---"):
                continue

            cleaned.append(para)

        return cleaned
