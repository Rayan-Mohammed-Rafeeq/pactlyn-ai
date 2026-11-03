"""Run populated multi-source RAG retrieval on the frozen 0.6 corpus."""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy import text

from pactlyn.app.configuration import Settings
from pactlyn.llm.providers.ollama import OllamaProvider
from pactlyn.memory.service import MemoryService
from pactlyn.rag.embeddings import DeterministicTestEmbedding
from pactlyn.rag.ingestion import IngestionService, SourceDocument
from pactlyn.storage.database import create_session_factory, init_database, make_engine
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore

DATASET = Path(__file__).parent / "datasets" / "rag-0.6.json"
REPORT = Path(__file__).parent / "reports" / "rag-expanded-0.6.json"


def _metrics(rows: list[dict[str, Any]], mode: str, dimension: int | None, latencies: list[float], persistence: bool) -> dict[str, object]:
    count = len(rows)
    hits5 = sum(bool(set(row["relevant"]) & set(row["ids"][:5])) for row in rows if row["answerable"])
    hits10 = sum(bool(set(row["relevant"]) & set(row["ids"][:10])) for row in rows if row["answerable"])
    relevant_rows = sum(row["answerable"] for row in rows)
    reciprocal = []
    for row in rows:
        ranks = [row["ids"].index(identifier) + 1 for identifier in row["relevant"] if identifier in row["ids"]]
        if ranks:
            reciprocal.append(1 / min(ranks))
    no_answer = [row for row in rows if not row["answerable"]]
    return {
        "dataset_size": count,
        "retrieval_mode": mode,
        "embedding_dimension": dimension,
        "recall_at_5": round(hits5 / relevant_rows, 4) if relevant_rows else 0.0,
        "recall_at_10": round(hits10 / relevant_rows, 4) if relevant_rows else 0.0,
        "precision_at_5": round(sum(bool(set(row["relevant"]) & set(row["ids"][:5])) for row in rows) / sum(bool(row["ids"][:5]) for row in rows), 4) if rows else 0.0,
        "mrr": round(sum(reciprocal) / relevant_rows, 4) if relevant_rows else 0.0,
        "empty_result_rate": round(sum(not row["ids"] for row in rows) / count, 4) if count else 0.0,
        "no_answer_queries": len(no_answer),
        "no_answer_returned_evidence_rate": round(sum(bool(row["ids"]) for row in no_answer) / len(no_answer), 4) if no_answer else 0.0,
        "latency_ms_mean": round(statistics.mean(latencies), 2) if latencies else 0.0,
        "latency_ms_p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2) if latencies else 0.0,
        "qdrant_persistence_verified": persistence,
    }


async def _evaluate(embedder: object, dataset: dict[str, Any], directory: str, mode: str) -> dict[str, object]:
    engine = make_engine(f"sqlite:///{Path(directory) / 'rag.sqlite3'}")
    init_database(engine)
    session = create_session_factory(engine)()
    vectors = LocalQdrantStore(Path(directory) / "qdrant")
    ingestion = IngestionService(MemoryService(session, vectors, embedder))
    for source in dataset["sources"]:
        await ingestion.ingest(SourceDocument(source["source_type"], source["id"], source["content"], {}))
    session.execute(text("DROP TABLE IF EXISTS rag06_fts"))
    session.execute(text("CREATE VIRTUAL TABLE rag06_fts USING fts5(source_id UNINDEXED, content)"))
    for source in dataset["sources"]:
        session.execute(text("INSERT INTO rag06_fts(source_id, content) VALUES (:id, :content)"), {"id": source["id"], "content": source["content"]})
    session.commit()
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    embedder_any: Any = embedder
    for query in dataset["queries"]:
        started = time.perf_counter()
        if mode == "dense":
            vector = (await embedder_any.embed([query["query"]]))[0]
            hits = vectors.search("personal_knowledge", vector, limit=10)
            identifiers = [str(hit.payload.get("source_id", hit.id)).split(":chunk:")[0] for hit in hits]
        elif mode == "fts5":
            tokens = [token for token in query["query"].replace('"', "").split() if token]
            expression = " OR ".join(f'"{token}"' for token in tokens) or '""'
            identifiers = list(session.execute(text("SELECT source_id FROM rag06_fts WHERE rag06_fts MATCH :q LIMIT 10"), {"q": expression}).scalars())
        else:
            vector = (await embedder_any.embed([query["query"]]))[0]
            semantic = vectors.search("personal_knowledge", vector, limit=10)
            tokens = [token for token in query["query"].replace('"', "").split() if token]
            expression = " OR ".join(f'"{token}"' for token in tokens) or '""'
            lexical: list[str] = list(session.execute(text("SELECT source_id FROM rag06_fts WHERE rag06_fts MATCH :q LIMIT 10"), {"q": expression}).scalars())
            scores: dict[str, float] = {}
            for rank, hit in enumerate(semantic, 1):
                identifier = str(hit.payload.get("source_id", hit.id)).split(":chunk:")[0]
                scores[identifier] = scores.get(identifier, 0) + 1 / (60 + rank)
            for rank, identifier in enumerate(lexical, 1):
                scores[str(identifier)] = scores.get(str(identifier), 0) + 1 / (60 + rank)
            identifiers = [identifier for identifier, _score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:10]]
        latencies.append((time.perf_counter() - started) * 1000)
        rows.append({"id": query["id"], "query": query["query"], "relevant": query["relevant"], "answerable": query["answerable"], "ids": identifiers})
    probe = (await embedder_any.embed([dataset["queries"][0]["query"]]))[0]
    dimension = vectors.dimension("personal_knowledge")
    vectors.close()
    reopened = LocalQdrantStore(Path(directory) / "qdrant")
    persistence = bool(reopened.search("personal_knowledge", probe, limit=1))
    reopened.close()
    session.close()
    engine.dispose()
    return {"metrics": _metrics(rows, mode, dimension, latencies, persistence), "rows": rows}


async def run() -> dict[str, object]:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    settings = Settings()
    result: dict[str, object] = {"dataset": str(DATASET), "dataset_version": dataset["dataset_version"], "source_count": len(dataset["sources"]), "query_count": len(dataset["queries"]), "deterministic": {}, "real_ollama": None}
    with TemporaryDirectory(prefix="pactlyn-rag06-deterministic-") as directory:
        result["deterministic"] = {mode: await _evaluate(DeterministicTestEmbedding(), dataset, directory, mode) for mode in ("dense", "fts5", "hybrid")}
    provider = OllamaProvider(settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model)
    if os.environ.get("PACTLYN_RAG_SKIP_REAL") == "1":
        result["status"] = "deterministic_only"
    elif not await provider.available():
        result["status"] = "ollama_unavailable"
    elif settings.ollama_embedding_model not in await provider.list_models() and f"{settings.ollama_embedding_model}:latest" not in await provider.list_models():
        result["status"] = "embedding_unavailable"
    else:
        with TemporaryDirectory(prefix="pactlyn-rag06-ollama-") as directory:
            result["real_ollama"] = {mode: await _evaluate(provider, dataset, directory, mode) for mode in ("dense", "fts5", "hybrid")}
        result["status"] = "complete"
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), indent=2))
