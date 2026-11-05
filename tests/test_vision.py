"""Tests for vision-language model integration."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pactlyn.documents.vision import (
    VisionError,
    VisionModelUnavailable,
    VisionProcessingError,
    VisionResult,
    VisionService,
    get_default_vision_service,
)


@pytest.fixture
def mock_image():
    """Create a test PIL Image."""
    return Image.new("RGB", (800, 600), color="white")


@pytest.fixture
def vision_service():
    """Create VisionService instance."""
    return VisionService(base_url="http://127.0.0.1:11434", model="llava:7b")


class TestVisionService:
    """Test VisionService initialization and configuration."""

    def test_init_with_model(self):
        """Test service initialization with explicit model."""
        service = VisionService(model="llava:13b")
        assert service._model == "llava:13b"
        assert service.base_url == "http://127.0.0.1:11434"
        assert service.timeout == 60.0

    def test_init_without_model(self):
        """Test service initialization without model (discovery mode)."""
        service = VisionService()
        assert service._model is None
        assert service._discovered_models is None

    def test_init_custom_url(self):
        """Test service initialization with custom Ollama URL."""
        service = VisionService(base_url="http://192.168.1.100:11434/")
        assert service.base_url == "http://192.168.1.100:11434"


class TestModelDiscovery:
    """Test vision model discovery logic."""

    @pytest.mark.asyncio
    async def test_discover_llava_by_name(self):
        """Test discovery identifies LLaVA models by name."""
        service = VisionService()

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "models": [
                {"name": "llava:7b"},
                {"name": "llava:13b"},
                {"name": "qwen2.5:7b"},  # Not a vision model
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            models = await service.discover_vision_models()

        assert "llava:7b" in models
        assert "llava:13b" in models
        assert "qwen2.5:7b" not in models

    @pytest.mark.asyncio
    async def test_discover_bakllava(self):
        """Test discovery identifies BakLLaVA models."""
        service = VisionService()

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "models": [{"name": "bakllava:latest"}]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            models = await service.discover_vision_models()

        assert "bakllava:latest" in models

    @pytest.mark.asyncio
    async def test_discover_no_vision_models(self):
        """Test discovery when no vision models installed."""
        service = VisionService()

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "models": [
                {"name": "qwen2.5:7b"},
                {"name": "mistral:latest"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            models = await service.discover_vision_models()

        assert len(models) == 0

    @pytest.mark.asyncio
    async def test_discover_connection_error(self):
        """Test discovery handles Ollama connection errors."""
        service = VisionService()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=Exception("Connection refused")
            )

            with pytest.raises(VisionModelUnavailable):
                await service.discover_vision_models()

    @pytest.mark.asyncio
    async def test_get_model_explicit(self):
        """Test get_model returns explicitly configured model."""
        service = VisionService(model="llava:7b")
        model = await service.get_model()
        assert model == "llava:7b"

    @pytest.mark.asyncio
    async def test_get_model_discovered(self):
        """Test get_model discovers and returns first available model."""
        service = VisionService()

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "models": [{"name": "llava:13b"}, {"name": "llava:7b"}]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            model = await service.get_model()

        assert model == "llava:13b"  # First discovered

    @pytest.mark.asyncio
    async def test_get_model_none_available(self):
        """Test get_model raises error when no vision models available."""
        service = VisionService()

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"models": [{"name": "qwen2.5:7b"}]}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(VisionModelUnavailable) as exc_info:
                await service.get_model()

        assert "No vision-capable models found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_is_available_true(self):
        """Test is_available returns True when vision models exist."""
        service = VisionService()

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"models": [{"name": "llava:7b"}]}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            available = await service.is_available()

        assert available is True

    @pytest.mark.asyncio
    async def test_is_available_false(self):
        """Test is_available returns False when no vision models."""
        service = VisionService()

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"models": [{"name": "qwen2.5:7b"}]}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            available = await service.is_available()

        assert available is False


class TestImageProcessing:
    """Test image encoding and vision inference."""

    def test_image_to_base64_rgb(self, mock_image):
        """Test RGB image encoding to base64."""
        b64_str = VisionService._image_to_base64(mock_image)
        assert isinstance(b64_str, str)
        assert len(b64_str) > 0
        # Base64 encoded JPEG should start with /9j/
        assert b64_str.startswith("/9j/") or b64_str.startswith("iVBORw==")

    def test_image_to_base64_rgba(self):
        """Test RGBA image is converted to RGB before encoding."""
        rgba_image = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        b64_str = VisionService._image_to_base64(rgba_image)
        assert isinstance(b64_str, str)
        assert len(b64_str) > 0

    @pytest.mark.asyncio
    async def test_describe_image_success(self, vision_service, mock_image):
        """Test successful image description."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "message": {"content": "A white image."}
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await vision_service.describe_image(mock_image)

        assert isinstance(result, VisionResult)
        assert result.description == "A white image."
        assert result.model == "llava:7b"
        assert result.metadata["image_size"] == (800, 600)
        assert result.metadata["image_mode"] == "RGB"

    @pytest.mark.asyncio
    async def test_describe_image_with_custom_prompt(self, vision_service, mock_image):
        """Test image description with custom prompt."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "message": {"content": "This is a screenshot of a login form."}
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await vision_service.describe_image(
                mock_image, prompt="What UI elements are visible?"
            )

        assert "screenshot" in result.description.lower()
        assert result.metadata["prompt"] == "What UI elements are visible?"

    @pytest.mark.asyncio
    async def test_describe_image_with_page_number(self, vision_service, mock_image):
        """Test image description includes page number."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "message": {"content": "Document page content."}
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await vision_service.describe_image(mock_image, page_number=5)

        assert result.page_number == 5

    @pytest.mark.asyncio
    async def test_describe_image_empty_response(self, vision_service, mock_image):
        """Test error handling for empty vision model response."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"message": {"content": ""}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(VisionProcessingError) as exc_info:
                await vision_service.describe_image(mock_image)

        assert "empty description" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_describe_image_http_error(self, vision_service, mock_image):
        """Test error handling for HTTP failures."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=Exception("HTTP 500")
            )

            with pytest.raises(VisionProcessingError):
                await vision_service.describe_image(mock_image)


class TestSpecializedVisionTasks:
    """Test specialized vision functions like tables and charts."""

    @pytest.mark.asyncio
    async def test_extract_table_structure(self, vision_service, mock_image):
        """Test table extraction with specialized prompt."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "message": {
                "content": "| Header 1 | Header 2 |\n|----------|----------|\n| Value 1  | Value 2  |"
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await vision_service.extract_table_structure(mock_image)

        assert "Header" in result.description
        assert "Value" in result.description

    @pytest.mark.asyncio
    async def test_extract_chart_insights(self, vision_service, mock_image):
        """Test chart analysis with specialized prompt."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "message": {"content": "Bar chart showing sales data trending upward."}
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await vision_service.extract_chart_insights(mock_image)

        assert "chart" in result.description.lower()


class TestVisionResult:
    """Test VisionResult dataclass."""

    def test_vision_result_creation(self):
        """Test VisionResult creation and defaults."""
        result = VisionResult(
            description="Test description",
            model="llava:7b",
        )

        assert result.description == "Test description"
        assert result.model == "llava:7b"
        assert result.confidence is None
        assert result.page_number is None
        assert result.warnings == []
        assert result.metadata == {}

    def test_vision_result_with_all_fields(self):
        """Test VisionResult with all fields populated."""
        result = VisionResult(
            description="Full result",
            model="llava:13b",
            confidence=0.95,
            page_number=3,
            metadata={"source": "test.pdf"},
            warnings=["Low resolution"],
        )

        assert result.confidence == 0.95
        assert result.page_number == 3
        assert result.metadata["source"] == "test.pdf"
        assert len(result.warnings) == 1


@pytest.mark.asyncio
async def test_get_default_vision_service():
    """Test default vision service factory."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {"models": [{"name": "llava:7b"}]}

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=mock_response
        )

        service = await get_default_vision_service()

    assert isinstance(service, VisionService)


@pytest.mark.asyncio
async def test_get_default_vision_service_unavailable():
    """Test default factory raises error when no models available."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {"models": []}

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=mock_response
        )

        with pytest.raises(VisionModelUnavailable) as exc_info:
            await get_default_vision_service()

    assert "No vision-capable models found" in str(exc_info.value)


# Mark tests that require real Ollama + vision models
@pytest.mark.live
class TestLiveVision:
    """Live tests requiring actual Ollama + vision model (marked for manual runs)."""

    @pytest.mark.asyncio
    async def test_real_ollama_discovery(self):
        """Test discovery against real Ollama instance."""
        service = VisionService()
        models = await service.discover_vision_models()
        # Should find at least one vision model if llava is installed
        assert isinstance(models, list)

    @pytest.mark.asyncio
    async def test_real_image_description(self):
        """Test real image description with actual vision model."""
        service = VisionService()

        # Create simple test image
        test_image = Image.new("RGB", (400, 300), color="blue")

        result = await service.describe_image(
            test_image, prompt="What color is this image?"
        )

        assert isinstance(result, VisionResult)
        assert len(result.description) > 0
        assert "blue" in result.description.lower()
