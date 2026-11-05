"""Model configuration and selection management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from pactlyn.llm.discovery import CapabilityState, ModelCapabilities, OllamaDiscoveryService
from pactlyn.storage.models import ActiveModelSelection, ModelConfiguration


class ModelRole:
    """Standard model role identifiers."""

    ASSISTANT = "assistant"
    EXTRACTION = "extraction"  # If using separate model for commitment extraction
    VISION = "vision"
    EMBEDDING = "embedding"


@dataclass
class ModelSelectionConfig:
    """Current active model selections."""

    assistant_model: str | None = None
    extraction_model: str | None = None
    vision_model: str | None = None
    embedding_model: str | None = None


class ModelConfigurationService:
    """Manage model selection and persistence."""

    def __init__(self, session: Session):
        self.session = session

    def get_active_model(self, role: str) -> ActiveModelSelection | None:
        """Get the currently selected model for a role."""
        stmt = select(ActiveModelSelection).where(ActiveModelSelection.role == role)
        return self.session.scalar(stmt)

    def set_active_model(
        self,
        role: str,
        model_name: str,
        provider: str = "ollama",
        validated: bool = False,
        validation_error: str | None = None,
    ) -> ActiveModelSelection:
        """Set or update the active model for a role."""
        existing = self.get_active_model(role)
        
        if existing:
            existing.provider = provider
            existing.selected_model = model_name
            existing.validated = validated
            existing.validation_error = validation_error
            existing.updated_at = datetime.utcnow()
            self.session.flush()
            return existing
        
        selection = ActiveModelSelection(
            role=role,
            provider=provider,
            selected_model=model_name,
            validated=validated,
            validation_error=validation_error,
        )
        self.session.add(selection)
        self.session.flush()
        return selection

    def get_all_active_models(self) -> ModelSelectionConfig:
        """Get all active model selections."""
        stmt = select(ActiveModelSelection)
        selections = self.session.scalars(stmt).all()
        
        config = ModelSelectionConfig()
        for selection in selections:
            if selection.role == ModelRole.ASSISTANT:
                config.assistant_model = selection.selected_model
            elif selection.role == ModelRole.EXTRACTION:
                config.extraction_model = selection.selected_model
            elif selection.role == ModelRole.VISION:
                config.vision_model = selection.selected_model
            elif selection.role == ModelRole.EMBEDDING:
                config.embedding_model = selection.selected_model
        
        return config

    def clear_active_model(self, role: str) -> None:
        """Remove the active model selection for a role."""
        existing = self.get_active_model(role)
        if existing:
            self.session.delete(existing)
            self.session.flush()

    def record_model_metadata(
        self,
        model_name: str,
        provider: str,
        model_type: str | None = None,
        context_length: int | None = None,
        parameter_count: str | None = None,
        quantization: str | None = None,
        embedding_dimension: int | None = None,
    ) -> ModelConfiguration:
        """Record or update model metadata."""
        # Check if already exists
        stmt = select(ModelConfiguration).where(
            ModelConfiguration.provider == provider,
            ModelConfiguration.model_name == model_name,
        )
        existing = self.session.scalar(stmt)
        
        if existing:
            if model_type is not None:
                existing.model_type = model_type
            if context_length is not None:
                existing.context_length = context_length
            if parameter_count is not None:
                existing.parameter_count = parameter_count
            if quantization is not None:
                existing.quantization = quantization
            if embedding_dimension is not None:
                existing.embedding_dimension = embedding_dimension
            existing.updated_at = datetime.utcnow()
            self.session.flush()
            return existing
        
        config = ModelConfiguration(
            provider=provider,
            model_name=model_name,
            model_type=model_type,
            context_length=context_length,
            parameter_count=parameter_count,
            quantization=quantization,
            embedding_dimension=embedding_dimension,
            enabled=True,
        )
        self.session.add(config)
        self.session.flush()
        return config

    async def validate_embedding_model(
        self,
        model_name: str,
        discovery: OllamaDiscoveryService,
    ) -> tuple[bool, int | None, str | None]:
        """Validate an embedding model and get its dimension."""
        is_valid, dimension = await discovery.verify_embedding_capability(model_name)
        
        if is_valid:
            return True, dimension, None
        return False, None, "Model does not support embedding generation"

    async def validate_text_model(
        self,
        model_name: str,
        discovery: OllamaDiscoveryService,
    ) -> tuple[bool, str | None]:
        """Validate a text generation model."""
        is_valid = await discovery.verify_text_generation_capability(model_name)
        
        if is_valid:
            return True, None
        return False, "Model does not respond to text generation requests"

    def is_embedding_dimension_compatible(
        self,
        new_dimension: int,
        existing_collections: list[str],
    ) -> tuple[bool, str | None]:
        """Check if a new embedding dimension is compatible with existing collections."""
        # Check stored configurations for these collections
        stmt = select(ModelConfiguration).where(
            ModelConfiguration.model_type == "embedding",
            ModelConfiguration.embedding_dimension.isnot(None),
        )
        existing_configs = self.session.scalars(stmt).all()
        
        if not existing_configs:
            return True, None
        
        # Check if any existing embedding config has a different dimension
        for config in existing_configs:
            if config.embedding_dimension and config.embedding_dimension != new_dimension:
                return False, (
                    f"Incompatible embedding dimension: existing={config.embedding_dimension}, "
                    f"new={new_dimension}. Reindexing required."
                )
        
        return True, None


def is_model_compatible_for_role(
    capabilities: ModelCapabilities,
    role: str,
) -> tuple[bool, str | None]:
    """Check if a model is compatible with a role based on its capabilities."""
    if role == ModelRole.ASSISTANT or role == ModelRole.EXTRACTION:
        if capabilities.text_generation in (CapabilityState.SUPPORTED, CapabilityState.LIKELY):
            return True, None
        return False, "Model does not support text generation"
    
    elif role == ModelRole.VISION:
        if capabilities.vision_language in (CapabilityState.SUPPORTED, CapabilityState.LIKELY):
            return True, None
        return False, "Model does not support vision input"
    
    elif role == ModelRole.EMBEDDING:
        if capabilities.embedding in (CapabilityState.SUPPORTED, CapabilityState.LIKELY):
            return True, None
        return False, "Model does not support embeddings"
    
    return False, "Unknown role"
