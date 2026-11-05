"""Live verification tests using actual Ollama installation.

These tests require Ollama to be running with models installed.
Run with: pytest tests/live/test_ollama_live.py -v -s
"""

import asyncio
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pactlyn.storage.models import Base
from pactlyn.llm.discovery import OllamaDiscoveryService
from pactlyn.llm.model_config import ModelConfigurationService, ModelRole
from pactlyn.app.bootstrap import _load_active_models, build_container
from pactlyn.app.configuration import Settings


@pytest.fixture(scope="module")
def ollama_url():
    """Get Ollama URL from settings."""
    settings = Settings()
    return settings.ollama_url


@pytest.fixture(scope="module")
def temp_db(tmp_path_factory):
    """Create a temporary database for testing."""
    db_path = tmp_path_factory.mktemp("data") / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal, SessionLocal()


@pytest.mark.live
class TestLiveOllamaDiscovery:
    """Test discovery against real Ollama installation."""
    
    @pytest.mark.asyncio
    async def test_ollama_connection(self, ollama_url):
        """Verify Ollama is accessible."""
        discovery = OllamaDiscoveryService(ollama_url)
        is_connected = await discovery.check_connection()
        
        assert is_connected, f"Ollama not accessible at {ollama_url}. Is it running?"
        print(f"\n[OK] Connected to Ollama at {ollama_url}")
    
    @pytest.mark.asyncio
    async def test_list_installed_models(self, ollama_url):
        """List all installed models."""
        discovery = OllamaDiscoveryService(ollama_url)
        models = await discovery.list_installed_models()
        
        assert len(models) > 0, "No models installed in Ollama"
        
        print(f"\n[OK] Found {len(models)} installed models:")
        for model in models:
            print(f"  - {model}")
    
    @pytest.mark.asyncio
    async def test_discover_models_with_metadata(self, ollama_url):
        """Discover models and retrieve their metadata."""
        discovery = OllamaDiscoveryService(ollama_url)
        inventory = await discovery.discover_models()
        
        assert len(inventory.models) > 0, "No models discovered"
        
        print(f"\n[OK] Discovered {len(inventory.models)} models with metadata:")
        for model_detail in inventory.models:
            # Classify capabilities
            caps = await discovery.classify_capabilities(model_detail)
            model_name = f"{model_detail.name}:{model_detail.tag}"
            print(f"\n  {model_name}:")
            print(f"    Family: {model_detail.family or 'Unknown'}")
            print(f"    Parameters: {model_detail.parameter_size or 'Unknown'}")
            print(f"    Quantization: {model_detail.quantization or 'Unknown'}")
            print(f"    Context: {model_detail.context_length or 'Unknown'}")
            print(f"    Text Generation: {caps.text_generation}")
            print(f"    Embeddings: {caps.embedding}")
            print(f"    Vision: {caps.vision_language}")
            if caps.embedding_dimension:
                print(f"    Embedding Dimension: {caps.embedding_dimension}")


@pytest.mark.live
class TestLiveModelSelection:
    """Test model selection persistence with real models."""
    
    @pytest.mark.asyncio
    async def test_select_and_persist_qwen_model(self, temp_db, ollama_url):
        """Select qwen2.5:7b and verify persistence."""
        session_factory, session = temp_db
        settings = Settings()
        
        # Verify model exists
        discovery = OllamaDiscoveryService(ollama_url)
        models = await discovery.list_installed_models()
        
        if "qwen2.5:7b" not in models:
            pytest.skip("qwen2.5:7b not installed")
        
        # Save selection
        config_service = ModelConfigurationService(session)
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        session.commit()
        
        # Verify it loads back
        assistant_model, _ = _load_active_models(session_factory, settings)
        
        assert assistant_model == "qwen2.5:7b"
        print(f"\n[OK] Selected and persisted qwen2.5:7b as assistant model")
    
    @pytest.mark.asyncio
    async def test_select_nomic_embedding_model(self, temp_db, ollama_url):
        """Select nomic-embed-text and verify persistence."""
        session_factory, session = temp_db
        settings = Settings()
        
        # Verify model exists
        discovery = OllamaDiscoveryService(ollama_url)
        models = await discovery.list_installed_models()
        
        if "nomic-embed-text:latest" not in models and "nomic-embed-text" not in models:
            pytest.skip("nomic-embed-text not installed")
        
        embedding_model = "nomic-embed-text:latest" if "nomic-embed-text:latest" in models else "nomic-embed-text"
        
        # Save selection
        config_service = ModelConfigurationService(session)
        config_service.set_active_model(ModelRole.EMBEDDING, embedding_model)
        session.commit()
        
        # Verify it loads back
        _, loaded_embedding = _load_active_models(session_factory, settings)
        
        assert loaded_embedding == embedding_model
        print(f"\n✓ Selected and persisted {embedding_model} as embedding model")


@pytest.mark.live
class TestLiveModelInference:
    """Test actual inference with selected models."""
    
    @pytest.mark.asyncio
    async def test_text_generation_with_qwen(self, ollama_url):
        """Test text generation with qwen2.5 model."""
        discovery = OllamaDiscoveryService(ollama_url)
        models = await discovery.list_models()
        
        # Try different variants
        test_model = None
        for variant in ["qwen2.5:7b", "qwen2.5:3b", "qwen2.5"]:
            if variant in models:
                test_model = variant
                break
        
        if not test_model:
            pytest.skip("No qwen2.5 model installed")
        
        is_valid = await discovery.verify_text_generation_capability(test_model)
        
        assert is_valid, f"{test_model} failed text generation test"
        print(f"\n✓ {test_model} successfully generated text")
    
    @pytest.mark.asyncio
    async def test_embedding_generation_with_nomic(self, ollama_url):
        """Test embedding generation with nomic-embed-text."""
        discovery = OllamaDiscoveryService(ollama_url)
        models = await discovery.list_models()
        
        test_model = None
        for variant in ["nomic-embed-text:latest", "nomic-embed-text"]:
            if variant in models:
                test_model = variant
                break
        
        if not test_model:
            pytest.skip("nomic-embed-text not installed")
        
        is_valid, dimension = await discovery.verify_embedding_capability(test_model)
        
        assert is_valid, f"{test_model} failed embedding test"
        assert dimension > 0, "Invalid embedding dimension"
        print(f"\n✓ {test_model} generated {dimension}-dimensional embeddings")


@pytest.mark.live
class TestLiveModelSwitching:
    """Test switching between different models."""
    
    @pytest.mark.asyncio
    async def test_switch_between_qwen_models(self, temp_db, ollama_url):
        """Test switching between qwen2.5:7b and qwen2.5:3b."""
        session_factory, session = temp_db
        settings = Settings()
        
        discovery = OllamaDiscoveryService(ollama_url)
        models = await discovery.list_models()
        
        if "qwen2.5:7b" not in models or "qwen2.5:3b" not in models:
            pytest.skip("Both qwen2.5:7b and qwen2.5:3b required")
        
        config_service = ModelConfigurationService(session)
        
        # Select first model
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        session.commit()
        
        assistant_model_1, _ = _load_active_models(session_factory, settings)
        assert assistant_model_1 == "qwen2.5:7b"
        print(f"\n✓ Switched to qwen2.5:7b")
        
        # Switch to second model
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:3b")
        session.commit()
        
        assistant_model_2, _ = _load_active_models(session_factory, settings)
        assert assistant_model_2 == "qwen2.5:3b"
        print(f"✓ Switched to qwen2.5:3b")
        
        print("✓ Model switching works correctly")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "-m", "live"])
