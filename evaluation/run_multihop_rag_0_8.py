"""Evaluate multi-source retrieval completeness and grounded answer coverage."""

from __future__ import annotations

import asyncio
import json
import re
import statistics
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pactlyn.app.configuration import Settings
from pactlyn.llm.interfaces import LLMUnavailable
from pactlyn.llm.providers.ollama import OllamaProvider
from pactlyn.memory.service import MemoryService
from pactlyn.rag.ingestion import IngestionService, SourceDocument
from pactlyn.rag.retrieval import HybridRetriever
from pactlyn.storage.database import create_session_factory, init_database, make_engine
from pactlyn.storage.models import MemoryKind
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore

DATASET = Path(__file__).parent / "datasets" / "rag-0.8.json"
REPORT = Path(__file__).parent / "reports" / "multihop-rag-0.8.json"


def tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[A-Za-z0-9]+", value.casefold()) if len(token) > 3}


async def evaluate(embedder: object, dataset: dict[str, Any], directory: str, provider: OllamaProvider | None = None) -> dict[str, Any]:
    engine = make_engine(f"sqlite:///{Path(directory) / 'rag.sqlite3'}")
    init_database(engine)
    session = create_session_factory(engine)()
    vectors = LocalQdrantStore(Path(directory) / "qdrant")
    ingestion = IngestionService(MemoryService(session, vectors, embedder))
    source_map = {source["id"]: source for source in dataset["sources"]}
    for source in dataset["sources"]:
        await ingestion.ingest(SourceDocument(source["source_type"], source["id"], source["content"], {}), kind=MemoryKind.SEMANTIC)
    retriever = HybridRetriever(session, vectors, embedder)
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    answer_model_status = "available" if provider is not None else "not_requested"
    for query in dataset["queries"]:
        started = time.perf_counter()
        evidence = await retriever.search(query["query"], limit=10, mode="hybrid", rerank=True)
        answer = None
        citations: list[str] = []
        if provider is not None and query["answerable"]:
            context = "\n\n".join(f"[source:{item.source_type}/{item.source_id}]\n{item.content}" for item in evidence)
            try:
                answer = await provider.complete([
                    {"role": "system", "content": "Answer only from local evidence. Address every part of the question, do not infer missing facts, and cite exact [source:type/id] identifiers."},
                    {"role": "user", "content": f"Question: {query['query']}\nExpected task shape: multi-source reasoning\nEvidence:\n{context}"},
                ])
                citations = [item.split(":chunk:")[0] for item in re.findall(r"\[source:[^/]+/([^\]]+)\]", answer)]
            except LLMUnavailable as exc:
                answer_model_status = f"unavailable: {exc}"
                provider = None
        latencies.append((time.perf_counter() - started) * 1000)
        ids = [item.source_id.split(":chunk:")[0] for item in evidence]
        relevant = set(query["relevant"])
        expected_terms = tokens(query["answer"])
        answer_terms = tokens(answer or " ".join(source_map[item]["content"] for item in ids if item in source_map))
        sufficient = bool(relevant) and relevant <= set(ids) if query["answerable"] else False
        rows.append({"id": query["id"], "answerable": query["answerable"], "multi_hop": query["multi_hop"], "required_sources": len(relevant), "retrieved_relevant": len(relevant & set(ids)), "evidence_complete": sufficient, "citations": citations, "citation_correct": bool(set(citations) & relevant) if query["answerable"] and answer is not None else False, "answer_evaluated": answer is not None, "answer_correct_proxy": answer is not None and len(expected_terms & answer_terms) / max(len(expected_terms), 1) >= 0.4 if query["answerable"] else False, "answer": answer, "ids": ids})
    vectors.close()
    session.close()
    engine.dispose()
    answerable = [row for row in rows if row["answerable"]]
    multi = [row for row in answerable if row["multi_hop"]]
    evaluated_answers = [row for row in answerable if row["answer_evaluated"]]
    return {"metrics": {"query_denominator": len(rows), "answerable_denominator": len(answerable), "multi_hop_denominator": len(multi), "answer_evaluated_denominator": len(evaluated_answers), "evidence_completeness": round(sum(row["evidence_complete"] for row in multi) / max(len(multi), 1), 4), "multi_source_retrieval_recall": round(sum(row["retrieved_relevant"] / max(row["required_sources"], 1) for row in multi) / max(len(multi), 1), 4), "answer_correctness": round(sum(row["answer_correct_proxy"] for row in evaluated_answers) / max(len(evaluated_answers), 1), 4) if evaluated_answers else None, "relationship_reasoning_accuracy": round(sum(row["evidence_complete"] for row in rows if row["multi_hop"]) / max(sum(row["multi_hop"] for row in rows), 1), 4), "citation_correctness": round(sum(row["citation_correct"] for row in evaluated_answers) / max(len(evaluated_answers), 1), 4) if evaluated_answers else None, "latency_ms_mean": round(statistics.mean(latencies), 2), "latency_ms_p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2), "answer_model_status": answer_model_status}, "rows": rows}


async def main_async() -> dict[str, Any]:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    settings = Settings()
    provider = OllamaProvider(settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model)
    result: dict[str, Any] = {"dataset_version": dataset["dataset_version"], "dataset_path": str(DATASET), "embedding_model": settings.ollama_embedding_model, "real_ollama": None}
    if await provider.available() and (settings.ollama_embedding_model in await provider.list_models() or f"{settings.ollama_embedding_model}:latest" in await provider.list_models()):
        with TemporaryDirectory(prefix="pactlyn-multihop-08-") as directory:
            result["real_ollama"] = await evaluate(provider, dataset, directory, provider if settings.ollama_model else None)
        result["status"] = "complete"
    else:
        result["status"] = "ollama_embedding_unavailable"
    return result


if __name__ == "__main__":
    result = asyncio.run(main_async())
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
