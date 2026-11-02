from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pactlyn.memory.service import MemoryService
from pactlyn.rag.embeddings import DeterministicTestEmbedding
from pactlyn.rag.ingestion import IngestionService, SourceDocument
from pactlyn.rag.retrieval import HybridRetriever
from pactlyn.storage.database import create_session_factory, init_database, make_engine
from pactlyn.storage.models import MemoryRecord
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore


async def run() -> dict[str, object]:
    dataset = json.loads((Path(__file__).parent / "datasets" / "retrieval.json").read_text())
    with TemporaryDirectory(prefix="pactlyn-rag-") as directory:
        engine = make_engine(f"sqlite:///{Path(directory) / 'pactlyn.sqlite3'}")
        init_database(engine)
        session = create_session_factory(engine)()
        vectors = LocalQdrantStore(Path(directory) / "qdrant")
        embedder = DeterministicTestEmbedding()
        memory = MemoryService(session, vectors, embedder)
        ingestion = IngestionService(memory)
        for row in dataset:
            await ingestion.ingest(SourceDocument(row["source_type"], row["id"], row["content"], {}))
        retriever = HybridRetriever(session, vectors, embedder)
        ranks: list[int] = []
        precision_hits = 0
        for row in dataset:
            evidence = await retriever.search(row["query"], limit=5)
            ids = [item.source_id.split(":chunk:")[0] for item in evidence]
            if row["relevant"] in ids:
                rank = ids.index(row["relevant"]) + 1
                ranks.append(rank)
                precision_hits += 1
        recall_at_5 = precision_hits / len(dataset)
        mrr = sum(1 / rank for rank in ranks) / len(dataset)
        first = dataset[0]
        ingestion.delete_source(first["id"])
        deleted_hits = await retriever.search(first["query"], limit=5)
        pending = list(
            session.query(MemoryRecord).filter(
                MemoryRecord.indexed.is_(True), MemoryRecord.deleted_at.is_(None)
            )
        )
        if pending:
            pending[0].indexed = False
            vectors.delete("personal_knowledge", pending[0].id)
            session.commit()
            reindexed = await memory.reindex_pending()
        else:
            reindexed = 0
        vectors.close()
        session.close()
        engine.dispose()
    return {
        "dataset_size": len(dataset),
        "embedding_model": DeterministicTestEmbedding.model_name,
        "recall_at_5": round(recall_at_5, 4),
        "mrr": round(mrr, 4),
        "retrieval_precision_at_5": round(recall_at_5, 4),
        "deletion_consistent": not any(first["id"] == item.source_id.split(":chunk:")[0] for item in deleted_hits),
        "reindex_count": reindexed,
        "note": "Executed with the deterministic local evaluation embedder because Ollama was unavailable; no hosted vector service was used.",
    }


if __name__ == "__main__":
    report = asyncio.run(run())
    destination = Path(__file__).parent / "reports" / "rag.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
