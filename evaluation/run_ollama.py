from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path

from pactlyn.app.configuration import Settings
from pactlyn.llm.gateway import LLMGateway
from pactlyn.llm.providers.ollama import OllamaProvider


async def run() -> dict[str, object]:
    settings = Settings()
    provider = OllamaProvider(settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model)
    if not await provider.available():
        return {
            "name": "ollama_capture_evaluation",
            "status": "unavailable",
            "model": settings.ollama_model,
            "note": "No live Ollama service was available; no model result was fabricated.",
        }
    dataset = json.loads((Path(__file__).parent / "datasets" / "commitments.json").read_text(encoding="utf-8"))
    gateway = LLMGateway(provider)
    type_correct = 0
    confirmation_correct = 0
    latencies: list[float] = []
    failures = 0
    for row in dataset:
        started = time.perf_counter()
        result = await gateway.extract_commitments(str(row["text"]), now=None)
        latencies.append((time.perf_counter() - started) * 1000)
        if not result.candidates:
            failures += 1
            continue
        candidate = result.candidates[0]
        expected = row["expected"]
        type_correct += candidate.type.value == expected["type"]
        confirmation_correct += candidate.needs_confirmation == expected["requires_confirmation"]
    count = len(dataset)
    return {
        "name": "ollama_capture_evaluation",
        "status": "complete",
        "model": settings.ollama_model,
        "dataset_size": count,
        "type_accuracy": round(type_correct / count, 4),
        "confirmation_accuracy": round(confirmation_correct / count, 4),
        "empty_results": failures,
        "latency_ms_mean": round(statistics.mean(latencies), 2),
        "latency_ms_p95": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 2),
    }


if __name__ == "__main__":
    report = asyncio.run(run())
    destination = Path(__file__).parent / "reports" / "ollama.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
