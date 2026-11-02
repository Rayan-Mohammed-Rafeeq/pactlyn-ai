from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from pactlyn.core.commitments import CommitmentExtractor


def run() -> dict[str, object]:
    dataset = json.loads((Path(__file__).parent / "datasets" / "commitments.json").read_text(encoding="utf-8"))
    extractor = CommitmentExtractor()
    type_correct = 0
    confirmation_correct = 0
    deadline_correct = 0
    contact_correct = 0
    latencies: list[float] = []
    for row in dataset:
        started = time.perf_counter()
        candidate = extractor.extract(str(row["text"])).candidates[0]
        latencies.append((time.perf_counter() - started) * 1000)
        expected = row["expected"]
        type_correct += candidate.type.value == expected["type"]
        confirmation_correct += candidate.needs_confirmation == expected["requires_confirmation"]
        deadline_correct += (candidate.due_at is not None) == expected["has_deadline"]
        contact_correct += (candidate.person is not None) == expected["has_contact"]
    count = len(dataset)
    deadline_tp = sum(
        extractor.extract(str(row["text"])).candidates[0].due_at is not None and row["expected"]["has_deadline"]
        for row in dataset
    )
    deadline_predicted = sum(
        extractor.extract(str(row["text"])).candidates[0].due_at is not None for row in dataset
    )
    deadline_expected = sum(row["expected"]["has_deadline"] for row in dataset)
    precision = deadline_tp / deadline_predicted if deadline_predicted else 0.0
    recall = deadline_tp / deadline_expected if deadline_expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "name": "deterministic_capture_baseline",
        "dataset_size": count,
        "type_accuracy": round(type_correct / count, 4),
        "confirmation_accuracy": round(confirmation_correct / count, 4),
        "deadline_presence_accuracy": round(deadline_correct / count, 4),
        "contact_presence_accuracy": round(contact_correct / count, 4),
        "deadline_precision": round(precision, 4),
        "deadline_recall": round(recall, 4),
        "deadline_f1": round(f1, 4),
        "latency_ms_mean": round(statistics.mean(latencies), 4),
        "latency_ms_p95": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 4),
        "note": "This is a reproducible baseline, not an LLM quality claim.",
    }


if __name__ == "__main__":
    result = run()
    destination = Path(__file__).parent / "reports" / "baseline.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
