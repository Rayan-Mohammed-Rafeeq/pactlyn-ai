"""Ollama model discovery and capability classification.

Portions inspired by local-ai-workspace (https://github.com/Jn527fd/local-ai-workspace)
Copyright 2026 Local AI Coding Assistant contributors
Licensed under the MIT License
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx

from pactlyn.llm.interfaces import LLMUnavailable


class ModelCapability(StrEnum):
    """Model capability categories."""

    TEXT_GENERATION = "text_generation"
    VISION_LANGUAGE = "vision_language"
    EMBEDDING = "embedding"
    UNKNOWN = "unknown"


class CapabilityState(StrEnum):
    """Confidence level for a model's capability."""

    SUPPORTED = "supported"  # Explicitly verified or confirmed by API
    LIKELY = "likely"  # Metadata suggests support, not verified
    UNSUPPORTED = "unsupported"  # Evidence indicates incompatibility
    UNKNOWN = "unknown"  # Insufficient information


@dataclass
class ModelDetails:
    """Normalized model metadata from Ollama API."""

    name: str
    tag: str
    digest: str | None = None
    family: str | None = None
    families: list[str] | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    format: str | None = None
    size_bytes: int | None = None
    modified_at: datetime | None = None
    context_length: int | None = None
    embedding_dimension: int | None = None
    capabilities: dict[str, Any] | None = None
    model_info: dict[str, Any] | None = None
    is_loaded: bool = False
    vram_bytes: int | None = None


@dataclass
class ModelCapabilities:
    """Classified capabilities for a model."""

    model_name: str
    text_generation: CapabilityState = CapabilityState.UNKNOWN
    vision_language: CapabilityState = CapabilityState.UNKNOWN
    embedding: CapabilityState = CapabilityState.UNKNOWN
    embedding_dimension: int | None = None
    # Metadata for UI display
    model_type: str | None = None  # Text, Vision, Embedding
    parameter_count: str | None = None
    quantization: str | None = None
    context_length: int | None = None


@dataclass
class ConnectionStatus:
    """Ollama server connection state."""

    connected: bool
    server_version: str | None = None
    base_url: str = ""
    error: str | None = None
    last_checked: datetime | None = None


@dataclass
class ModelInventory:
    """Complete discovered model inventory."""

    models: list[ModelDetails]
    running_models: list[str]
    connection: ConnectionStatus
    discovered_at: datetime


class OllamaDiscoveryService:
    """Discover and categorize locally installed Ollama models."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def check_connection(self) -> ConnectionStatus:
        """Check if Ollama server is accessible."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/version")
                if response.is_success:
                    version = response.json().get("version")
                    return ConnectionStatus(
                        connected=True,
                        server_version=str(version) if version else None,
                        base_url=self.base_url,
                        last_checked=datetime.now(UTC),
                    )
                return ConnectionStatus(
                    connected=False,
                    base_url=self.base_url,
                    error=f"HTTP {response.status_code}",
                    last_checked=datetime.now(UTC),
                )
        except httpx.ConnectError:
            return ConnectionStatus(
                connected=False,
                base_url=self.base_url,
                error="Connection refused - Ollama may not be running",
                last_checked=datetime.utcnow(),
            )
        except httpx.TimeoutException:
            return ConnectionStatus(
                connected=False,
                base_url=self.base_url,
                error="Connection timeout",
                last_checked=datetime.utcnow(),
            )
        except Exception as exc:
            return ConnectionStatus(
                connected=False,
                base_url=self.base_url,
                error=str(exc),
                last_checked=datetime.utcnow(),
            )

    async def list_installed_models(self) -> list[str]:
        """List model names from /api/tags."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            models = response.json().get("models", [])
            return [str(model["name"]) for model in models if isinstance(model, dict) and "name" in model]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise LLMUnavailable(f"Failed to list models: {exc}") from exc

    async def get_running_models(self) -> list[str]:
        """Get currently loaded models from /api/ps."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/api/ps")
                response.raise_for_status()
            models = response.json().get("models", [])
            return [str(model["name"]) for model in models if isinstance(model, dict) and "name" in model]
        except (httpx.HTTPError, ValueError, KeyError):
            # /api/ps may not exist in older Ollama versions
            return []

    async def get_model_details(self, model_name: str) -> ModelDetails:
        """Retrieve detailed metadata for a specific model."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/show",
                    json={"name": model_name},
                )
                response.raise_for_status()
            data = response.json()
            
            # Parse model name and tag
            name_parts = model_name.split(":", 1)
            name = name_parts[0]
            tag = name_parts[1] if len(name_parts) > 1 else "latest"
            
            # Extract metadata safely
            details = data.get("details", {}) or {}
            model_info = data.get("model_info", {}) or {}
            
            # Parse parameter size and quantization from format strings
            parameter_size = details.get("parameter_size")
            quantization = details.get("quantization_level")
            
            # Try to extract from format if not explicitly provided
            format_str = details.get("format", "")
            if not parameter_size and format_str:
                # Try to extract like "7B" from format string
                import re
                size_match = re.search(r'(\d+\.?\d*[BMK])', format_str, re.IGNORECASE)
                if size_match:
                    parameter_size = size_match.group(1).upper()
            
            # Parse modified timestamp
            modified_at = None
            if "modified_at" in data:
                try:
                    modified_at = datetime.fromisoformat(data["modified_at"].replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass
            
            # Extract context length from model_info
            context_length = model_info.get("context_length") or model_info.get("num_ctx")
            
            return ModelDetails(
                name=name,
                tag=tag,
                digest=data.get("digest"),
                family=details.get("family"),
                families=details.get("families"),
                parameter_size=parameter_size,
                quantization=quantization,
                format=details.get("format"),
                size_bytes=data.get("size"),
                modified_at=modified_at,
                context_length=context_length,
                embedding_dimension=None,  # Determined by capability check
                capabilities=data.get("capabilities"),
                model_info=model_info,
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise LLMUnavailable(f"Failed to get model details for {model_name}: {exc}") from exc

    async def classify_capabilities(self, model: ModelDetails) -> ModelCapabilities:
        """Classify model capabilities using available metadata."""
        caps = ModelCapabilities(
            model_name=f"{model.name}:{model.tag}",
            model_type=None,
            parameter_count=model.parameter_size,
            quantization=model.quantization,
            context_length=model.context_length
        )
        
        # Check explicit capabilities first
        if model.capabilities:
            # Some newer Ollama versions expose capabilities directly
            # Handle both dict and list formats
            if isinstance(model.capabilities, dict):
                if "vision" in model.capabilities or model.capabilities.get("vision") is True:
                    caps.vision_language = CapabilityState.SUPPORTED
                if "embedding" in model.capabilities or model.capabilities.get("embedding") is True:
                    caps.embedding = CapabilityState.SUPPORTED
            elif isinstance(model.capabilities, list):
                if "vision" in model.capabilities:
                    caps.vision_language = CapabilityState.SUPPORTED
                if "embedding" in model.capabilities:
                    caps.embedding = CapabilityState.SUPPORTED
        
        # Family-based heuristics (conservative)
        families = model.families or ([model.family] if model.family else [])
        family_lower = " ".join(str(f).lower() for f in families)
        
        # Vision models
        if any(indicator in family_lower for indicator in ["llava", "bakllava", "vision", "vl", "clip"]):
            if caps.vision_language == CapabilityState.UNKNOWN:
                caps.vision_language = CapabilityState.LIKELY
        
        # Embedding models
        if any(indicator in family_lower for indicator in ["embed", "nomic", "bge", "sentence"]):
            if caps.embedding == CapabilityState.UNKNOWN:
                caps.embedding = CapabilityState.LIKELY
        
        # Name-based detection (very conservative)
        name_lower = model.name.lower()
        if caps.vision_language == CapabilityState.UNKNOWN:
            if any(indicator in name_lower for indicator in ["llava", "vision", "-vl"]):
                caps.vision_language = CapabilityState.LIKELY
        
        if caps.embedding == CapabilityState.UNKNOWN:
            if "embed" in name_lower or "nomic" in name_lower:
                caps.embedding = CapabilityState.LIKELY
        
        # Text generation is default for non-embedding models
        if caps.embedding != CapabilityState.SUPPORTED and caps.embedding != CapabilityState.LIKELY:
            # If not explicitly an embedding model, assume text generation capability
            if caps.text_generation == CapabilityState.UNKNOWN:
                caps.text_generation = CapabilityState.LIKELY
            # Mark embedding as unsupported for non-embedding models
            if caps.embedding == CapabilityState.UNKNOWN:
                caps.embedding = CapabilityState.UNSUPPORTED
        else:
            # If embedding is likely, text generation is usually not primary
            if caps.text_generation == CapabilityState.UNKNOWN:
                caps.text_generation = CapabilityState.UNSUPPORTED
            caps.embedding = CapabilityState.LIKELY  # Promote to at least LIKELY
        
        return caps

    async def verify_embedding_capability(self, model_name: str) -> tuple[bool, int | None]:
        """Test if a model can produce embeddings and get dimension."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": model_name, "input": ["test"]},
                )
                response.raise_for_status()
            
            body = response.json()
            embeddings = body.get("embeddings") or [body.get("embedding")]
            
            if embeddings and isinstance(embeddings, list) and embeddings[0]:
                dimension = len(embeddings[0])
                return True, dimension
            return False, None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return False, None

    async def verify_text_generation_capability(self, model_name: str) -> bool:
        """Test if a model can generate text responses."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": "Hi"}],
                        "stream": False,
                    },
                )
                response.raise_for_status()
            
            body = response.json()
            content = body.get("message", {}).get("content")
            return bool(content)
        except (httpx.HTTPError, ValueError, KeyError):
            return False

    async def discover_models(self) -> ModelInventory:
        """Discover all installed models with full metadata and capabilities."""
        connection = await self.check_connection()
        
        if not connection.connected:
            return ModelInventory(
                models=[],
                running_models=[],
                connection=connection,
                discovered_at=datetime.now(UTC),
            )
        
        try:
            # Get installed and running models
            installed_names = await self.list_installed_models()
            running_names = await self.get_running_models()
            
            # Fetch details for each model, but don't fail the entire discovery if one fails
            models: list[ModelDetails] = []
            for model_name in installed_names:
                try:
                    details = await self.get_model_details(model_name)
                    details.is_loaded = model_name in running_names
                    
                    # Try to get running model VRAM info
                    if details.is_loaded:
                        try:
                            async with httpx.AsyncClient(timeout=5.0) as client:
                                response = await client.get(f"{self.base_url}/api/ps")
                                if response.is_success:
                                    ps_models = response.json().get("models", [])
                                    for ps_model in ps_models:
                                        if ps_model.get("name") == model_name:
                                            details.vram_bytes = ps_model.get("size_vram")
                                            break
                        except Exception:
                            pass  # VRAM info is optional
                    
                    models.append(details)
                except Exception:
                    # Log but don't fail - one bad model shouldn't block discovery
                    continue
            
            return ModelInventory(
                models=models,
                running_models=running_names,
                connection=connection,
                discovered_at=datetime.now(UTC),
            )
        except Exception as exc:
            connection.error = str(exc)
            connection.connected = False
            return ModelInventory(
                models=[],
                running_models=[],
                connection=connection,
                discovered_at=datetime.now(UTC),
            )

    async def refresh_inventory(self) -> ModelInventory:
        """Alias for discover_models for API consistency."""
        return await self.discover_models()
