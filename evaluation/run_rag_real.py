from __future__ import annotations

import asyncio
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from pactlyn.app.configuration import Settings
from pactlyn.llm.providers.ollama import OllamaProvider
from pactlyn.memory.service import MemoryService
from pactlyn.rag.embeddings import DeterministicTestEmbedding
from pactlyn.rag.ingestion import IngestionService, SourceDocument
from pactlyn.rag.retrieval import HybridRetriever
from pactlyn.storage.database import create_session_factory, init_database, make_engine
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore


async def _evaluate(embedder: object, dataset: list[dict[str, str]], directory: str) -> dict[str, object]:
    engine = make_engine(f"sqlite:///{Path(directory) / 'rag.sqlite3'}")
    init_database(engine)
    session = create_session_factory(engine)()
    vectors = LocalQdrantStore(Path(directory) / "qdrant")
    memory = MemoryService(session, vectors, embedder)
    ingestion = IngestionService(memory)
    for row in dataset:
        await ingestion.ingest(
            SourceDocument(row["source_type"], row["id"], row["content"], {})
        )
    retriever = HybridRetriever(session, vectors, embedder)
    ranks: list[int] = []
    latencies: list[float] = []
    empty = 0
    precision_hits = 0
    retrieved_at_5 = 0
    for row in dataset:
        started = time.perf_counter()
        evidence = await retriever.search(row["query"], limit=10)
        latencies.append((time.perf_counter() - started) * 1000)
        ids = [item.source_id.split(":chunk:")[0] for item in evidence]
        retrieved_at_5 += min(5, len(ids))
        if not ids:
            empty += 1
        if row["relevant"] in ids[:5]:
            precision_hits += 1
        if row["relevant"] in ids:
            ranks.append(ids.index(row["relevant"]) + 1)
    count = len(dataset)
    report = {
        "dataset_size": count,
        "embedding_model": getattr(embedder, "model_name", type(embedder).__name__),
        "embedding_dimension": getattr(embedder, "dimension", None),
        "recall_at_5": round(precision_hits / count, 4),
        "recall_at_10": round(len(ranks) / count, 4),
        "precision_at_5": round(precision_hits / retrieved_at_5, 4) if retrieved_at_5 else 0.0,
        "precision_definition": "Relevant query target hits divided by all returned results in the top-five slots.",
        "mrr": round(sum(1 / rank for rank in ranks) / count, 4),
        "empty_result_rate": round(empty / count, 4),
        "latency_ms_mean": round(statistics.mean(latencies), 2),
        "latency_ms_median": round(statistics.median(latencies), 2),
        "latency_ms_p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2),
    }
    vectors.close()
    session.close()
    engine.dispose()
    return report


async def run() -> dict[str, object]:
    dataset = json.loads(
        (Path(__file__).parent / "datasets" / "retrieval.json").read_text(encoding="utf-8")
    )
    settings = Settings()
    deterministic_report: dict[str, object]
    with TemporaryDirectory(prefix="pactlyn-rag-real-") as directory:
        deterministic_report = await _evaluate(DeterministicTestEmbedding(), dataset, directory)
    provider = OllamaProvider(
        settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model
    )
    result: dict[str, object] = {
        "status": "unavailable",
        "evaluation_timestamp": datetime.now(UTC).isoformat(),
        "configuration": {
            "ollama_url": settings.ollama_url,
            "embedding_model": settings.ollama_embedding_model,
        },
        "deterministic": deterministic_report,
        "real_ollama": None,
        "note": "Deterministic results are a harness check only and are not semantic-model evidence.",
    }
    if not await provider.available():
        result["missing"] = "Ollama server is not reachable"
        return result
    models = await provider.list_models()
    if settings.ollama_embedding_model not in models:
        result["missing"] = [settings.ollama_embedding_model]
        return result
    with TemporaryDirectory(prefix="pactlyn-rag-ollama-") as directory:
        real_report = await _evaluate(provider, dataset, directory)
    result["status"] = "complete"
    result["real_ollama"] = real_report
    return result


if __name__ == "__main__":
    report = asyncio.run(run())
    destination = Path(__file__).parent / "reports" / "rag-real.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
