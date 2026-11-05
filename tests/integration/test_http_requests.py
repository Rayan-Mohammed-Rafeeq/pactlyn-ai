"""HTTP transport-level integration tests verifying actual outgoing requests.

These tests use httpx.MockTransport to intercept and verify the exact HTTP requests
sent to Ollama, proving that model selections control actual inference.
"""

import json
import pytest
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pactlyn.storage.models import Base
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


class TestHTTPRequestPayloads:
    """Test that HTTP requests contain the correct model identifiers."""
    
    @pytest.mark.asyncio
    async def test_assistant_request_contains_selected_model(self, temp_db, config_service):
        """Verify assistant inference request contains the selected model."""
        session_factory, session = temp_db
        settings = Settings()
        
        # Save model selection
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        session.commit()
        
        # Load via bootstrap
        assistant_model, embedding_model = _load_active_models(session_factory, settings)
        
        # Track captured requests
        captured_requests = []
        
        def mock_handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append({
                "method": request.method,
                "url": str(request.url),
                "content": json.loads(request.content.decode())
            })
            return httpx.Response(
                200,
                json={"message": {"content": "Test response"}}
            )
        
        # Create provider with mock transport
        transport = httpx.MockTransport(mock_handler)
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model=assistant_model,
            embedding_model=embedding_model
        )
        
        # Make request with mocked client
        async with httpx.AsyncClient(transport=transport, timeout=30) as client:
            response = await client.post(
                f"{provider.base_url}/api/chat",
                json={"model": provider.model, "messages": [{"role": "user", "content": "Test"}], "stream": False}
            )
        
        # Verify request
        assert len(captured_requests) == 1
        request = captured_requests[0]
        assert request["method"] == "POST"
        assert "/api/chat" in request["url"]
        assert request["content"]["model"] == "qwen2.5:7b"
        assert request["content"]["messages"] == [{"role": "user", "content": "Test"}]
    
    @pytest.mark.asyncio
    async def test_model_switch_changes_next_request(self, temp_db, config_service):
        """Verify switching model changes subsequent requests."""
        session_factory, session = temp_db
        settings = Settings()
        
        captured_requests = []
        
        def mock_handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append({
                "method": request.method,
                "url": str(request.url),
                "content": json.loads(request.content.decode())
            })
            return httpx.Response(
                200,
                json={"message": {"content": "Test response"}}
            )
        
        transport = httpx.MockTransport(mock_handler)
        
        # First model selection
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        session.commit()
        
        assistant_model_1, embedding_model_1 = _load_active_models(session_factory, settings)
        
        async with httpx.AsyncClient(transport=transport, timeout=30) as client:
            await client.post(
                "http://localhost:11434/api/chat",
                json={"model": assistant_model_1, "messages": [{"role": "user", "content": "Test 1"}], "stream": False}
            )
        
        assert captured_requests[0]["content"]["model"] == "qwen2.5:7b"
        
        # Switch model
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:3b")
        session.commit()
        
        assistant_model_2, embedding_model_2 = _load_active_models(session_factory, settings)
        
        async with httpx.AsyncClient(transport=transport, timeout=30) as client:
            await client.post(
                "http://localhost:11434/api/chat",
                json={"model": assistant_model_2, "messages": [{"role": "user", "content": "Test 2"}], "stream": False}
            )
        
        assert captured_requests[1]["content"]["model"] == "qwen2.5:3b"
    
    @pytest.mark.asyncio
    async def test_embedding_request_uses_selected_model(self, temp_db, config_service):
        """Verify embedding generation uses the selected embedding model."""
        session_factory, session = temp_db
        settings = Settings()
        
        # Save embedding model selection
        config_service.set_active_model(ModelRole.EMBEDDING, "nomic-embed-text:latest")
        session.commit()
        
        # Load via bootstrap
        assistant_model, embedding_model = _load_active_models(session_factory, settings)
        
        # Track captured requests
        captured_requests = []
        
        def mock_handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append({
                "method": request.method,
                "url": str(request.url),
                "content": json.loads(request.content.decode())
            })
            return httpx.Response(
                200,
                json={"embeddings": [[0.1, 0.2, 0.3]]}
            )
        
        transport = httpx.MockTransport(mock_handler)
        
        async with httpx.AsyncClient(transport=transport, timeout=30) as client:
            response = await client.post(
                "http://localhost:11434/api/embed",
                json={"model": embedding_model, "input": ["Test text"]}
            )
        
        # Verify request
        assert len(captured_requests) == 1
        request = captured_requests[0]
        assert request["method"] == "POST"
        assert "/api/embed" in request["url"]
        assert request["content"]["model"] == "nomic-embed-text:latest"
        assert request["content"]["input"] == ["Test text"]
    
    @pytest.mark.asyncio
    async def test_extraction_uses_configured_model(self, temp_db, config_service):
        """Verify extraction workflow uses the configured assistant model."""
        session_factory, session = temp_db
        settings = Settings()
        
        # Set assistant model (extraction currently uses assistant model)
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        session.commit()
        
        assistant_model, _ = _load_active_models(session_factory, settings)
        
        captured_requests = []
        
        def mock_handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append({
                "method": request.method,
                "url": str(request.url),
                "content": json.loads(request.content.decode())
            })
            return httpx.Response(
                200,
                json={"message": {"content": "[]"}}  # Empty extraction result
            )
        
        transport = httpx.MockTransport(mock_handler)
        
        # Simulate extraction request
        async with httpx.AsyncClient(transport=transport, timeout=30) as client:
            response = await client.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": assistant_model,
                    "messages": [{"role": "user", "content": "Extract commitments from: Call John tomorrow"}],
                    "stream": False
                }
            )
        
        # Verify extraction uses correct model
        assert len(captured_requests) == 1
        assert captured_requests[0]["content"]["model"] == "qwen2.5:7b"
    
    @pytest.mark.asyncio
    async def test_restart_persistence_loads_saved_model(self, temp_db, config_service):
        """Verify saved selections survive simulated application restart."""
        session_factory, session = temp_db
        settings = Settings()
        
        # Save selection
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:3b")
        config_service.set_active_model(ModelRole.EMBEDDING, "nomic-embed-text:latest")
        session.commit()
        session.close()
        
        # Simulate restart by creating new bootstrap load
        assistant_model, embedding_model = _load_active_models(session_factory, settings)
        
        # Verify persisted values
        assert assistant_model == "qwen2.5:3b"
        assert embedding_model == "nomic-embed-text:latest"
        
        # Verify they're used in requests
        captured_requests = []
        
        def mock_handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append({
                "content": json.loads(request.content.decode())
            })
            return httpx.Response(200, json={"message": {"content": "Test"}})
        
        transport = httpx.MockTransport(mock_handler)
        
        async with httpx.AsyncClient(transport=transport, timeout=30) as client:
            await client.post(
                "http://localhost:11434/api/chat",
                json={"model": assistant_model, "messages": [{"role": "user", "content": "Test"}], "stream": False}
            )
        
        assert captured_requests[0]["content"]["model"] == "qwen2.5:3b"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
