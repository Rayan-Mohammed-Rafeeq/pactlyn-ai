"""Build a comparison from completed reports without rerunning any model."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent
EXPERIMENTS = ROOT / "reports" / "experiments"


def run() -> dict[str, object]:
    reports: dict[str, object] = {}
    for path in sorted(EXPERIMENTS.glob("*.json")):
        if path.name.endswith("-rows.json") or path.name == "summary.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("name") == "ollama_capture_evaluation":
            reports[path.stem] = payload
    baseline_path = ROOT / "reports" / "baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else None
    result = {
        "dataset": "evaluation/datasets/commitments.json",
        "dataset_size": 150,
        "evaluation_now": "2026-11-02T10:00:00+00:00",
        "completed_configurations": sorted(reports),
        "pending_configurations": [
            name for name in (
                "C-improved-qwen2.5-7b-retrieved-context",
                "alternative-qwen2.5-3b",
            ) if name not in reports
        ],
        "deterministic_baseline": baseline,
        "experiments": reports,
        "contact_identity_note": "The original 150-example dataset has no identity gold labels; see heldout-identity.json for independent identity scoring.",
    }
    destination = EXPERIMENTS / "consolidated-comparison.json"
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
