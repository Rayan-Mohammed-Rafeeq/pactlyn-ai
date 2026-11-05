"""Compare retrieval configurations on the frozen 0.8 RAG corpus."""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pactlyn.app.configuration import Settings
from pactlyn.llm.providers.ollama import OllamaProvider
from pactlyn.memory.service import MemoryService
from pactlyn.rag.embeddings import DeterministicTestEmbedding
from pactlyn.rag.ingestion import IngestionService, SourceDocument
from pactlyn.rag.retrieval import HybridRetriever
from pactlyn.storage.database import create_session_factory, init_database, make_engine
from pactlyn.storage.models import MemoryKind
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore

DATASET = Path(__file__).parent / "datasets" / "rag-0.8.json"
REPORT = Path(__file__).parent / "reports" / "retrieval-ranking-0.8.json"


def metrics(rows: list[dict[str, Any]], latencies: list[float], mode: str) -> dict[str, Any]:
    answerable = [row for row in rows if row["answerable"]]
    hits5 = sum(bool(set(row["relevant"]) & set(row["ids"][:5])) for row in answerable)
    hits10 = sum(bool(set(row["relevant"]) & set(row["ids"][:10])) for row in answerable)
    precision5 = sum(len(set(row["relevant"]) & set(row["ids"][:5])) / max(len(row["ids"][:5]), 1) for row in rows) / max(len(rows), 1)
    reciprocal = sum((1 / (min(row["ids"].index(item) for item in row["relevant"] if item in row["ids"]) + 1)) if any(item in row["ids"] for item in row["relevant"]) else 0.0 for row in answerable)
    ndcg = 0.0
    for row in answerable:
        dcg = sum(1 / __import__("math").log2(rank + 2) for rank, identifier in enumerate(row["ids"][:5]) if identifier in row["relevant"])
        ideal = sum(1 / __import__("math").log2(rank + 2) for rank in range(min(len(row["relevant"]), 5)))
        ndcg += dcg / ideal if ideal else 0.0
    duplicate = sum(len(row["ids"]) - len(set(row["ids"])) for row in rows) / max(sum(len(row["ids"]) for row in rows), 1)
    return {"mode": mode, "query_denominator": len(rows), "answerable_denominator": len(answerable), "recall_at_5": round(hits5 / max(len(answerable), 1), 4), "recall_at_10": round(hits10 / max(len(answerable), 1), 4), "precision_at_5": round(precision5, 4), "mrr": round(reciprocal / max(len(answerable), 1), 4), "ndcg_at_5": round(ndcg / max(len(answerable), 1), 4), "empty_result_rate": round(sum(not row["ids"] for row in rows) / max(len(rows), 1), 4), "duplicate_context_rate": round(duplicate, 4), "latency_ms_mean": round(statistics.mean(latencies), 2), "latency_ms_p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2)}


async def evaluate(embedder: object, dataset: dict[str, Any], directory: str, mode: str, rerank: bool = False) -> dict[str, Any]:
    engine = make_engine(f"sqlite:///{Path(directory) / 'rag.sqlite3'}")
    init_database(engine)
    session = create_session_factory(engine)()
    vectors = LocalQdrantStore(Path(directory) / "qdrant")
    ingestion = IngestionService(MemoryService(session, vectors, embedder))
    for source in dataset["sources"]:
        await ingestion.ingest(SourceDocument(source["source_type"], source["id"], source["content"], {}), kind=MemoryKind.SEMANTIC)
    retriever = HybridRetriever(session, vectors, embedder)
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    for query in dataset["queries"]:
        started = time.perf_counter()
        evidence = await retriever.search(query["query"], limit=10, collection="personal_knowledge", mode=mode if mode != "rerank" else "hybrid", rerank=rerank or mode == "rerank")
        latencies.append((time.perf_counter() - started) * 1000)
        ids = [item.source_id.split(":chunk:")[0] for item in evidence]
        rows.append({"id": query["id"], "relevant": query["relevant"], "answerable": query["answerable"], "ids": ids})
    dimension = vectors.dimension("personal_knowledge")
    vectors.close()
    session.close()
    engine.dispose()
    return {"metrics": {**metrics(rows, latencies, mode), "embedding_dimension": dimension, "real_embedding": getattr(embedder, "model_name", "") == "nomic-embed-text"}, "rows": rows}


async def main_async() -> dict[str, Any]:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    settings = Settings()
    provider = OllamaProvider(settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model)
    result: dict[str, Any] = {"dataset_version": dataset["dataset_version"], "dataset_path": str(DATASET), "embedding_model": settings.ollama_embedding_model, "real_ollama": {}, "deterministic": {}}
    with TemporaryDirectory(prefix="pactlyn-rag08-deterministic-") as directory:
        for mode, rerank in (("dense", False), ("fts5", False), ("hybrid", False), ("rrf", False), ("rerank", True)):
            result["deterministic"][mode] = await evaluate(DeterministicTestEmbedding(), dataset, directory, mode, rerank)
    if await provider.available() and (settings.ollama_embedding_model in await provider.list_models() or f"{settings.ollama_embedding_model}:latest" in await provider.list_models()):
        with TemporaryDirectory(prefix="pactlyn-rag08-ollama-") as directory:
            for mode, rerank in (("dense", False), ("fts5", False), ("hybrid", False), ("rrf", False), ("rerank", True)):
                result["real_ollama"][mode] = await evaluate(provider, dataset, directory, mode, rerank)
        result["status"] = "complete"
    else:
        result["status"] = "ollama_embedding_unavailable"
    return result


if __name__ == "__main__":
    result = asyncio.run(main_async())
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
