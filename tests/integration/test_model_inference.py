"""Integration tests verifying persisted model selections control actual Ollama requests.

These tests verify the complete execution path from database → bootstrap → provider → HTTP.
Uses mocked HTTP to capture outgoing requests without requiring a live Ollama server.
"""

import json
from unittest.mock import AsyncMock, Mock, patch
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pactlyn.storage.models import Base, ActiveModelSelection
from pactlyn.llm.model_config import ModelConfigurationService, ModelRole
from pactlyn.app.bootstrap import _load_active_models
from pactlyn.llm.providers.ollama import OllamaProvider
from pactlyn.app.configuration import Settings


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal, SessionLocal()


@pytest.fixture
def config_service(temp_db):
    """Create a ModelConfigurationService instance."""
    _, session = temp_db
    return ModelConfigurationService(session)


class TestBootstrapModelLoading:
    """Test bootstrap correctly loads models from database."""
    
    def test_loads_saved_models(self, temp_db, config_service):
        """Bootstrap should load models saved in database."""
        session_factory, session = temp_db
        settings = Settings()
        
        # Save model selections
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        config_service.set_active_model(ModelRole.EMBEDDING, "nomic-embed-text:latest")
        session.commit()  # Commit the transaction
        
        # Load via bootstrap helper
        assistant_model, embedding_model = _load_active_models(session_factory, settings)
        
        assert assistant_model == "qwen2.5:7b"
        assert embedding_model == "nomic-embed-text:latest"
    
    def test_falls_back_to_settings_when_empty(self, temp_db):
        """Bootstrap should fall back to settings when no selection exists."""
        session_factory, _ = temp_db
        settings = Settings()
        
        assistant_model, embedding_model = _load_active_models(session_factory, settings)
        
        # Should match default settings
        assert assistant_model == settings.ollama_model
        assert embedding_model == settings.ollama_embedding_model
    
    def test_partial_selection_uses_settings_fallback(self, temp_db, config_service):
        """Bootstrap should fall back per-role when only some models are selected."""
        session_factory, session = temp_db
        settings = Settings()
        
        # Only set assistant model
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:3b")
        session.commit()  # Commit the transaction
        
        assistant_model, embedding_model = _load_active_models(session_factory, settings)
        
        assert assistant_model == "qwen2.5:3b"
        # Embedding should fall back to settings
        assert embedding_model == settings.ollama_embedding_model


class TestProviderUsesSelectedModels:
    """Test OllamaProvider uses models passed to constructor."""
    
    def test_provider_stores_selected_models(self):
        """Provider should store models passed to constructor."""
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="qwen2.5:7b",
            embedding_model="nomic-embed-text:latest",
            timeout=30
        )
        
        assert provider.model == "qwen2.5:7b"
        assert provider.embedding_model == "nomic-embed-text:latest"
    
    @pytest.mark.asyncio
    async def test_chat_uses_configured_model(self):
        """Chat completion should use the configured assistant model."""
        # Create provider with specific model
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="qwen2.5:7b",
            embedding_model="nomic-embed-text:latest",
            timeout=30
        )
        
        # Mock the HTTP client
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.is_success = True
            mock_response.status_code = 200
            mock_response.json = AsyncMock(return_value={
                "message": {"content": "Test response"}
            })
            mock_response.raise_for_status = Mock()
            
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post
            
            # Make completion request
            await provider.complete([{"role": "user", "content": "Test"}])
            
            # Verify HTTP request used correct model
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            request_json = call_args.kwargs['json']
            
            assert request_json["model"] == "qwen2.5:7b"
    
    @pytest.mark.asyncio
    async def test_embed_uses_configured_model(self):
        """Embedding should use the configured embedding model."""
        # Create provider with specific embedding model
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="qwen2.5:7b",
            embedding_model="nomic-embed-text:latest",
            timeout=30
        )
        
        # Mock the HTTP client
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.is_success = True
            mock_response.status_code = 200
            mock_response.json = AsyncMock(return_value={
                "embeddings": [[0.1, 0.2, 0.3]]
            })
            mock_response.raise_for_status = Mock()
            
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post
            
            # Make embedding request
            await provider.embed(["Test text"])
            
            # Verify HTTP request used correct model
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            request_json = call_args.kwargs['json']
            
            assert request_json["model"] == "nomic-embed-text:latest"


class TestModelSwitching:
    """Test model switching changes subsequent requests."""
    
    @pytest.mark.asyncio
    async def test_changing_selection_affects_next_request(self, temp_db, config_service):
        """Changing model selection should affect next inference request."""
        session_factory, session = temp_db
        settings = Settings()
        
        # Initial selection
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        session.commit()
        assistant_model, _ = _load_active_models(session_factory, settings)
        
        provider1 = OllamaProvider(
            base_url="http://localhost:11434",
            model=assistant_model,
            embedding_model="nomic-embed-text:latest",
            timeout=30
        )
        
        # Mock first request
        with patch('httpx.AsyncClient') as mock_client1:
            mock_response1 = AsyncMock()
            mock_response1.json = AsyncMock(return_value={"message": {"content": "Test"}})
            mock_response1.raise_for_status = Mock()
            mock_post1 = AsyncMock(return_value=mock_response1)
            mock_client1.return_value.__aenter__.return_value.post = mock_post1
            
            await provider1.complete([{"role": "user", "content": "Test"}])
            
            # Verify first request
            call_args1 = mock_post1.call_args
            assert call_args1.kwargs['json']["model"] == "qwen2.5:7b"
        
        # Change selection
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:3b")
        session.commit()
        assistant_model, _ = _load_active_models(session_factory, settings)
        
        provider2 = OllamaProvider(
            base_url="http://localhost:11434",
            model=assistant_model,
            embedding_model="nomic-embed-text:latest",
            timeout=30
        )
        
        # Mock second request
        with patch('httpx.AsyncClient') as mock_client2:
            mock_response2 = AsyncMock()
            mock_response2.json = AsyncMock(return_value={"message": {"content": "Test"}})
            mock_response2.raise_for_status = Mock()
            mock_post2 = AsyncMock(return_value=mock_response2)
            mock_client2.return_value.__aenter__.return_value.post = mock_post2
            
            await provider2.complete([{"role": "user", "content": "Test"}])
            
            # Verify second request uses new model
            call_args2 = mock_post2.call_args
            assert call_args2.kwargs['json']["model"] == "qwen2.5:3b"


class TestEndToEndIntegration:
    """End-to-end integration tests simulating full application flow."""
    
    @pytest.mark.asyncio
    async def test_complete_flow_assistant_inference(self, temp_db, config_service):
        """Complete flow: Save model → Bootstrap → Provider → HTTP request."""
        session_factory, session = temp_db
        settings = Settings()
        
        # 1. User saves model selection via UI (simulated)
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        session.commit()
        
        # 2. Application bootstrap loads selections
        assistant_model, embedding_model = _load_active_models(session_factory, settings)
        
        # 3. Provider created with loaded models
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model=assistant_model,
            embedding_model=embedding_model,
            timeout=30
        )
        
        # Mock HTTP client
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={"message": {"content": "Test"}})
            mock_response.raise_for_status = Mock()
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post
            
            # 4. User makes inference request
            await provider.complete([{"role": "user", "content": "What should I do today?"}])
            
            # 5. Verify HTTP request contains selected model
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            request_json = call_args.kwargs['json']
            
            assert request_json["model"] == "qwen2.5:7b"
            assert any("What should I do today?" in str(msg) for msg in request_json["messages"])
    
    @pytest.mark.asyncio
    async def test_complete_flow_embedding_generation(self, temp_db, config_service):
        """Complete flow: Save embedding model → Bootstrap → Provider → HTTP request."""
        session_factory, session = temp_db
        settings = Settings()
        
        # 1. User saves embedding model selection
        config_service.set_active_model(ModelRole.EMBEDDING, "nomic-embed-text:latest")
        session.commit()
        
        # 2. Application bootstrap loads selections
        assistant_model, embedding_model = _load_active_models(session_factory, settings)
        
        # 3. Provider created with loaded models
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model=assistant_model,
            embedding_model=embedding_model,
            timeout=30
        )
        
        # Mock HTTP client
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={"embeddings": [[0.1, 0.2, 0.3]]})
            mock_response.raise_for_status = Mock()
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post
            
            # 4. Memory service generates embeddings (simulated)
            await provider.embed(["Remember to call mom tomorrow"])
            
            # 5. Verify HTTP request contains selected embedding model
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            request_json = call_args.kwargs['json']
            
            assert request_json["model"] == "nomic-embed-text:latest"
            assert "Remember to call mom tomorrow" in request_json["input"]
    
    @pytest.mark.asyncio
    async def test_restart_persistence(self, temp_db, config_service):
        """Model selections should persist across simulated application restarts."""
        session_factory, session = temp_db
        settings = Settings()
        
        # First "session" - save model
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:3b")
        session.commit()
        
        # Simulate restart by creating new service and provider
        assistant_model, embedding_model = _load_active_models(session_factory, settings)
        
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model=assistant_model,
            embedding_model=embedding_model,
            timeout=30
        )
        
        # Mock HTTP client
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={"message": {"content": "Test"}})
            mock_response.raise_for_status = Mock()
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post
            
            await provider.complete([{"role": "user", "content": "Test"}])
            
            # Verify persisted model is used
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            request_json = call_args.kwargs['json']
            
            assert request_json["model"] == "qwen2.5:3b"


class TestExtractionUsesAssistantModel:
    """Test commitment extraction uses the assistant model (no separate extraction role)."""
    
    @pytest.mark.asyncio
    async def test_extraction_uses_assistant_model(self, temp_db, config_service):
        """Extraction should use assistant model since no separate extraction role exists."""
        session_factory, session = temp_db
        settings = Settings()
        
        # Set assistant model
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        session.commit()
        
        # Bootstrap loads model
        assistant_model, _ = _load_active_models(session_factory, settings)
        
        # Provider uses assistant model for extraction
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model=assistant_model,
            embedding_model="nomic-embed-text:latest",
            timeout=30
        )
        
        # Mock HTTP client
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={"message": {"content": "[]"}})
            mock_response.raise_for_status = Mock()
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post
            
            # Simulate extraction request
            await provider.complete([{
                "role": "user",
                "content": "Extract commitments from: I'll call John tomorrow."
            }])
            
            # Verify extraction uses assistant model
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            request_json = call_args.kwargs['json']
            
            assert request_json["model"] == "qwen2.5:7b"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
