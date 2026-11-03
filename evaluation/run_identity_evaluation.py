"""Evaluate manually authored contact identities on a held-out dataset."""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pactlyn.app.configuration import Settings
from pactlyn.llm.gateway import LLMGateway
from pactlyn.llm.providers.ollama import OllamaProvider

DATASET = Path(__file__).parent / "datasets" / "commitments-heldout.json"
REPORTS = Path(__file__).parent / "reports"
EVAL_NOW = datetime(2026, 11, 2, 10, tzinfo=UTC)


def _norm(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.casefold().strip(" .,!?:;").split())


def _model_matches(requested: str, installed: list[str]) -> bool:
    return requested in installed or f"{requested}:latest" in installed


def _row(row: dict[str, Any], result: Any, latency_ms: float) -> dict[str, Any]:
    expected = cast(dict[str, Any], row["expected"])
    candidates = result.candidates
    candidate = candidates[0] if candidates else None
    expected_contact = expected.get("contact")
    predicted_value = candidate.person if candidate else None
    predicted_value = predicted_value or (candidate.contact_email if candidate else None)
    expected_value = expected_contact.get("value") if isinstance(expected_contact, dict) else None
    exact_identity = bool(expected_value and _norm(predicted_value) == _norm(str(expected_value)))
    kind_exact = bool(
        expected_contact
        and candidate
        and candidate.contact_kind == expected_contact.get("kind")
    )
    role_exact = bool(
        expected_contact
        and candidate
        and candidate.contact_role == expected_contact.get("role")
    )
    expected_resolved = bool(expected_contact and expected_contact.get("resolvable")) if isinstance(expected_contact, dict) else False
    status_ok = (
        candidate is not None
        and candidate.contact_status == ("resolved" if expected_resolved else "unresolved")
    ) if expected_contact else candidate is None or not predicted_value
    identity_correct = exact_identity and status_ok
    type_correct = (
        candidate is None and expected.get("type") is None
    ) or bool(candidate and candidate.type.value == expected.get("type"))
    contact_expected = expected_contact is not None
    contact_predicted = bool(predicted_value)
    multi_expected = isinstance(expected, dict) and expected.get("additional_commitment") is not None
    multi_predicted = len(candidates) >= 2
    return {
        "id": row["id"],
        "text": row["text"],
        "expected_type": expected.get("type"),
        "predicted_type": candidate.type.value if candidate else None,
        "type_correct": type_correct,
        "contact_expected": contact_expected,
        "contact_predicted": contact_predicted,
        "expected_contact": expected_contact,
        "predicted_contact": {
            "value": predicted_value,
            "kind": candidate.contact_kind,
            "role": candidate.contact_role,
            "status": candidate.contact_status,
        } if candidate and predicted_value else None,
        "identity_exact": exact_identity,
        "identity_kind_exact": kind_exact,
        "identity_role_exact": role_exact,
        "identity_resolution_correct": identity_correct,
        "multi_expected": multi_expected,
        "multi_predicted": multi_predicted,
        "deadline_expected": bool(expected.get("has_deadline")),
        "deadline_predicted": bool(candidate and candidate.due_at),
        "candidate_count": len(candidates),
        "provider_error": result.provider_error,
        "latency_ms": round(latency_ms, 2),
    }


async def run() -> dict[str, object]:
    settings = Settings()
    provider = OllamaProvider(settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model)
    report: dict[str, object] = {
        "dataset": str(DATASET),
        "dataset_version": "commitments-heldout-v1",
        "authoring": "manual labels independent of evaluated model output",
        "evaluation_now": EVAL_NOW.isoformat(),
        "configuration": {"model": settings.ollama_model, "timezone": settings.default_timezone},
        "status": "unavailable",
    }
    if not await provider.available():
        report["missing"] = "Ollama server is not reachable"
        return report
    installed = await provider.list_models()
    if not _model_matches(settings.ollama_model, installed):
        report["missing"] = settings.ollama_model
        return report
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))["examples"]
    gateway = LLMGateway(provider)
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    for item in dataset:
        started = time.perf_counter()
        result = await gateway.extract_commitments(
            str(item["text"]), timezone_name=settings.default_timezone, now=EVAL_NOW, prompt_version="improved"
        )
        latency = (time.perf_counter() - started) * 1000
        latencies.append(latency)
        rows.append(_row(item, result, latency))
    contact_rows = [row for row in rows if row["contact_expected"]]
    identity_tp = sum(bool(row["identity_resolution_correct"]) for row in contact_rows)
    identity_exact = sum(bool(row["identity_exact"]) for row in contact_rows)
    identity_kind = sum(bool(row["identity_kind_exact"]) for row in contact_rows)
    identity_role = sum(bool(row["identity_role_exact"]) for row in contact_rows)
    negative_identity_correct = sum(not row["contact_predicted"] for row in rows if not row["contact_expected"])
    multi_rows = [row for row in rows if row["multi_expected"]]
    report.update(
        {
            "status": "complete",
            "dataset_size": len(rows),
            "type_accuracy": round(sum(bool(row["type_correct"]) for row in rows) / len(rows), 4),
            "contact_presence": {
                "precision": round(sum(row["contact_expected"] and row["contact_predicted"] for row in rows) / sum(bool(row["contact_predicted"]) for row in rows), 4) if any(row["contact_predicted"] for row in rows) else 0.0,
                "recall": round(sum(row["contact_expected"] and row["contact_predicted"] for row in rows) / sum(bool(row["contact_expected"]) for row in rows), 4),
            },
            "contact_identity": {
                "exact_value_accuracy_on_contact_rows": round(identity_exact / len(contact_rows), 4) if contact_rows else 0.0,
                "kind_accuracy_on_contact_rows": round(identity_kind / len(contact_rows), 4) if contact_rows else 0.0,
                "role_accuracy_on_contact_rows": round(identity_role / len(contact_rows), 4) if contact_rows else 0.0,
                "resolution_accuracy_on_contact_rows": round(identity_tp / len(contact_rows), 4) if contact_rows else 0.0,
                "negative_no_contact_accuracy": round(negative_identity_correct / sum(not row["contact_expected"] for row in rows), 4),
                "definition": "Exact manually labelled value plus resolved/unresolved status; not inferred gold data.",
            },
            "multi_commitment_accuracy": round(sum(row["multi_predicted"] for row in multi_rows) / len(multi_rows), 4) if multi_rows else None,
            "deadline_presence_accuracy": round(sum(row["deadline_expected"] == row["deadline_predicted"] for row in rows) / len(rows), 4),
            "latency_ms_mean": round(statistics.mean(latencies), 2),
            "latency_ms_p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2),
        }
    )
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "heldout-identity-rows.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    (REPORTS / "heldout-identity.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), indent=2))
