"""Compare single-pass and staged relationship reasoning with Qwen2.5 7B.

The live comparison intentionally uses one held-out example per relationship
category as a latency-bounded pilot. Full deterministic metrics are in the
companion report; the pilot is not presented as generalisation evidence.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any

from pactlyn.app.configuration import Settings
from pactlyn.core.commitments import CaptureResult, RelationshipReasoner
from pactlyn.llm.gateway import LLMGateway
from pactlyn.llm.providers.ollama import OllamaProvider

DATASET = Path(__file__).parent / "datasets" / "relationships-0.8.json"
REPORT = Path(__file__).parent / "reports" / "relationship-reasoning-0.8.json"


def score(rows: list[dict[str, Any]], configuration: str, latencies: list[float], calls: int) -> dict[str, Any]:
    expected = [set(tuple(edge) for edge in row["expected"]) for row in rows]
    predicted = [set(tuple(edge) for edge in row["predicted"]) for row in rows]
    tp = sum(len(a & b) for a, b in zip(expected, predicted, strict=True))
    fp = sum(len(b - a) for a, b in zip(expected, predicted, strict=True))
    fn = sum(len(a - b) for a, b in zip(expected, predicted, strict=True))
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    direction_expected = [{(edge[0], edge[1]) for edge in item} for item in expected]
    direction_predicted = [{(edge[0], edge[1]) for edge in item} for item in predicted]
    direction_correct = sum(len(a & b) for a, b in zip(direction_expected, direction_predicted, strict=True))
    direction_denominator = sum(len(a) for a in direction_expected)
    type_correct = tp
    type_denominator = direction_correct
    return {"configuration": configuration, "sample_denominator": len(rows), "model_call_count": calls, "event_count_accuracy": round(sum(row["event_count_correct"] for row in rows) / max(len(rows), 1), 4), "relationship_edge_metrics": {"tp": tp, "fp": fp, "fn": fn, "denominator_predicted": tp + fp, "denominator_expected": tp + fn, "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(2 * precision * recall / max(precision + recall, 1e-9), 4)}, "direction_accuracy": {"correct": direction_correct, "denominator": direction_denominator, "accuracy": round(direction_correct / max(direction_denominator, 1), 4)}, "relationship_type_accuracy": {"correct": type_correct, "denominator": type_denominator, "accuracy": round(type_correct / max(type_denominator, 1), 4)}, "exact_graph_accuracy": {"correct": sum(a == b for a, b in zip(expected, predicted, strict=True)), "denominator": len(rows), "accuracy": round(sum(a == b for a, b in zip(expected, predicted, strict=True)) / max(len(rows), 1), 4)}, "latency_ms_mean": round(statistics.mean(latencies), 2) if latencies else 0.0, "latency_ms_p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2) if latencies else 0.0, "failures": [row for row in rows if set(tuple(edge) for edge in row["expected"]) != set(tuple(edge) for edge in row["predicted"])][:20]}


async def run_config(gateway: LLMGateway, items: list[dict[str, Any]], configuration: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    calls = 0
    for item in items:
        started = time.perf_counter()
        if configuration == "A_single_pass":
            result = await gateway.extract_commitments(item["text"], prompt_version="improved")
            calls += 1
        else:
            events = await gateway.extract_events(item["text"])
            calls += 1
            context = f"Retrieved local context for relationship category: {item['category']}"
            relations = await gateway.extract_relationships(item["text"], events.candidates, context=context if configuration == "D_staged_with_context" else "", candidate_pairs=RelationshipReasoner.candidate_pairs(events.candidates) if configuration in {"C_candidate_edges", "D_staged_with_context"} else None)
            calls += 1
            result = CaptureResult(candidates=events.candidates, relationships=relations.relationships)
            if configuration in {"C_candidate_edges", "D_staged_with_context"}:
                result = RelationshipReasoner.validate(result, item["text"])
        latencies.append((time.perf_counter() - started) * 1000)
        rows.append({"id": item["id"], "expected": [(edge["source_index"], edge["target_index"], edge["relationship"]) for edge in item["relationships"]], "predicted": [(edge.source_index, edge.target_index, edge.relationship.value) for edge in result.relationships], "event_count_correct": len(result.candidates) == len(item["events"])})
    return score(rows, configuration, latencies, calls)


async def main_async() -> dict[str, Any]:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    heldout = [item for item in dataset["examples"] if item["split"] == "heldout"]
    pilot = [next(item for item in heldout if item["category"] == category) for category in sorted({item["category"] for item in heldout})]
    settings = Settings()
    provider = OllamaProvider(settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model)
    result: dict[str, Any] = {"dataset_version": dataset["dataset_version"], "dataset_sha256": _sha256(DATASET), "configuration": {"model": settings.ollama_model, "prompt_version": "improved", "relationship_prompt_version": LLMGateway.relationship_prompt_version()}, "pilot": {"sample_denominator": len(pilot), "selection": "one held-out item per category", "not_generalisation_evidence": True}}
    if not await provider.available():
        result["status"] = "ollama_unavailable"
        return result
    gateway = LLMGateway(provider)
    result["reports"] = {}
    for configuration in ("A_single_pass", "B_staged", "C_candidate_edges", "D_staged_with_context"):
        result["reports"][configuration] = await run_config(gateway, pilot, configuration)
    result["status"] = "complete"
    return result


def _sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    payload = asyncio.run(main_async())
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
    payload["deterministic"] = existing.get("reports", {}) if isinstance(existing, dict) else {}
    REPORT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
