"""Run Qwen2.5 7B on the frozen 0.7 held-out split."""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pactlyn.app.configuration import Settings
from pactlyn.llm.gateway import LLMGateway
from pactlyn.llm.providers.ollama import OllamaProvider

DATASET = Path(__file__).parent / "datasets" / "commitments-0.7.json"
REPORT = Path(__file__).parent / "reports" / "heldout-0.7.json"
NOW = datetime(2026, 11, 2, 10, tzinfo=UTC)


def _context(text: str) -> str:
    names = ["Rahul", "Maya", "Aisha", "Daniel", "Elena", "Noor", "Priya", "Sam", "HR", "library", "placement coordinator", "clinic", "research office", "vendor"]
    return "\n".join(f"Known contact: {name} <{name.casefold().replace(' ', '.')}@example.com>" for name in names if name.casefold() in text.casefold())


def _score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(min(row["expected_count"], row["predicted_count"]) for row in rows)
    fp = sum(max(0, row["predicted_count"] - row["expected_count"]) for row in rows)
    fn = sum(max(0, row["expected_count"] - row["predicted_count"]) for row in rows)
    expected_edges = sum(len(row["expected_edges"]) for row in rows)
    edge_tp = sum(len(set(row["expected_edges"]) & set(row["predicted_edges"])) for row in rows)
    edge_fp = sum(len(set(row["predicted_edges"]) - set(row["expected_edges"])) for row in rows)
    edge_fn = sum(len(set(row["expected_edges"]) - set(row["predicted_edges"])) for row in rows)
    def metrics(tp_value: int, fp_value: int, fn_value: int) -> dict[str, float]:
        precision = tp_value / (tp_value + fp_value) if tp_value + fp_value else 0.0
        recall = tp_value / (tp_value + fn_value) if tp_value + fn_value else 0.0
        return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0}
    contacts = [row for row in rows if row["expected_contact"]]
    return {
        "dataset_size": len(rows), "event_extraction": metrics(tp, fp, fn),
        "event_count_accuracy": round(sum(row["expected_count"] == row["predicted_count"] for row in rows) / len(rows), 4),
        "exact_multi_event_accuracy": round(sum(row["multi_exact"] for row in rows if row["expected_count"] > 1) / sum(row["expected_count"] > 1 for row in rows), 4),
        "relationship_extraction": metrics(edge_tp, edge_fp, edge_fn),
        "relation_type_accuracy": round(sum(row["expected_edges"] == row["predicted_edges"] for row in rows if row["expected_edges"]) / sum(bool(row["expected_edges"]) for row in rows), 4) if expected_edges else 0.0,
        "actor_accuracy": round(sum(row["actor_correct"] for row in contacts) / len(contacts), 4) if contacts else 0.0,
        "recipient_accuracy": round(sum(row["recipient_correct"] for row in contacts) / len(contacts), 4) if contacts else 0.0,
        "responsibility_direction_accuracy": round(sum(row["responsibility_correct"] for row in rows) / len(rows), 4),
        "deadline_owner_accuracy": round(sum(row["deadline_owner_correct"] for row in rows) / len(rows), 4),
        "conditional_accuracy": round(sum(row["conditional_correct"] for row in rows) / len(rows), 4),
        "negation_accuracy": round(sum(row["negation_correct"] for row in rows if row["expected_count"] == 0) / sum(row["expected_count"] == 0 for row in rows), 4) if any(row["expected_count"] == 0 for row in rows) else 0.0,
        "contact_role_accuracy": round(sum(row["role_correct"] for row in contacts) / len(contacts), 4) if contacts else 0.0,
    }


async def run() -> dict[str, Any]:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    heldout = [item for item in dataset["examples"] if item["split"] == "heldout"]
    settings = Settings()
    provider = OllamaProvider(settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model)
    deterministic_report: dict[str, Any] | None = None
    if REPORT.exists():
        existing = json.loads(REPORT.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            if isinstance(existing.get("deterministic"), dict):
                deterministic_report = existing["deterministic"]
            elif existing.get("configuration", {}).get("name") == "deterministic-extractor":
                deterministic_report = existing
    if not await provider.available():
        result = {"status": "ollama_unavailable", "dataset_version": dataset["dataset_version"], "dataset_size": len(heldout), "deterministic": deterministic_report}
        REPORT.write_text(json.dumps(result, indent=2) + "\n")
        return result
    gateway = LLMGateway(provider)
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    for item in heldout:
        started = time.perf_counter()
        extraction = await gateway.extract_commitments(item["text"], now=NOW, timezone_name="UTC", context=_context(item["text"]), prompt_version="improved")
        latencies.append((time.perf_counter() - started) * 1000)
        expected = item["expected"]
        predicted = extraction.candidates
        expected_contact = next((event for event in expected["events"] if event.get("recipient") or event.get("actor") not in {None, "user"}), None)
        predicted_contact = next((event for event in predicted if event.person or event.contact_email), None)
        rows.append({
            "id": item["id"], "scenario": item["scenario"], "expected_count": len(expected["events"]), "predicted_count": len(predicted),
            "expected_edges": sorted((edge["source_index"], edge["target_index"], edge["relationship"]) for edge in expected["relationships"]), "predicted_edges": sorted((edge.source_index, edge.target_index, edge.relationship.value) for edge in extraction.relationships),
            "multi_exact": len(expected["events"]) == len(predicted) and [event["type"] for event in expected["events"]] == [event.type.value for event in predicted],
            "expected_contact": expected_contact is not None, "actor_correct": bool(expected_contact and predicted_contact and (predicted_contact.actor or predicted_contact.person) == expected_contact.get("actor")), "recipient_correct": bool(expected_contact and predicted_contact and (predicted_contact.person or predicted_contact.contact_email) == expected_contact.get("recipient")), "role_correct": bool(expected_contact and predicted_contact and predicted_contact.contact_role == ("recipient" if expected_contact.get("responsibility") == "USER_CONTACTS" else "responsible")),
            "responsibility_correct": bool(expected["events"] and predicted and expected["events"][0].get("responsibility") == predicted[0].responsibility), "deadline_owner_correct": not any(event.get("deadline_owner") for event in expected["events"]) or any(event.due_at for event in predicted), "conditional_correct": not any(event.get("responsibility") == "CONDITIONALLY_EXECUTES" for event in expected["events"]) or any(event.condition or event.dependency for event in predicted), "negation_correct": not predicted if not expected["events"] else True,
        })
    report = {"status": "complete", "dataset_version": dataset["dataset_version"], "configuration": {"model": settings.ollama_model, "prompt_version": "improved", "evaluation_now": NOW.isoformat()}, "metrics": _score(rows), "latency_ms_mean": round(statistics.mean(latencies), 2), "latency_ms_p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2), "rows": rows}
    if deterministic_report is not None:
        report["deterministic"] = deterministic_report
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), indent=2))
