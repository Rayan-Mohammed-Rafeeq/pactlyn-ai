"""Export contact evidence without pretending the dataset contains contact gold values."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pactlyn.core.commitments import CommitmentExtractor

ROOT = Path(__file__).parent
DATASET = ROOT / "datasets" / "commitments.json"
REPORTS = ROOT / "reports"


def run() -> list[dict[str, object]]:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    detailed = Path(os.environ.get("PACTLYN_CONTACT_AUDIT_SOURCE", REPORTS / "extraction-audit.json"))
    if detailed.exists():
        predictions = {row["id"]: row for row in json.loads(detailed.read_text(encoding="utf-8"))}
    else:
        legacy = REPORTS / "extraction-errors-qwen2.5-7b.json"
        predictions = {row["id"]: row for row in json.loads(legacy.read_text(encoding="utf-8"))}
    failures: list[dict[str, object]] = []
    extractor = CommitmentExtractor()
    for row in dataset:
        expected = row["expected"]
        prediction = predictions.get(row["id"], {})
        expected_presence = bool(expected["has_contact"])
        predicted_presence = bool(prediction.get("contact_predicted", False))
        if expected_presence == predicted_presence:
            continue
        inferred = extractor.extract(str(row["text"])).candidates[0] if expected_presence else None
        failures.append(
            {
                "id": row["id"],
                "source_text": row["text"],
                "label": {"has_contact": expected_presence},
                "expected_contact_value_inferred_from_source": inferred.person if inferred else None,
                "expected_contact_kind_inferred_from_source": inferred.contact_kind if inferred else None,
                "expected_contact_role_inferred_from_source": inferred.contact_role if inferred else None,
                "predicted_contact_value": prediction.get("predicted_person"),
                "predicted_contact_email": prediction.get("predicted_contact_email"),
                "predicted_contact_kind": prediction.get("predicted_contact_kind"),
                "predicted_contact_role": prediction.get("predicted_contact_role"),
                "diagnosis": "The checked-in dataset has no expected contact value; this row is a presence failure and cannot support name-level accuracy.",
            }
        )
    return failures


if __name__ == "__main__":
    REPORTS.mkdir(parents=True, exist_ok=True)
    result = run()
    destination = Path(os.environ.get("PACTLYN_CONTACT_AUDIT_OUTPUT", REPORTS / "contact-failures.json"))
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"failed_examples": len(result), "path": str(destination)}, indent=2))
