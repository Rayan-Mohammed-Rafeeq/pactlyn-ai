"""Tests for Ollama model discovery service."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

from pactlyn.llm.discovery import (
    CapabilityState,
    ConnectionStatus,
    ModelCapabilities,
    ModelDetails,
    OllamaDiscoveryService,
)
from pactlyn.llm.interfaces import LLMUnavailable


@pytest.fixture
def discovery_service():
    return OllamaDiscoveryService(base_url="http://localhost:11434", timeout=15.0)


@pytest.fixture
def mock_httpx_client():
    """Mock httpx.AsyncClient for testing without real HTTP calls."""
    with patch("pactlyn.llm.discovery.httpx.AsyncClient") as mock:
        yield mock


class TestConnectionCheck:
    """Tests for Ollama connection status checking."""

    @pytest.mark.asyncio
    async def test_connection_successful(self, discovery_service, mock_httpx_client):
        """Test successful connection to Ollama server."""
        # Arrange
        mock_response = Mock()
        mock_response.is_success = True
        mock_response.json.return_value = {"version": "0.1.25"}
        
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_httpx_client.return_value = mock_context
        
        # Act
        status = await discovery_service.check_connection()
        
        # Assert
        assert status.connected is True
        assert status.server_version == "0.1.25"
        assert status.base_url == "http://localhost:11434"
        assert status.error is None
        assert isinstance(status.last_checked, datetime)

    @pytest.mark.asyncio
    async def test_connection_refused(self, discovery_service, mock_httpx_client):
        """Test connection refused (Ollama not running)."""
        # Arrange
        import httpx
        mock_httpx_client.return_value.__aenter__.side_effect = httpx.ConnectError("Connection refused")
        
        # Act
        status = await discovery_service.check_connection()
        
        # Assert
        assert status.connected is False
        assert "Connection refused" in (status.error or "")
        assert status.server_version is None

    @pytest.mark.asyncio
    async def test_connection_timeout(self, discovery_service, mock_httpx_client):
        """Test connection timeout."""
        # Arrange
        import httpx
        mock_httpx_client.return_value.__aenter__.side_effect = httpx.TimeoutException("timeout")
        
        # Act
        status = await discovery_service.check_connection()
        
        # Assert
        assert status.connected is False
        assert "timeout" in (status.error or "").lower()


class TestListModels:
    """Tests for listing installed models."""

    @pytest.mark.asyncio
    async def test_list_models_success(self, discovery_service, mock_httpx_client):
        """Test successful model listing."""
        # Arrange
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3.2:3b"},
                {"name": "qwen2.5:7b"},
                {"name": "nomic-embed-text"},
            ]
        }
        
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_httpx_client.return_value = mock_context
        
        # Act
        models = await discovery_service.list_installed_models()
        
        # Assert
        assert len(models) == 3
        assert "llama3.2:3b" in models
        assert "qwen2.5:7b" in models
        assert "nomic-embed-text" in models

    @pytest.mark.asyncio
    async def test_list_models_empty(self, discovery_service, mock_httpx_client):
        """Test listing when no models installed."""
        # Arrange
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"models": []}
        
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_httpx_client.return_value = mock_context
        
        # Act
        models = await discovery_service.list_installed_models()
        
        # Assert
        assert models == []

    @pytest.mark.asyncio
    async def test_list_models_unavailable(self, discovery_service, mock_httpx_client):
        """Test listing when Ollama is unavailable."""
        # Arrange
        import httpx
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.get = AsyncMock(side_effect=httpx.HTTPError("error"))
        mock_httpx_client.return_value = mock_context
        
        # Act & Assert
        with pytest.raises(LLMUnavailable):
            await discovery_service.list_installed_models()


class TestModelDetails:
    """Tests for getting model metadata."""

    @pytest.mark.asyncio
    async def test_get_model_details_success(self, discovery_service, mock_httpx_client):
        """Test successful model details retrieval."""
        # Arrange
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "digest": "sha256:abc123",
            "details": {
                "family": "llama",
                "families": ["llama"],
                "parameter_size": "7B",
                "quantization_level": "Q4_0",
                "format": "gguf",
            },
            "model_info": {
                "context_length": 8192,
            },
            "size": 4661211136,
            "modified_at": "2024-11-05T12:00:00Z",
        }
        
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        mock_httpx_client.return_value = mock_context
        
        # Act
        details = await discovery_service.get_model_details("qwen2.5:7b")
        
        # Assert
        assert details.name == "qwen2.5"
        assert details.tag == "7b"
        assert details.digest == "sha256:abc123"
        assert details.family == "llama"
        assert details.parameter_size == "7B"
        assert details.quantization == "Q4_0"
        assert details.context_length == 8192
        assert details.size_bytes == 4661211136

    @pytest.mark.asyncio
    async def test_get_model_details_minimal_metadata(self, discovery_service, mock_httpx_client):
        """Test handling model with minimal metadata."""
        # Arrange
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "details": {},
            "model_info": {},
        }
        
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        mock_httpx_client.return_value = mock_context
        
        # Act
        details = await discovery_service.get_model_details("simple-model")
        
        # Assert
        assert details.name == "simple-model"
        assert details.tag == "latest"
        assert details.family is None
        assert details.context_length is None


class TestCapabilityClassification:
    """Tests for model capability classification."""

    @pytest.mark.asyncio
    async def test_classify_embedding_model(self, discovery_service):
        """Test classification of embedding model."""
        # Arrange
        model = ModelDetails(
            name="nomic-embed-text",
            tag="latest",
            family="nomic",
            families=["bert", "nomic"],
        )
        
        # Act
        caps = await discovery_service.classify_capabilities(model)
        
        # Assert
        assert caps.embedding in (CapabilityState.LIKELY, CapabilityState.SUPPORTED)
        assert caps.text_generation == CapabilityState.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_classify_vision_model(self, discovery_service):
        """Test classification of vision model."""
        # Arrange
        model = ModelDetails(
            name="llava",
            tag="7b",
            family="llava",
            families=["llava", "vision"],
        )
        
        # Act
        caps = await discovery_service.classify_capabilities(model)
        
        # Assert
        assert caps.vision_language in (CapabilityState.LIKELY, CapabilityState.SUPPORTED)

    @pytest.mark.asyncio
    async def test_classify_text_model(self, discovery_service):
        """Test classification of text generation model."""
        # Arrange
        model = ModelDetails(
            name="qwen2.5",
            tag="7b",
            family="qwen2",
            families=["qwen2"],
        )
        
        # Act
        caps = await discovery_service.classify_capabilities(model)
        
        # Assert
        assert caps.text_generation in (CapabilityState.LIKELY, CapabilityState.SUPPORTED)
        assert caps.embedding == CapabilityState.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_classify_explicit_capabilities(self, discovery_service):
        """Test classification using explicit capability metadata."""
        # Arrange
        model = ModelDetails(
            name="multimodal-model",
            tag="latest",
            capabilities={"vision": True, "embedding": False},
        )
        
        # Act
        caps = await discovery_service.classify_capabilities(model)
        
        # Assert
        assert caps.vision_language == CapabilityState.SUPPORTED


class TestEmbeddingVerification:
    """Tests for embedding capability verification."""

    @pytest.mark.asyncio
    async def test_verify_embedding_success(self, discovery_service, mock_httpx_client):
        """Test successful embedding verification."""
        # Arrange
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "embeddings": [[0.1] * 768]
        }
        
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        mock_httpx_client.return_value = mock_context
        
        # Act
        is_valid, dimension = await discovery_service.verify_embedding_capability("nomic-embed-text")
        
        # Assert
        assert is_valid is True
        assert dimension == 768

    @pytest.mark.asyncio
    async def test_verify_embedding_failure(self, discovery_service, mock_httpx_client):
        """Test embedding verification failure."""
        # Arrange
        import httpx
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.post = AsyncMock(side_effect=httpx.HTTPError("error"))
        mock_httpx_client.return_value = mock_context
        
        # Act
        is_valid, dimension = await discovery_service.verify_embedding_capability("text-model")
        
        # Assert
        assert is_valid is False
        assert dimension is None


class TestTextGenerationVerification:
    """Tests for text generation capability verification."""

    @pytest.mark.asyncio
    async def test_verify_text_generation_success(self, discovery_service, mock_httpx_client):
        """Test successful text generation verification."""
        # Arrange
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "message": {"content": "Hello!"}
        }
        
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        mock_httpx_client.return_value = mock_context
        
        # Act
        is_valid = await discovery_service.verify_text_generation_capability("qwen2.5:7b")
        
        # Assert
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_verify_text_generation_failure(self, discovery_service, mock_httpx_client):
        """Test text generation verification failure."""
        # Arrange
        import httpx
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value.post = AsyncMock(side_effect=httpx.HTTPError("error"))
        mock_httpx_client.return_value = mock_context
        
        # Act
        is_valid = await discovery_service.verify_text_generation_capability("embed-model")
        
        # Assert
        assert is_valid is False


class TestDiscoverModels:
    """Tests for complete model discovery."""

    @pytest.mark.asyncio
    async def test_discover_models_success(self, discovery_service):
        """Test successful full model discovery."""
        # Arrange
        with patch.object(discovery_service, 'check_connection') as mock_conn, \
             patch.object(discovery_service, 'list_installed_models') as mock_list, \
             patch.object(discovery_service, 'get_running_models') as mock_running, \
             patch.object(discovery_service, 'get_model_details') as mock_details:
            
            mock_conn.return_value = ConnectionStatus(
                connected=True,
                server_version="0.1.25",
                base_url="http://localhost:11434",
            )
            mock_list.return_value = ["qwen2.5:7b", "nomic-embed-text"]
            mock_running.return_value = ["qwen2.5:7b"]
            mock_details.side_effect = [
                ModelDetails(name="qwen2.5", tag="7b", family="qwen2"),
                ModelDetails(name="nomic-embed-text", tag="latest", family="nomic"),
            ]
            
            # Act
            inventory = await discovery_service.discover_models()
            
            # Assert
            assert inventory.connection.connected is True
            assert len(inventory.models) == 2
            assert "qwen2.5:7b" in inventory.running_models
            assert inventory.models[0].is_loaded is True
            assert inventory.models[1].is_loaded is False

    @pytest.mark.asyncio
    async def test_discover_models_connection_failed(self, discovery_service):
        """Test discovery when connection fails."""
        # Arrange
        with patch.object(discovery_service, 'check_connection') as mock_conn:
            mock_conn.return_value = ConnectionStatus(
                connected=False,
                error="Connection refused",
                base_url="http://localhost:11434",
            )
            
            # Act
            inventory = await discovery_service.discover_models()
            
            # Assert
            assert inventory.connection.connected is False
            assert len(inventory.models) == 0
            assert len(inventory.running_models) == 0

    @pytest.mark.asyncio
    async def test_discover_models_partial_failure(self, discovery_service):
        """Test discovery continues when one model fails."""
        # Arrange
        with patch.object(discovery_service, 'check_connection') as mock_conn, \
             patch.object(discovery_service, 'list_installed_models') as mock_list, \
             patch.object(discovery_service, 'get_running_models') as mock_running, \
             patch.object(discovery_service, 'get_model_details') as mock_details:
            
            mock_conn.return_value = ConnectionStatus(connected=True)
            mock_list.return_value = ["model1", "model2", "model3"]
            mock_running.return_value = []
            
            # First model succeeds, second fails, third succeeds
            mock_details.side_effect = [
                ModelDetails(name="model1", tag="latest"),
                LLMUnavailable("Failed to get details"),
                ModelDetails(name="model3", tag="latest"),
            ]
            
            # Act
            inventory = await discovery_service.discover_models()
            
            # Assert
            assert len(inventory.models) == 2  # Only successful models
            assert inventory.models[0].name == "model1"
            assert inventory.models[1].name == "model3"
