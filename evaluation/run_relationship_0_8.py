"""Evaluate directed relationship reasoning without touching the 0.7 corpus."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pactlyn.core.commitments import CaptureResult, CommitmentExtractor, RelationshipReasoner

DATASET = Path(__file__).parent / "datasets" / "relationships-0.8.json"
REPORT = Path(__file__).parent / "reports" / "relationship-reasoning-0.8.json"


def prf(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "denominator_predicted": tp + fp, "denominator_expected": tp + fn, "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0}


def evaluate(rows: list[dict[str, Any]], extract: Callable[[str], CaptureResult], name: str) -> dict[str, Any]:
    edge_tp = edge_fp = edge_fn = 0
    direction_correct = type_correct = conditional_correct = 0
    direction_denominator = type_denominator = conditional_denominator = exact = 0
    orphan = invalid = 0
    failures: list[dict[str, Any]] = []
    for item in rows:
        result = extract(item["text"])
        expected = {(e["source_index"], e["target_index"], e["relationship"]) for e in item["relationships"]}
        predicted = {(e.source_index, e.target_index, e.relationship.value) for e in result.relationships}
        tp = len(expected & predicted)
        edge_tp += tp
        edge_fp += len(predicted - expected)
        edge_fn += len(expected - predicted)
        orphan += sum(e.source_index >= len(result.candidates) or e.target_index >= len(result.candidates) for e in result.relationships)
        invalid += len(result.rejected_relationships)
        expected_pairs = {(e[0], e[1]) for e in expected}
        predicted_pairs = {(e[0], e[1]) for e in predicted}
        direction_correct += len(expected_pairs & predicted_pairs)
        direction_denominator += len(expected_pairs)
        type_correct += len(expected & predicted)
        type_denominator += len(expected_pairs & predicted_pairs)
        expected_conditional = {(e["source_index"], e["target_index"]) for e in item["relationships"] if e.get("conditional_trigger")}
        predicted_conditional = {(e.source_index, e.target_index) for e in result.relationships if any(word in (e.evidence or "").casefold() for word in ("if", "once", "after", "until"))}
        conditional_correct += len(expected_conditional & predicted_conditional)
        conditional_denominator += len(expected_conditional)
        is_exact = expected == predicted
        exact += is_exact
        if not is_exact:
            failures.append({"id": item["id"], "category": item["category"], "expected": sorted(expected), "predicted": sorted(predicted), "warnings": result.relationship_warnings})
    return {
        "configuration": name,
        "dataset_version": "relationships-0.8-v1",
        "sample_count": len(rows),
        "relationship_edge_metrics": prf(edge_tp, edge_fp, edge_fn),
        "direction_accuracy": {"correct": direction_correct, "denominator": direction_denominator, "accuracy": round(direction_correct / direction_denominator, 4) if direction_denominator else 0.0},
        "relationship_type_accuracy": {"correct": type_correct, "denominator": type_denominator, "accuracy": round(type_correct / type_denominator, 4) if type_denominator else 0.0},
        "conditional_trigger_accuracy": {"correct": conditional_correct, "denominator": conditional_denominator, "accuracy": round(conditional_correct / conditional_denominator, 4) if conditional_denominator else 0.0},
        "exact_graph_accuracy": {"correct": exact, "denominator": len(rows), "accuracy": round(exact / len(rows), 4) if rows else 0.0},
        "orphan_edge_rate": {"invalid_edges": orphan, "predicted_edge_denominator": edge_tp + edge_fp, "rate": round(orphan / (edge_tp + edge_fp), 4) if edge_tp + edge_fp else 0.0},
        "invalid_edge_rate": {"rejected_edges": invalid, "predicted_edge_denominator": edge_tp + edge_fp + invalid, "rate": round(invalid / (edge_tp + edge_fp + invalid), 4) if edge_tp + edge_fp + invalid else 0.0},
        "failures": failures[:30],
    }


def main() -> None:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    rows = dataset["examples"]
    heldout = [row for row in rows if row["split"] == "heldout"]
    extractor = CommitmentExtractor()
    reports = {
        "deterministic_single_pass": evaluate(rows, extractor.extract, "deterministic_single_pass"),
        "deterministic_staged": evaluate(rows, lambda text: _staged_deterministic(extractor, text), "deterministic_staged"),
        "heldout_deterministic_single_pass": evaluate(heldout, extractor.extract, "heldout_deterministic_single_pass"),
        "heldout_deterministic_staged": evaluate(heldout, lambda text: _staged_deterministic(extractor, text), "heldout_deterministic_staged"),
    }
    payload = {"dataset_path": str(DATASET), "dataset_sha256": _sha256(DATASET), "reports": reports, "known_limitation": "The deterministic staged path isolates relationship reasoning but does not measure Qwen latency; the Qwen comparison is recorded separately when run against the same held-out rows."}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


def _staged_deterministic(extractor: CommitmentExtractor, text: str) -> CaptureResult:
    events = extractor.extract(text)
    inferred = RelationshipReasoner.infer(events.candidates, text)
    return CaptureResult(candidates=events.candidates, relationships=events.relationships + inferred.relationships, explanation=inferred.explanation)


def _sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    main()
