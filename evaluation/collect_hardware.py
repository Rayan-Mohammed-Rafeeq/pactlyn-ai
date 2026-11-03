"""Collect model metadata and Ollama's runtime memory counters for local models."""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from pactlyn.app.configuration import Settings
from pactlyn.llm.providers.ollama import OllamaProvider


async def _probe(model: str, settings: Settings) -> dict[str, object]:
    provider = OllamaProvider(settings.ollama_url, model, settings.ollama_embedding_model)
    details = await provider.model_details(model)
    await provider.complete(
        [{"role": "user", "content": "Return the JSON object {\"ok\":true}."}],
        json_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
    )
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{settings.ollama_url.rstrip('/')}/api/ps")
        response.raise_for_status()
        running = response.json().get("models", [])
    runtime: dict[str, Any] = next((item for item in running if str(item.get("name", "")).startswith(model)), {})
    return {
        "model": model,
        "model_details": {
            key: details.get(key)
            for key in ("size", "details", "parameter_size", "quantization_level", "context_length")
            if key in details
        },
        "runtime": {
            key: runtime.get(key)
            for key in ("name", "size", "size_vram", "context_length", "expires_at")
            if key in runtime
        },
    }


async def run() -> dict[str, object]:
    settings = Settings()
    result: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "ollama_url": settings.ollama_url,
        "models": [],
        "system_ram_kb": {},
        "gpu": None,
    }
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith(("MemTotal:", "MemAvailable:")):
            key, value = line.split(":", 1)
        result["system_ram_kb"][key] = int(value.strip().split()[0])
    try:
        result["gpu"] = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        result["gpu"] = "unavailable in evaluation environment"
    if not await OllamaProvider(settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model).available():
        result["status"] = "ollama_unavailable"
        return result
    models = await OllamaProvider(settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model).list_models()
    for model in ("qwen2.5:7b", "qwen2.5:3b"):
        if model in models:
            cast_models = result["models"]
            if isinstance(cast_models, list):
                cast_models.append(await _probe(model, settings))
    result["status"] = "complete"
    destination = Path("evaluation/reports/hardware-models.json")
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), indent=2))
