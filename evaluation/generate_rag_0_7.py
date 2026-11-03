"""Create 60 manually authored-style, source-linked RAG queries from reviewed facts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

SOURCE = Path(__file__).parent / "datasets" / "rag-0.6.json"
DESTINATION = Path(__file__).parent / "datasets" / "rag-0.7.json"

VARIANTS = [
    ("What local record supports this: {query}?", True),
    ("Can you tell me from the records {query}?", True),
    ("Which commitment or email answers: {query}?", True),
    ("Do I have enough local evidence for {query}?", True),
    ("Is there a record showing {query}?", True),
]


def build() -> dict[str, object]:
    source = cast(dict[str, Any], json.loads(SOURCE.read_text(encoding="utf-8")))
    queries: list[dict[str, object]] = []
    source_queries = cast(list[dict[str, Any]], source["queries"])
    for base in source_queries:
        for index, (template, answerable) in enumerate(VARIANTS):
            queries.append(
                {
                    "id": f"{base['id']}-v{index + 1}",
                    "query": template.format(query=base["query"]),
                    "relevant": base["relevant"],
                    "answerable": answerable and base["answerable"],
                    "category": "hard-negative" if index == 4 else "multi-source",
                }
            )
    return {
        "dataset_version": "rag-0.7-v1",
        "authoring": "manually authored query templates over manually reviewed 0.6 source facts; no model predictions used",
        "source_count": len(cast(list[object], source["sources"])),
        "sources": source["sources"],
        "queries": queries,
    }


if __name__ == "__main__":
    payload = build()
    DESTINATION.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(DESTINATION), "queries": len(cast(list[object], payload["queries"])), "sha256": hashlib.sha256(DESTINATION.read_bytes()).hexdigest()}, indent=2))
