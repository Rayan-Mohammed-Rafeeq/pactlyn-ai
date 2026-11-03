"""Score deterministic and structured extraction on the frozen 0.6 corpus."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pactlyn.core.commitments import CommitmentCandidate, CommitmentExtractor

DATASET = Path(__file__).parent / "datasets" / "commitments-0.6.json"
REPORTS = Path(__file__).parent / "reports"
NOW = datetime(2026, 11, 2, 10, tzinfo=UTC)


def _f1(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
    }


def _score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    type_correct = sum(row["type_correct"] for row in rows)
    contact_tp = sum(row["contact_expected"] and row["contact_predicted"] for row in rows)
    contact_fp = sum(not row["contact_expected"] and row["contact_predicted"] for row in rows)
    contact_fn = sum(row["contact_expected"] and not row["contact_predicted"] for row in rows)
    deadline_tp = sum(row["deadline_expected"] and row["deadline_predicted"] for row in rows)
    deadline_fp = sum(not row["deadline_expected"] and row["deadline_predicted"] for row in rows)
    deadline_fn = sum(row["deadline_expected"] and not row["deadline_predicted"] for row in rows)
    multi_rows = [row for row in rows if row["expected_count"] > 1]
    dependency_rows = [row for row in rows if row["expected_relationships"]]
    return {
        "dataset_size": len(rows),
        "type_accuracy": round(type_correct / len(rows), 4) if rows else 0.0,
        "extraction": _f1(
            sum(min(row["expected_count"], row["predicted_count"]) for row in rows),
            sum(max(0, row["predicted_count"] - row["expected_count"]) for row in rows),
            sum(max(0, row["expected_count"] - row["predicted_count"]) for row in rows),
        ),
        "deadline": _f1(deadline_tp, deadline_fp, deadline_fn),
        "contact_presence": _f1(contact_tp, contact_fp, contact_fn),
        "contact_identity_accuracy": round(
            sum(row["identity_correct"] for row in rows if row["contact_expected"])
            / sum(row["contact_expected"] for row in rows),
            4,
        ) if any(row["contact_expected"] for row in rows) else 0.0,
        "contact_role_accuracy": round(
            sum(row["role_correct"] for row in rows if row["contact_expected"])
            / sum(row["contact_expected"] for row in rows),
            4,
        ) if any(row["contact_expected"] for row in rows) else 0.0,
        "multi_commitment_accuracy": round(sum(row["multi_correct"] for row in multi_rows) / len(multi_rows), 4) if multi_rows else 0.0,
        "dependency_extraction_accuracy": round(sum(row["relationship_correct"] for row in dependency_rows) / len(dependency_rows), 4) if dependency_rows else 0.0,
        "negation_accuracy": round(sum(row["negation_correct"] for row in rows if row["expected_count"] == 0) / sum(row["expected_count"] == 0 for row in rows), 4) if any(row["expected_count"] == 0 for row in rows) else 0.0,
        "ambiguity_detection_accuracy": round(sum(row["ambiguity_correct"] for row in rows) / len(rows), 4) if rows else 0.0,
        "categories": _categories(rows),
    }


def _categories(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for category in sorted({row["scenario"] for row in rows}):
        subset = [row for row in rows if row["scenario"] == category]
        result[category] = {
            "count": float(len(subset)),
            "type_accuracy": round(sum(row["type_correct"] for row in subset) / len(subset), 4),
            "multi_accuracy": round(sum(row["multi_correct"] for row in subset) / len(subset), 4),
            "relationship_accuracy": round(sum(row["relationship_correct"] for row in subset) / len(subset), 4),
        }
    return result


def score_predictions(dataset: dict[str, Any], predictor: Callable[[str], tuple[list[CommitmentCandidate], list[Any]]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for item in dataset["examples"]:
        expected = item["expected"]
        predicted, relationships = predictor(item["text"])
        expected_commitments = expected["commitments"]
        expected_types = [commitment["type"] for commitment in expected_commitments]
        predicted_types = [candidate.type.value for candidate in predicted]
        expected_contact_commitment = next((commitment for commitment in expected_commitments if commitment.get("contact")), None)
        expected_contact = expected_contact_commitment.get("contact") if expected_contact_commitment else None
        predicted_contact = next((candidate for candidate in predicted if candidate.person or candidate.contact_email), None)
        expected_role = expected_contact_commitment.get("contact_role") if expected_contact_commitment else None
        identity_correct = bool(expected_contact and predicted_contact and (predicted_contact.person or predicted_contact.contact_email) == expected_contact)
        role_correct = bool(expected_role and predicted_contact and predicted_contact.contact_role == expected_role)
        expected_relationships = {(edge["source_index"], edge["target_index"], edge["relationship"]) for edge in expected.get("relationships", []) if edge["source_index"] != edge["target_index"]}
        predicted_relationships = {(edge.source_index, edge.target_index, edge.relationship.value) for edge in relationships if edge.source_index != edge.target_index}
        rows.append({
            "id": item["id"],
            "text": item["text"],
            "scenario": item["scenario"],
            "expected_count": len(expected_commitments),
            "predicted_count": len(predicted),
            "expected_relationships": sorted(expected_relationships),
            "predicted_relationships": sorted(predicted_relationships),
            "relationship_correct": expected_relationships == predicted_relationships,
            "multi_correct": len(expected_commitments) == len(predicted) and predicted_types == expected_types,
            "type_correct": bool(expected_types) and predicted_types[:1] == expected_types[:1] or not expected_types and not predicted,
            "contact_expected": expected_contact is not None,
            "contact_predicted": predicted_contact is not None,
            "identity_correct": identity_correct,
            "role_correct": role_correct,
            "deadline_expected": any(commitment.get("has_deadline") for commitment in expected_commitments),
            "deadline_predicted": any(candidate.due_at for candidate in predicted),
            "negation_correct": not predicted if not expected_commitments else True,
            "ambiguity_correct": any(commitment.get("status") == "active" and candidate.needs_confirmation for commitment, candidate in zip(expected_commitments, predicted, strict=False)),
        })
    return _score(rows), rows


def run() -> dict[str, Any]:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    extractor = CommitmentExtractor()
    started = time.perf_counter()
    report, rows = score_predictions(
        dataset,
        lambda text: (lambda result: (result.candidates, result.relationships))(extractor.extract(text, now=NOW)),
    )
    report["configuration"] = {"name": "deterministic-extractor", "evaluation_now": NOW.isoformat(), "seed": dataset["seed"]}
    report["latency_ms_mean"] = round((time.perf_counter() - started) * 1000 / len(dataset["examples"]), 4)
    report["latency_ms_p95"] = report["latency_ms_mean"]
    report["dataset_version"] = dataset["dataset_version"]
    report["multi_commitment_count"] = dataset["multi_commitment_count"]
    heldout = {**dataset, "examples": [item for item in dataset["examples"] if item["split"] == "heldout"]}
    heldout_report, heldout_rows = score_predictions(
        heldout,
        lambda text: (lambda result: (result.candidates, result.relationships))(extractor.extract(text, now=NOW)),
    )
    heldout_report.update({"configuration": report["configuration"], "dataset_version": dataset["dataset_version"], "split": "heldout"})
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "heldout-0.6.json").write_text(json.dumps(heldout_report, indent=2) + "\n", encoding="utf-8")
    (REPORTS / "multi-commitment-0.6.json").write_text(json.dumps({"configuration": report["configuration"], "metrics": report, "failures": [row for row in rows if row["expected_count"] > 1 and not row["multi_correct"]]}, indent=2) + "\n", encoding="utf-8")
    (REPORTS / "dependency-0.6.json").write_text(json.dumps({"configuration": report["configuration"], "metrics": {"accuracy": report["dependency_extraction_accuracy"]}, "failures": [row for row in rows if row["expected_relationships"] and not row["relationship_correct"]]}, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
