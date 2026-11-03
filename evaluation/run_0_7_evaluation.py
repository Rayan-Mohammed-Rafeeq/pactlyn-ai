"""Score the deterministic 0.7 event and relationship baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pactlyn.core.commitments import CommitmentExtractor

DATASET = Path(__file__).parent / "datasets" / "commitments-0.7.json"
REPORTS = Path(__file__).parent / "reports"


def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0}


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    event_tp = sum(min(row["expected_count"], row["predicted_count"]) for row in rows)
    event_fp = sum(max(0, row["predicted_count"] - row["expected_count"]) for row in rows)
    event_fn = sum(max(0, row["expected_count"] - row["predicted_count"]) for row in rows)
    edges_tp = sum(len(set(row["expected_edges"]) & set(row["predicted_edges"])) for row in rows)
    edges_fp = sum(len(set(row["predicted_edges"]) - set(row["expected_edges"])) for row in rows)
    edges_fn = sum(len(set(row["expected_edges"]) - set(row["predicted_edges"])) for row in rows)
    contact_rows = [row for row in rows if row["expected_contacts"]]
    return {
        "dataset_size": len(rows),
        "event_extraction": prf(event_tp, event_fp, event_fn),
        "event_count_accuracy": round(sum(row["expected_count"] == row["predicted_count"] for row in rows) / len(rows), 4),
        "exact_multi_event_accuracy": round(sum(row["multi_exact"] for row in rows if row["expected_count"] > 1) / sum(row["expected_count"] > 1 for row in rows), 4),
        "relationship_extraction": prf(edges_tp, edges_fp, edges_fn),
        "relation_type_accuracy": round(sum(row["edges_exact"] for row in rows if row["expected_edges"]) / sum(bool(row["expected_edges"]) for row in rows), 4) if any(row["expected_edges"] for row in rows) else 0.0,
        "responsibility_direction_accuracy": round(sum(row["responsibility_correct"] for row in rows) / len(rows), 4),
        "actor_accuracy": round(sum(row["actor_correct"] for row in contact_rows) / len(contact_rows), 4) if contact_rows else 0.0,
        "recipient_accuracy": round(sum(row["recipient_correct"] for row in contact_rows) / len(contact_rows), 4) if contact_rows else 0.0,
        "deadline_owner_accuracy": round(sum(row["deadline_owner_correct"] for row in rows) / len(rows), 4),
        "conditional_accuracy": round(sum(row["conditional_correct"] for row in rows) / len(rows), 4),
        "negation_accuracy": round(sum(row["negation_correct"] for row in rows if row["expected_count"] == 0) / sum(row["expected_count"] == 0 for row in rows), 4) if any(row["expected_count"] == 0 for row in rows) else 0.0,
        "contact_role_accuracy": round(sum(row["role_correct"] for row in contact_rows) / len(contact_rows), 4) if contact_rows else 0.0,
    }


def evaluate(dataset: dict[str, Any], split: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    extractor = CommitmentExtractor()
    rows: list[dict[str, Any]] = []
    for item in dataset["examples"]:
        if item["split"] != split:
            continue
        expected = item["expected"]
        result = extractor.extract(item["text"])
        expected_events = expected["events"]
        predicted = result.candidates
        expected_edges = sorted((edge["source_index"], edge["target_index"], edge["relationship"]) for edge in expected["relationships"])
        predicted_edges = sorted((edge.source_index, edge.target_index, edge.relationship.value) for edge in result.relationships)
        expected_contact = next((event for event in expected_events if event.get("recipient") or event.get("actor") not in {None, "user"}), None)
        predicted_contact = next((event for event in predicted if event.person or event.contact_email), None)
        rows.append({
            "id": item["id"], "scenario": item["scenario"], "expected_count": len(expected_events), "predicted_count": len(predicted),
            "expected_edges": expected_edges, "predicted_edges": predicted_edges, "edges_exact": expected_edges == predicted_edges,
            "multi_exact": len(expected_events) == len(predicted) and [event["type"] for event in expected_events] == [event.type.value for event in predicted],
            "expected_contacts": expected_contact is not None, "actor_correct": bool(expected_contact and predicted_contact and (predicted_contact.actor or predicted_contact.person) == expected_contact.get("actor")),
            "recipient_correct": bool(expected_contact and predicted_contact and (predicted_contact.person or predicted_contact.contact_email) == expected_contact.get("recipient")),
            "role_correct": bool(expected_contact and predicted_contact and ((expected_contact.get("responsibility") == "USER_CONTACTS" and predicted_contact.contact_role == "recipient") or (expected_contact.get("responsibility") in {"OTHER_PARTY_PERFORMS", "USER_WAITING_FOR"} and predicted_contact.contact_role == "responsible"))),
            "responsibility_correct": bool(
                expected_events
                and predicted
                and (
                    expected_events[0].get("responsibility")
                    in {"USER_PERFORMS", "USER_CONTACTS", "CONDITIONALLY_EXECUTES"}
                )
                == (
                    predicted[0].responsibility
                    in {"USER_PERFORMS", "USER_CONTACTS", "CONDITIONALLY_EXECUTES"}
                )
            ),
            "deadline_owner_correct": not any(event.get("deadline_owner") for event in expected_events) or any(candidate.due_at for candidate in predicted),
            "conditional_correct": not any(event.get("responsibility") == "CONDITIONALLY_EXECUTES" for event in expected_events) or any(candidate.condition or candidate.dependency for candidate in predicted),
            "negation_correct": not predicted if not expected_events else True,
        })
    return score(rows), rows


def main() -> None:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    REPORTS.mkdir(parents=True, exist_ok=True)
    full, rows = evaluate(dataset, "train")
    heldout, heldout_rows = evaluate(dataset, "heldout")
    config = {"name": "deterministic-extractor", "dataset_version": dataset["dataset_version"], "seed": dataset["seed"]}
    full["configuration"] = config
    heldout["configuration"] = {**config, "split": "heldout"}
    (REPORTS / "event-extraction-0.7.json").write_text(json.dumps({"full_train": full, "failures": [row for row in rows if row["predicted_count"] != row["expected_count"]]}, indent=2) + "\n")
    (REPORTS / "relationship-extraction-0.7.json").write_text(json.dumps({"full_train": {"metrics": full["relationship_extraction"], "relation_type_accuracy": full["relation_type_accuracy"]}, "failures": [row for row in rows if row["expected_edges"] and not row["edges_exact"]]}, indent=2) + "\n")
    (REPORTS / "responsibility-0.7.json").write_text(json.dumps({"full_train": {key: full[key] for key in ("actor_accuracy", "recipient_accuracy", "responsibility_direction_accuracy", "deadline_owner_accuracy", "contact_role_accuracy")}, "failures": [row for row in rows if not row["responsibility_correct"]]}, indent=2) + "\n")
    heldout_path = REPORTS / "heldout-0.7.json"
    if heldout_path.exists():
        existing = json.loads(heldout_path.read_text(encoding="utf-8"))
    else:
        existing = {}
    if isinstance(existing, dict) and (
        existing.get("status") == "complete" or isinstance(existing.get("qwen2.5:7b"), dict)
    ):
        existing["deterministic"] = heldout
        heldout_path.write_text(json.dumps(existing, indent=2) + "\n")
    else:
        heldout_path.write_text(json.dumps(heldout, indent=2) + "\n")
    print(json.dumps({"train": full, "heldout": heldout}, indent=2))


if __name__ == "__main__":
    main()
