from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    root = Path(__file__).parent
    baseline = json.loads((root / "reports" / "baseline.json").read_text(encoding="utf-8"))
    ollama = json.loads(
        (root / "reports" / "ollama-extraction-qwen2.5-7b.json").read_text(encoding="utf-8")
    ) if (root / "reports" / "ollama-extraction-qwen2.5-7b.json").exists() else json.loads(
        (root / "reports" / "ollama-extraction.json").read_text(encoding="utf-8")
    )
    report = {
        "evaluation_timestamp": datetime.now(UTC).isoformat(),
        "dataset": "evaluation/datasets/commitments.json",
        "scoring": {
            "type_accuracy": "first candidate type equals expected type; empty prediction is incorrect",
            "deadline_precision_recall": "binary presence of a due_at value against has_deadline labels",
            "contact_accuracy": "binary person or contact_email presence against has_contact labels",
            "confirmation_accuracy": "candidate needs_confirmation equals requires_confirmation",
            "multi_commitment_accuracy": "not scored: the checked-in 150-example labels contain no expected commitment count",
        },
        "deterministic_baseline": baseline,
        "ollama": ollama,
        "comparison_status": "available" if ollama.get("status") == "complete" else "ollama_unavailable",
        "note": "The qwen report is an explicit PACTLYN_OLLAMA_MODEL override; it is not a result for the configured llama3.2:3b model.",
    }
    destination = root / "reports" / "extraction-comparison.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
