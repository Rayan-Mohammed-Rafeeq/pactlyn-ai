"""Simplified integration tests verifying model selection persistence and configuration.

These tests focus on the database → bootstrap → provider configuration path,
without needing to mock complex async HTTP interactions.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pactlyn.storage.models import Base
from pactlyn.llm.model_config import ModelConfigurationService, ModelRole
from pactlyn.app.bootstrap import _load_active_models, build_container
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


class TestBootstrapIntegration:
    """Test that bootstrap correctly loads and applies model selections."""
    
    def test_bootstrap_loads_saved_models(self, temp_db, config_service):
        """Bootstrap should load models saved in database."""
        session_factory, session = temp_db
        settings = Settings()
        
        # Save model selections
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        config_service.set_active_model(ModelRole.EMBEDDING, "nomic-embed-text:latest")
        session.commit()
        
        # Load via bootstrap helper
        assistant_model, embedding_model = _load_active_models(session_factory, settings)
        
        assert assistant_model == "qwen2.5:7b"
        assert embedding_model == "nomic-embed-text:latest"
    
    def test_bootstrap_falls_back_to_environment(self, temp_db):
        """Bootstrap should fall back to settings when no selection exists."""
        session_factory, _ = temp_db
        settings = Settings()
        
        assistant_model, embedding_model = _load_active_models(session_factory, settings)
        
        # Should match default settings (from environment variables)
        assert assistant_model == settings.ollama_model
        assert embedding_model == settings.ollama_embedding_model
    
    def test_partial_selection_mixed_fallback(self, temp_db, config_service):
        """Bootstrap should use database for some roles, settings for others."""
        session_factory, session = temp_db
        settings = Settings()
        
        # Only set assistant model
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:3b")
        session.commit()
        
        assistant_model, embedding_model = _load_active_models(session_factory, settings)
        
        # Assistant from database, embedding from settings
        assert assistant_model == "qwen2.5:3b"
        assert embedding_model == settings.ollama_embedding_model


class TestProviderConfiguration:
    """Test that providers are configured with selected models."""
    
    def test_provider_stores_configured_models(self):
        """Provider should store models passed to constructor."""
        provider = OllamaProvider(
            base_url="http://localhost:11434",
            model="qwen2.5:7b",
            embedding_model="nomic-embed-text:latest",
            timeout=30
        )
        
        # Verify models are stored correctly
        assert provider.model == "qwen2.5:7b"
        assert provider.embedding_model == "nomic-embed-text:latest"
        assert provider.base_url == "http://localhost:11434"
    
    def test_provider_configuration_from_bootstrap(self, temp_db, config_service):
        """Provider created via bootstrap should use selected models."""
        session_factory, session = temp_db
        settings = Settings()
        
        # Save selections
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        config_service.set_active_model(ModelRole.EMBEDDING, "nomic-embed-text:latest")
        session.commit()
        
        # Load via bootstrap
        assistant_model, embedding_model = _load_active_models(session_factory, settings)
        
        # Create provider with loaded models
        provider = OllamaProvider(
            base_url=settings.ollama_url,
            model=assistant_model,
            embedding_model=embedding_model
        )
        
        # Verify provider has correct models
        assert provider.model == "qwen2.5:7b"
        assert provider.embedding_model == "nomic-embed-text:latest"


class TestModelSwitching:
    """Test that changing selections affects subsequent provider creation."""
    
    def test_model_switch_affects_new_provider(self, temp_db, config_service):
        """Changing model selection should affect next provider instance."""
        session_factory, session = temp_db
        settings = Settings()
        
        # Initial selection
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        session.commit()
        
        assistant_model1, _ = _load_active_models(session_factory, settings)
        provider1 = OllamaProvider(
            base_url="http://localhost:11434",
            model=assistant_model1,
            embedding_model="nomic-embed-text:latest"
        )
        
        assert provider1.model == "qwen2.5:7b"
        
        # Change selection
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:3b")
        session.commit()
        
        assistant_model2, _ = _load_active_models(session_factory, settings)
        provider2 = OllamaProvider(
            base_url="http://localhost:11434",
            model=assistant_model2,
            embedding_model="nomic-embed-text:latest"
        )
        
        # New provider should use new model
        assert provider2.model == "qwen2.5:3b"
    
    def test_restart_persistence(self, temp_db, config_service):
        """Model selections should persist across simulated restarts."""
        session_factory, session = temp_db
        settings = Settings()
        
        # First "session" - save model
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:3b")
        config_service.set_active_model(ModelRole.EMBEDDING, "nomic-embed-text:latest")
        session.commit()
        session.close()
        
        # Simulate restart by creating new session
        assistant_model, embedding_model = _load_active_models(session_factory, settings)
        
        # Persisted selections should be loaded
        assert assistant_model == "qwen2.5:3b"
        assert embedding_model == "nomic-embed-text:latest"


class TestDatabasePersistence:
    """Test that model selections are correctly persisted in database."""
    
    def test_selection_stored_in_database(self, temp_db, config_service):
        """Model selection should be stored in database."""
        session_factory, session = temp_db
        
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        session.commit()
        
        # Query directly from database
        selection = config_service.get_active_model(ModelRole.ASSISTANT)
        
        assert selection is not None
        assert selection.role == ModelRole.ASSISTANT
        assert selection.selected_model == "qwen2.5:7b"
        assert selection.provider == "ollama"
    
    def test_selection_update_modifies_existing(self, temp_db, config_service):
        """Updating a selection should modify existing record, not create new one."""
        session_factory, session = temp_db
        
        # Initial selection
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        session.commit()
        
        selection1 = config_service.get_active_model(ModelRole.ASSISTANT)
        id1 = selection1.id
        
        # Update selection
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:3b")
        session.commit()
        
        selection2 = config_service.get_active_model(ModelRole.ASSISTANT)
        id2 = selection2.id
        
        # Should be same record
        assert id1 == id2
        assert selection2.selected_model == "qwen2.5:3b"
    
    def test_multiple_roles_stored_separately(self, temp_db, config_service):
        """Different roles should have separate database records."""
        session_factory, session = temp_db
        
        config_service.set_active_model(ModelRole.ASSISTANT, "qwen2.5:7b")
        config_service.set_active_model(ModelRole.EMBEDDING, "nomic-embed-text:latest")
        session.commit()
        
        assistant_sel = config_service.get_active_model(ModelRole.ASSISTANT)
        embedding_sel = config_service.get_active_model(ModelRole.EMBEDDING)
        
        assert assistant_sel.selected_model == "qwen2.5:7b"
        assert embedding_sel.selected_model == "nomic-embed-text:latest"
        assert assistant_sel.id != embedding_sel.id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
