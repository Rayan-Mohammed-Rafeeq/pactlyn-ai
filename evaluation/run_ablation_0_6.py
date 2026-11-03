"""Run extraction ablations on the frozen 0.6 held-out split."""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from run_0_6_evaluation import _score

from pactlyn.app.configuration import Settings
from pactlyn.llm.gateway import LLMGateway
from pactlyn.llm.providers.ollama import OllamaProvider

DATASET = Path(__file__).parent / "datasets" / "commitments-0.6.json"
CONTEXT = Path(__file__).parent / "datasets" / "context-fixture-0.6.json"
REPORT = Path(__file__).parent / "reports" / "ablation-0.6.json"
NOW = datetime(2026, 11, 2, 10, tzinfo=UTC)


def _context_for(text: str) -> str:
    fixture = json.loads(CONTEXT.read_text(encoding="utf-8"))
    lowered = text.casefold()
    lines: list[str] = []
    for contact in fixture["contacts"]:
        if any(token in lowered for token in contact["name"].casefold().split() if len(token) > 2):
            lines.append(f"Known contact: {contact['name']} <{contact['email']}> ({contact['kind']})")
    for memory in fixture["memories"]:
        if any(token in lowered for token in memory["content"].casefold().split() if len(token) > 3):
            lines.append(f"Memory ({memory['source_id']}): {memory['content']}")
    return "\n".join(lines)


async def run() -> dict[str, Any]:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    heldout = {**dataset, "examples": [item for item in dataset["examples"] if item["split"] == "heldout"]}
    settings = Settings()
    provider = OllamaProvider(settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model)
    report: dict[str, Any] = {
        "dataset": str(DATASET),
        "dataset_version": dataset["dataset_version"],
        "split": "heldout",
        "example_count": len(heldout["examples"]),
        "evaluation_now": NOW.isoformat(),
        "configurations": {},
        "note": "A deterministic full-corpus result is in heldout-0.6.json; model ablations use this frozen held-out split and identical inputs.",
    }
    if not await provider.available():
        report["status"] = "ollama_unavailable"
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    gateway = LLMGateway(provider)
    configurations = {
        "B-raw-qwen2.5-7b": {"apply_validation": False},
        "C-grounded-validation": {"apply_validation": True, "normalize_dates": False, "ground_contacts": True},
        "D-grounded-validation-date-normalization": {"apply_validation": True, "normalize_dates": True, "ground_contacts": True},
        "E-grounded-validation-date-normalization-context": {"apply_validation": True, "normalize_dates": True, "ground_contacts": True, "context": True},
    }
    for name, options in configurations.items():
        rows: list[dict[str, Any]] = []
        latencies: list[float] = []
        for item in heldout["examples"]:
            started = time.perf_counter()
            result = await gateway.extract_commitments(
                item["text"],
                now=NOW,
                timezone_name="UTC",
                context=_context_for(item["text"]) if options.get("context") else "",
                apply_validation=bool(options.get("apply_validation")),
                normalize_dates=bool(options.get("normalize_dates", True)),
                ground_contacts=bool(options.get("ground_contacts", True)),
            )
            latencies.append((time.perf_counter() - started) * 1000)
            rows.append({"item": item, "result": result})
        score_rows: list[dict[str, Any]] = []
        for row in rows:
            result = row["result"]
            item = row["item"]
            expected = item["expected"]
            predicted = result.candidates
            expected_types = [entry["type"] for entry in expected["commitments"]]
            predicted_types = [candidate.type.value for candidate in predicted]
            expected_contact = next((entry for entry in expected["commitments"] if entry.get("contact")), None)
            predicted_contact = next((candidate for candidate in predicted if candidate.person or candidate.contact_email), None)
            score_rows.append({
                "expected_count": len(expected["commitments"]), "predicted_count": len(predicted),
                "type_correct": bool(expected_types) and predicted_types[:1] == expected_types[:1] or not expected_types and not predicted,
                "contact_expected": expected_contact is not None, "contact_predicted": predicted_contact is not None,
                "identity_correct": bool(expected_contact and predicted_contact and (predicted_contact.person or predicted_contact.contact_email) == expected_contact["contact"]),
                "role_correct": bool(expected_contact and predicted_contact and predicted_contact.contact_role == expected_contact.get("contact_role")),
                "deadline_expected": any(entry.get("has_deadline") for entry in expected["commitments"]), "deadline_predicted": any(candidate.due_at for candidate in predicted),
                "expected_relationships": sorted((edge["source_index"], edge["target_index"], edge["relationship"]) for edge in expected.get("relationships", [])),
                "predicted_relationships": sorted((edge.source_index, edge.target_index, edge.relationship.value) for edge in result.relationships),
                "relationship_correct": sorted((edge["source_index"], edge["target_index"], edge["relationship"]) for edge in expected.get("relationships", [])) == sorted((edge.source_index, edge.target_index, edge.relationship.value) for edge in result.relationships),
                "multi_correct": len(expected["commitments"]) == len(predicted) and predicted_types == expected_types,
                "negation_correct": not predicted if not expected["commitments"] else True, "ambiguity_correct": True, "scenario": item["scenario"],
            })
        metrics = _score(score_rows)
        metrics["latency_ms_mean"] = round(statistics.mean(latencies), 2)
        metrics["latency_ms_p95"] = round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2)
        report["configurations"][name] = metrics
    report["status"] = "complete"
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), indent=2))
