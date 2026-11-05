"""Vision-language model integration for document image understanding.

Supports local vision models through Ollama for:
- Standalone image descriptions
- PDF page visual understanding
- Charts, diagrams, tables, screenshots
- Visual context extraction

All inference remains local - no cloud APIs.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

logger = logging.getLogger(__name__)


class VisionError(Exception):
    """Base exception for vision processing errors."""


class VisionModelUnavailable(VisionError):
    """Vision model is not available or not configured."""


class VisionProcessingError(VisionError):
    """Vision inference failed."""


@dataclass
class VisionResult:
    """Result from vision model inference."""

    description: str
    model: str
    confidence: float | None = None
    page_number: int | None = None
    metadata: dict[str, Any] | None = None
    warnings: list[str] | None = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
        if self.metadata is None:
            self.metadata = {}


class VisionService:
    """Service for vision-language model inference through Ollama."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str | None = None,
        timeout: float = 60.0,
    ):
        """Initialize vision service.

        Args:
            base_url: Ollama server URL
            model: Optional specific model name. If None, discovers vision-capable models.
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self._model = model
        self.timeout = timeout
        self._discovered_models: list[str] | None = None

    async def discover_vision_models(self) -> list[str]:
        """Discover available vision-capable models from Ollama.

        Returns:
            List of model names with vision capabilities

        Raises:
            VisionModelUnavailable: If no vision models found or Ollama unreachable
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()

            models = response.json().get("models", [])
            vision_models = []

            for model in models:
                model_name = model.get("name", "")
                # Check for vision indicators in name
                if any(
                    indicator in model_name.lower()
                    for indicator in ["llava", "vision", "bakllava", "minicpm-v", "cogvlm"]
                ):
                    vision_models.append(model_name)
                    continue

                # Check model details for vision capability
                try:
                    async with httpx.AsyncClient(timeout=10.0) as detail_client:
                        detail_response = await detail_client.post(
                            f"{self.base_url}/api/show",
                            json={"name": model_name},
                        )
                        if detail_response.is_success:
                            details = detail_response.json()

                            # Check families for vision indicators
                            families = details.get("details", {}).get("families", [])
                            if families and any(
                                "llava" in str(f).lower() or "vision" in str(f).lower()
                                for f in families
                            ):
                                vision_models.append(model_name)
                                continue

                            # Check explicit capabilities
                            capabilities = details.get("capabilities", {})
                            if isinstance(capabilities, dict) and capabilities.get("vision"):
                                vision_models.append(model_name)
                            elif isinstance(capabilities, list) and "vision" in capabilities:
                                vision_models.append(model_name)

                except Exception as e:
                    logger.debug(f"Could not check details for {model_name}: {e}")
                    continue

            self._discovered_models = vision_models
            return vision_models

        except httpx.HTTPError as e:
            raise VisionModelUnavailable(f"Cannot connect to Ollama: {e}") from e

    async def get_model(self) -> str:
        """Get configured or discovered vision model.

        Returns:
            Model name to use for vision inference

        Raises:
            VisionModelUnavailable: If no vision model available
        """
        if self._model:
            return self._model

        if self._discovered_models is None:
            await self.discover_vision_models()

        if not self._discovered_models:
            raise VisionModelUnavailable(
                "No vision-capable models found. Install a vision model like 'ollama pull llava:7b'"
            )

        # Return first discovered model
        return self._discovered_models[0]

    async def is_available(self) -> bool:
        """Check if vision service is available.

        Returns:
            True if at least one vision model is available
        """
        try:
            models = await self.discover_vision_models()
            return len(models) > 0
        except VisionModelUnavailable:
            return False

    @staticmethod
    def _image_to_base64(image: Image.Image) -> str:
        """Convert PIL Image to base64 string for Ollama API.

        Args:
            image: PIL Image object

        Returns:
            Base64-encoded image string
        """
        buffer = BytesIO()
        # Convert RGBA to RGB if necessary
        if image.mode == "RGBA":
            rgb_image = Image.new("RGB", image.size, (255, 255, 255))
            rgb_image.paste(image, mask=image.split()[3])
            image = rgb_image
        image.save(buffer, format="JPEG", quality=95)
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode("utf-8")

    async def describe_image(
        self,
        image: Image.Image,
        prompt: str = "Describe this image in detail.",
        page_number: int | None = None,
    ) -> VisionResult:
        """Generate description of an image using vision model.

        Args:
            image: PIL Image to analyze
            prompt: Instruction prompt for the vision model
            page_number: Optional page number for context

        Returns:
            VisionResult with description and metadata

        Raises:
            VisionModelUnavailable: If no vision model available
            VisionProcessingError: If inference fails
        """
        model = await self.get_model()

        try:
            # Convert image to base64
            image_b64 = self._image_to_base64(image)

            # Call Ollama vision API
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt,
                                "images": [image_b64],
                            }
                        ],
                        "stream": False,
                    },
                )
                response.raise_for_status()

            result = response.json()
            description = result.get("message", {}).get("content", "")

            if not description:
                raise VisionProcessingError("Vision model returned empty description")

            return VisionResult(
                description=description.strip(),
                model=model,
                page_number=page_number,
                metadata={
                    "image_size": image.size,
                    "image_mode": image.mode,
                    "prompt": prompt,
                },
            )

        except httpx.HTTPError as e:
            raise VisionProcessingError(f"Vision API request failed: {e}") from e
        except (KeyError, ValueError) as e:
            raise VisionProcessingError(f"Invalid vision API response: {e}") from e

    async def describe_image_file(
        self, image_path: Path, prompt: str = "Describe this image in detail."
    ) -> VisionResult:
        """Describe an image from a file path.

        Args:
            image_path: Path to image file
            prompt: Instruction prompt for vision model

        Returns:
            VisionResult with description

        Raises:
            VisionModelUnavailable: If no vision model available
            VisionProcessingError: If file cannot be read or inference fails
        """
        try:
            image = Image.open(image_path)
            result = await self.describe_image(image, prompt=prompt)
            result.metadata["source_file"] = str(image_path)
            return result
        except IOError as e:
            raise VisionProcessingError(f"Cannot read image file {image_path}: {e}") from e

    async def describe_pdf_page(
        self,
        pdf_path: Path,
        page_number: int,
        dpi: int = 150,
        prompt: str = "Describe this document page, including any text, diagrams, charts, or visual elements.",
    ) -> VisionResult:
        """Extract visual understanding from a PDF page.

        Args:
            pdf_path: Path to PDF file
            page_number: Page number (1-indexed)
            dpi: Resolution for page rendering
            prompt: Instruction prompt for vision model

        Returns:
            VisionResult with page description

        Raises:
            VisionModelUnavailable: If no vision model available
            VisionProcessingError: If PDF cannot be read or inference fails
        """
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(pdf_path)

            if page_number < 1 or page_number > len(doc):
                raise VisionProcessingError(
                    f"Page {page_number} out of range (PDF has {len(doc)} pages)"
                )

            # Get page (0-indexed)
            page = doc[page_number - 1]

            # Render page to image
            pix = page.get_pixmap(dpi=dpi)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            doc.close()

            # Get description
            result = await self.describe_image(image, prompt=prompt, page_number=page_number)
            result.metadata["source_pdf"] = str(pdf_path)
            result.metadata["render_dpi"] = dpi

            return result

        except ImportError as e:
            raise VisionProcessingError("PyMuPDF not installed") from e
        except Exception as e:
            raise VisionProcessingError(f"PDF page processing failed: {e}") from e

    async def extract_table_structure(
        self,
        image: Image.Image,
        page_number: int | None = None,
    ) -> VisionResult:
        """Extract table structure and content from an image using vision model.

        Args:
            image: PIL Image containing a table
            page_number: Optional page number for context

        Returns:
            VisionResult with table description

        Raises:
            VisionModelUnavailable: If no vision model available
            VisionProcessingError: If inference fails
        """
        prompt = (
            "This image contains a table. Extract the table structure and content. "
            "Describe the headers, rows, columns, and all data values. "
            "Format as markdown table if possible."
        )
        return await self.describe_image(image, prompt=prompt, page_number=page_number)

    async def extract_chart_insights(
        self,
        image: Image.Image,
        page_number: int | None = None,
    ) -> VisionResult:
        """Extract insights from charts, graphs, and diagrams.

        Args:
            image: PIL Image containing a chart or diagram
            page_number: Optional page number for context

        Returns:
            VisionResult with chart analysis

        Raises:
            VisionModelUnavailable: If no vision model available
            VisionProcessingError: If inference fails
        """
        prompt = (
            "This image contains a chart, graph, or diagram. "
            "Describe what it shows: type of visualization, axes, data trends, "
            "key values, labels, and any important insights."
        )
        return await self.describe_image(image, prompt=prompt, page_number=page_number)


async def get_default_vision_service() -> VisionService:
    """Get default vision service instance with discovered model.

    Returns:
        VisionService instance

    Raises:
        VisionModelUnavailable: If no vision models available
    """
    service = VisionService()
    if not await service.is_available():
        raise VisionModelUnavailable(
            "No vision-capable models found in Ollama. "
            "Install one with: ollama pull llava:7b"
        )
    return service
