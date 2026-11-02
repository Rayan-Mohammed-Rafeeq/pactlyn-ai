from __future__ import annotations

import json
from pathlib import Path

from pactlyn.core.commitments import CommitmentExtractor


def run() -> dict[str, object]:
    dataset = json.loads((Path(__file__).parent / "datasets" / "commitments.json").read_text(encoding="utf-8"))
    extractor = CommitmentExtractor()
    type_correct = 0
    confirmation_correct = 0
    deadline_correct = 0
    for row in dataset:
        candidate = extractor.extract(str(row["text"])).candidates[0]
        expected = row["expected"]
        type_correct += candidate.type.value == expected["type"]
        confirmation_correct += candidate.needs_confirmation == expected["requires_confirmation"]
        deadline_correct += (candidate.due_at is not None) == expected["has_deadline"]
    count = len(dataset)
    return {
        "name": "deterministic_capture_baseline",
        "dataset_size": count,
        "type_accuracy": round(type_correct / count, 4),
        "confirmation_accuracy": round(confirmation_correct / count, 4),
        "deadline_presence_accuracy": round(deadline_correct / count, 4),
        "note": "This is a reproducible baseline, not an LLM quality claim.",
    }


if __name__ == "__main__":
    result = run()
    destination = Path(__file__).parent / "reports" / "baseline.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
