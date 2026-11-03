from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy import text

from pactlyn.app.configuration import Settings
from pactlyn.llm.providers.ollama import OllamaProvider
from pactlyn.memory.service import MemoryService
from pactlyn.rag.embeddings import DeterministicTestEmbedding
from pactlyn.rag.ingestion import IngestionService, SourceDocument
from pactlyn.rag.retrieval import HybridRetriever
from pactlyn.storage.database import create_session_factory, init_database, make_engine
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore


def _model_matches(requested: str, installed: list[str]) -> bool:
    return requested in installed or f"{requested}:latest" in installed


async def _evaluate(
    embedder: object,
    dataset: list[dict[str, str]],
    directory: str,
    *,
    mode: str = "hybrid",
) -> dict[str, object]:
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
    session.execute(text("DROP TABLE IF EXISTS rag_benchmark_fts"))
    session.execute(text("CREATE VIRTUAL TABLE rag_benchmark_fts USING fts5(source_id UNINDEXED, content)"))
    for row in dataset:
        session.execute(
            text("INSERT INTO rag_benchmark_fts(source_id, content) VALUES (:source_id, :content)"),
            {"source_id": row["id"], "content": row["content"]},
        )
    session.commit()
    ranks: list[int] = []
    latencies: list[float] = []
    empty = 0
    precision_hits = 0
    retrieved_at_5 = 0
    for row in dataset:
        started = time.perf_counter()
        if mode == "hybrid":
            evidence = await HybridRetriever(session, vectors, embedder).search(row["query"], limit=10)
        elif mode == "dense":
            query_vector = (await embedder.embed([row["query"]]))[0]  # type: ignore[attr-defined]
            hits = vectors.search("personal_knowledge", query_vector, limit=10)
            evidence = [
                type("Evidence", (), {"source_id": str(hit.payload.get("source_id", hit.id))})()
                for hit in hits
            ]
        elif mode == "fts5":
            tokens = [token for token in row["query"].replace('"', "").split() if token]
            fts_query = " OR ".join(f'"{token}"' for token in tokens) or '""'
            matches: list[Any] = list(session.execute(
                text(
                    "SELECT source_id FROM rag_benchmark_fts WHERE rag_benchmark_fts MATCH :query LIMIT :limit"
                ),
                {"query": fts_query, "limit": 10},
            ).scalars().all())
            evidence = [type("Evidence", (), {"source_id": str(source_id)})() for source_id in matches]
        else:
            raise ValueError(f"Unknown retrieval mode: {mode}")
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
    embedder_any: Any = embedder
    probe_vector = (await embedder_any.embed([dataset[0]["query"]]))[0] if dataset else []
    qdrant_dimension = vectors.dimension("personal_knowledge")
    vectors.close()
    reopened = LocalQdrantStore(Path(directory) / "qdrant")
    persistence_hits = reopened.search("personal_knowledge", probe_vector, limit=1) if probe_vector else []
    reopened.close()
    report = {
        "dataset_size": count,
        "embedding_model": getattr(embedder, "model_name", type(embedder).__name__),
        "retrieval_mode": mode,
        "embedding_dimension": getattr(embedder, "dimension", None),
        "qdrant_dimension": qdrant_dimension,
        "qdrant_persistence_verified": bool(persistence_hits),
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
    session.close()
    engine.dispose()
    return report


async def run() -> dict[str, object]:
    dataset_path = Path(os.environ.get("PACTLYN_RAG_DATASET", Path(__file__).parent / "datasets" / "retrieval.json"))
    dataset = json.loads(
        dataset_path.read_text(encoding="utf-8")
    )
    settings = Settings()
    deterministic_report: dict[str, object]
    with TemporaryDirectory(prefix="pactlyn-rag-real-") as directory:
        deterministic_report = {
            mode: await _evaluate(DeterministicTestEmbedding(), dataset, directory, mode=mode)
            for mode in ("dense", "fts5", "hybrid")
        }
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
        "dataset": str(dataset_path),
        "dataset_size": len(dataset),
        "deterministic": deterministic_report,
        "real_ollama": None,
        "note": "Deterministic results are a harness check only and are not semantic-model evidence.",
    }
    if not await provider.available():
        result["missing"] = "Ollama server is not reachable"
        return result
    models = await provider.list_models()
    if not _model_matches(settings.ollama_embedding_model, models):
        result["missing"] = [settings.ollama_embedding_model]
        return result
    with TemporaryDirectory(prefix="pactlyn-rag-ollama-") as directory:
        real_report = {
            mode: await _evaluate(provider, dataset, directory, mode=mode)
            for mode in ("dense", "fts5", "hybrid")
        }
    result["status"] = "complete"
    result["real_ollama"] = real_report
    return result


if __name__ == "__main__":
    report = asyncio.run(run())
    destination = Path(__file__).parent / "reports" / "rag-real.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
