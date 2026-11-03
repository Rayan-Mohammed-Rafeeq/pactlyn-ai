from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pactlyn.app.configuration import Settings
from pactlyn.core.commitments import CommitmentExtractor
from pactlyn.llm.gateway import LLMGateway
from pactlyn.llm.providers.ollama import OllamaProvider

DATASET = Path(__file__).parent / "datasets" / "commitments.json"
REPORTS = Path(__file__).parent / "reports"
EVAL_NOW = datetime(2026, 11, 2, 10, tzinfo=UTC)


def _model_matches(requested: str, installed: list[str]) -> bool:
    """Ollama may return ``name:latest`` for a requested untagged model."""
    return requested in installed or f"{requested}:latest" in installed


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sorted(values)[max(0, int(len(values) * 0.95) - 1)], 2)


def _scores(rows: list[dict[str, Any]]) -> dict[str, object]:
    total = len(rows)
    if not total:
        return {}
    def accuracy(key: str) -> float:
        return round(sum(bool(row[key]) for row in rows) / total, 4)

    deadline_tp = sum(row["deadline_expected"] and row["deadline_predicted"] for row in rows)
    deadline_fp = sum(not row["deadline_expected"] and row["deadline_predicted"] for row in rows)
    deadline_fn = sum(row["deadline_expected"] and not row["deadline_predicted"] for row in rows)
    contact_tp = sum(row["contact_expected"] and row["contact_predicted"] for row in rows)
    contact_fp = sum(not row["contact_expected"] and row["contact_predicted"] for row in rows)
    contact_fn = sum(row["contact_expected"] and not row["contact_predicted"] for row in rows)

    def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}

    categories: dict[str, dict[str, float]] = {}
    for category in sorted({str(row["expected_type"]) for row in rows}):
        category_rows = [row for row in rows if row["expected_type"] == category]
        categories[category] = {
            "count": float(len(category_rows)),
            "type_accuracy": round(
                sum(row["type_correct"] for row in category_rows) / len(category_rows), 4
            ),
        }
    confusion: dict[str, dict[str, int]] = {}
    for row in rows:
        actual = str(row["expected_type"])
        predicted = str(row["predicted_type"] or "missing")
        confusion.setdefault(actual, {})[predicted] = confusion.setdefault(actual, {}).get(predicted, 0) + 1
    scenarios: dict[str, dict[str, int]] = {}
    for row in rows:
        scenario = row["scenario"]
        bucket = scenarios.setdefault(scenario, {"count": 0, "type_failures": 0, "deadline_failures": 0, "contact_failures": 0})
        bucket["count"] += 1
        bucket["type_failures"] += int(not row["type_correct"])
        bucket["deadline_failures"] += int(not row["deadline_presence_correct"])
        bucket["contact_failures"] += int(not row["contact_presence_correct"])
    return {
        "dataset_size": total,
        "type_accuracy": accuracy("type_correct"),
        "confirmation_accuracy": accuracy("confirmation_correct"),
        "deadline_presence_accuracy": accuracy("deadline_presence_correct"),
        "contact_presence_accuracy": accuracy("contact_presence_correct"),
        "deadline": prf(deadline_tp, deadline_fp, deadline_fn),
        "contact_presence": prf(contact_tp, contact_fp, contact_fn),
        "extraction_detection": {
            "precision": round(sum(row["has_prediction"] for row in rows) / total, 4),
            "recall": round(sum(row["has_prediction"] for row in rows) / total, 4),
            "f1": round(sum(row["has_prediction"] for row in rows) / total, 4),
            "definition": "The checked-in dataset labels one commitment per example but does not label a commitment count; this is prediction non-emptiness, not a multi-commitment score.",
        },
        "multi_commitment_accuracy": None,
        "categories": categories,
        "type_confusion_matrix": confusion,
        "scenario_failures": scenarios,
        "contact_value_evaluable": False,
        "contact_value_note": "The checked-in labels contain only has_contact; expected name, email, role, and organisation/person class are absent.",
    }


def _row_result(row: dict[str, Any], result: Any, latency_ms: float) -> dict[str, Any]:
    expected = row["expected"]
    candidate = result.candidates[0] if result.candidates else None
    predicted_type = candidate.type.value if candidate else None
    has_deadline = bool(candidate and candidate.due_at)
    has_contact = bool(candidate and (candidate.person or candidate.contact_email))
    expected_candidate = CommitmentExtractor().extract(str(row["text"]), now=EVAL_NOW).candidates[0]
    scenario = f"variant-{(int(str(row['id']).split('-')[-1]) - 1) % 10}"
    predicted_contacts = [
        {
            "value": item.person or item.contact_email,
            "email": item.contact_email,
            "kind": item.contact_kind,
            "role": item.contact_role,
            "status": item.contact_status,
        }
        for item in result.candidates
        if item.person or item.contact_email
    ]
    return {
        "id": row["id"],
        "text": row["text"],
        "expected_type": expected["type"],
        "predicted_type": predicted_type,
        "type_correct": predicted_type == expected["type"],
        "confirmation_expected": expected["requires_confirmation"],
        "confirmation_predicted": bool(candidate and candidate.needs_confirmation),
        "confirmation_correct": bool(candidate and candidate.needs_confirmation) == expected["requires_confirmation"],
        "deadline_expected": expected["has_deadline"],
        "deadline_predicted": has_deadline,
        "deadline_presence_correct": has_deadline == expected["has_deadline"],
        "contact_expected": expected["has_contact"],
        "contact_predicted": has_contact,
        "contact_presence_correct": has_contact == expected["has_contact"],
        "has_prediction": bool(result.candidates),
        "candidate_count": len(result.candidates),
        "predicted_due_at": candidate.due_at.isoformat() if candidate and candidate.due_at else None,
        "predicted_person": candidate.person if candidate else None,
        "predicted_contact_email": candidate.contact_email if candidate else None,
        "predicted_contact_kind": candidate.contact_kind if candidate else None,
        "predicted_contact_role": candidate.contact_role if candidate else None,
        "predicted_contacts": predicted_contacts,
        "expected_contact_value_inferred_from_source": expected_candidate.person,
        "expected_contact_kind_inferred_from_source": expected_candidate.contact_kind,
        "expected_contact_role_inferred_from_source": expected_candidate.contact_role,
        "expected_contact_value_source": "heuristic source parse; not a checked-in gold field",
        "expected_due_at_inferred_from_source": expected_candidate.due_at.isoformat() if expected_candidate.due_at else None,
        "deadline_error_class": _deadline_error(row, candidate, expected_candidate),
        "scenario": scenario,
        "explanation": result.explanation,
        "evidence": candidate.evidence if candidate else None,
        "provider_error": result.provider_error,
        "latency_ms": round(latency_ms, 2),
    }


def _deadline_error(row: dict[str, Any], candidate: Any, expected_candidate: Any) -> str:
    expected = bool(row["expected"]["has_deadline"])
    predicted = bool(candidate and candidate.due_at)
    if expected and not predicted:
        return "missing_date"
    if not expected and predicted:
        return "false_positive_date"
    if expected and predicted and expected_candidate.due_at:
        if candidate.due_at != expected_candidate.due_at:
            return "date_value_differs_from_deterministic_reference"
        return "none"
    return "none"


async def run() -> dict[str, object] | tuple[dict[str, object], list[dict[str, Any]]]:
    settings = Settings()
    provider = OllamaProvider(
        settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model
    )
    report: dict[str, object] = {
        "name": "ollama_capture_evaluation",
        "status": "unavailable",
        "evaluation_timestamp": datetime.now(UTC).isoformat(),
        "evaluation_now": EVAL_NOW.isoformat(),
        "configuration": {
            "ollama_url": settings.ollama_url,
            "llm_model": settings.ollama_model,
            "embedding_model": settings.ollama_embedding_model,
            "timezone": settings.default_timezone,
        },
    }
    if not await provider.available():
        report["missing"] = "Ollama server is not reachable"
        return report
    models = await provider.list_models()
    report["ollama_version"] = await provider.version()
    report["installed_models"] = models
    missing: list[str] = []
    if not _model_matches(settings.ollama_model, models):
        missing.append(settings.ollama_model)
    if not _model_matches(settings.ollama_embedding_model, models):
        missing.append(settings.ollama_embedding_model)
    if not _model_matches(settings.ollama_model, models):
        report["missing"] = missing
        return report
    if _model_matches(settings.ollama_embedding_model, models):
        vectors = await provider.embed(["Pactlyn local embedding dimension probe"])
        report["embedding_dimension"] = len(vectors[0])
        report["embedding_status"] = "available"
    else:
        report["embedding_dimension"] = None
        report["embedding_status"] = "unavailable"
        report["missing_embedding_model"] = settings.ollama_embedding_model
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    prompt_version = str(os.environ.get("PACTLYN_PROMPT_VERSION", "improved"))
    context_mode = str(os.environ.get("PACTLYN_CONTEXT_MODE", "none"))
    retrieved_context = ""
    if context_mode == "existing_contacts":
        # The evaluation process has no application contact records. Keep the experiment
        # explicit instead of leaking labels or treating source text as retrieved evidence.
        retrieved_context = "No matching existing contact record was retrieved."
    gateway = LLMGateway(provider)
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    for row in dataset:
        started = time.perf_counter()
        result = await gateway.extract_commitments(
            str(row["text"]),
            timezone_name=settings.default_timezone,
            now=EVAL_NOW,
            prompt_version=prompt_version,
            context=retrieved_context,
        )
        latency = (time.perf_counter() - started) * 1000
        latencies.append(latency)
        rows.append(_row_result(row, result, latency))
    report.update(_scores(rows))
    report["status"] = "complete"
    report["latency_ms_mean"] = round(statistics.mean(latencies), 2)
    report["latency_ms_median"] = round(statistics.median(latencies), 2)
    report["latency_ms_p95"] = _p95(latencies)
    report["empty_results"] = sum(not row["has_prediction"] for row in rows)
    report["prompt_version"] = prompt_version
    report["retrieved_context_mode"] = context_mode
    return report, rows


async def main() -> None:
    result = await run()
    rows: list[dict[str, Any]]
    if isinstance(result, tuple):
        report, rows = result
    else:
        rows = []
        report = result
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "ollama-extraction.json").write_text(json.dumps(report, indent=2) + "\n")
    (REPORTS / "ollama.json").write_text(json.dumps(report, indent=2) + "\n")
    errors = [
        row
        for row in rows
        if not (
            row["type_correct"]
            and row["confirmation_correct"]
            and row["deadline_presence_correct"]
            and row["contact_presence_correct"]
        )
    ]
    (REPORTS / "extraction-errors.json").write_text(json.dumps(errors, indent=2) + "\n")
    (REPORTS / "extraction-audit.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
