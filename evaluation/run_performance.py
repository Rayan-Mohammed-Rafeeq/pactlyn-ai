from __future__ import annotations

import asyncio
import json
import resource
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from pactlyn.app.configuration import Settings
from pactlyn.llm.gateway import LLMGateway
from pactlyn.llm.providers.ollama import OllamaProvider


async def run() -> dict[str, object]:
    settings = Settings()
    provider = OllamaProvider(
        settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model
    )
    report: dict[str, object] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "configuration": {
            "llm_model": settings.ollama_model,
            "embedding_model": settings.ollama_embedding_model,
            "ollama_url": settings.ollama_url,
        },
        "gpu": "not measured: no GPU telemetry is claimed by this harness",
    }
    if not await provider.available():
        report["status"] = "unavailable"
        report["missing"] = "Ollama server is not reachable"
        return report
    models = await provider.list_models()
    missing = [
        model
        for model in (settings.ollama_model, settings.ollama_embedding_model)
        if model not in models
    ]
    if settings.ollama_model not in models:
        report["status"] = "unavailable"
        report["missing"] = missing
        return report
    samples: list[float] = []
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    gateway = LLMGateway(provider)
    for text in (
        "I need to send the report by Friday.",
        "I'm waiting for Rahul to send the proposal.",
        "Ask the placement coordinator about my interview schedule.",
    ):
        started = time.perf_counter()
        await gateway.extract_commitments(text, now=datetime(2026, 11, 2, 10, tzinfo=UTC))
        samples.append((time.perf_counter() - started) * 1000)
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report.update(
        {
            "status": "complete",
            "model_version": await provider.version(),
            "latency_ms_mean": round(statistics.mean(samples), 2),
            "latency_ms_median": round(statistics.median(samples), 2),
            "latency_ms_p95": round(sorted(samples)[max(0, int(len(samples) * 0.95) - 1)], 2),
            "sample_count": len(samples),
            "process_max_rss_kib": after,
            "process_max_rss_delta_kib": max(0, after - before),
            "embedding": "unavailable: configured embedding model is not installed"
            if settings.ollama_embedding_model not in models
            else "not probed",
            "qdrant_storage_growth": "not measured without real embeddings",
            "sqlite_storage_growth": "not measured in this model-only probe",
        }
    )
    return report


if __name__ == "__main__":
    report = asyncio.run(run())
    destination = Path(__file__).parent / "reports" / "performance.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
