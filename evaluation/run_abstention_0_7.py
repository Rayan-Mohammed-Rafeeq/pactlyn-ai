"""Evaluate evidence sufficiency, safe abstention, and citation coverage."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

DATASET = Path(__file__).parent / "datasets" / "rag-0.7.json"
GROUNDING = Path(__file__).parent / "reports" / "grounding-0.7.json"
REPORT = Path(__file__).parent / "reports" / "abstention-0.7.json"

STOPWORDS = {
    "what", "when", "where", "which", "who", "whom", "have", "has", "did", "does", "the",
    "a", "an", "my", "me", "i", "is", "are", "to", "from", "for", "of", "and", "on", "in",
    "about", "already", "anyone", "else", "local", "record", "records", "support", "supports",
    "showing", "enough", "evidence", "commitment", "commitments", "email", "emails", "tell",
    "contact", "contacted",
}


def terms(value: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9_]+", value)
        if len(token) > 2 and token.casefold() not in STOPWORDS
    }


def evaluate_mode(rows: list[dict[str, Any]], sources: dict[str, str], mode: str) -> dict[str, Any]:
    evaluated: list[dict[str, Any]] = []
    for row in rows:
        retrieved = [str(identifier) for identifier in row["ids"]]
        relevant = {str(identifier) for identifier in row["relevant"]}
        evidence_text = " ".join(
            content
            for identifier in retrieved
            if not re.search(
                r"\b(?:no local record|no evidence|not recorded|does not state)\b",
                (content := sources.get(identifier, "")),
                re.IGNORECASE,
            )
        )
        anchor = bool(terms(row["query"]) & terms(evidence_text))
        sufficient = bool(relevant & set(retrieved))
        predicted_abstain = not anchor
        evaluated.append(
            {
                "id": row["id"],
                "answerable": row["answerable"],
                "evidence_sufficient": sufficient,
                "predicted_abstain": predicted_abstain,
                "citation_ids": sorted(relevant & set(retrieved)),
            }
        )
    no_answer = [row for row in evaluated if not row["answerable"]]
    answerable = [row for row in evaluated if row["answerable"]]
    unsafe = [row for row in answerable if not row["evidence_sufficient"] and not row["predicted_abstain"]]
    return {
        "mode": mode,
        "dataset_size": len(evaluated),
        "evidence_sufficiency_rate": round(sum(row["evidence_sufficient"] for row in answerable) / len(answerable), 4),
        "citation_coverage": round(sum(bool(row["citation_ids"]) for row in answerable) / len(answerable), 4),
        "safe_no_answer_abstention_rate": round(sum(row["predicted_abstain"] for row in no_answer) / len(no_answer), 4) if no_answer else 0.0,
        "unsupported_answer_rate": round(len(unsafe) / len(answerable), 4) if answerable else 0.0,
        "abstention_accuracy": round(sum(row["predicted_abstain"] == (not row["answerable"]) for row in evaluated) / len(evaluated), 4),
        "failures": [row for row in evaluated if (not row["answerable"]) != row["predicted_abstain"] or (row["answerable"] and not row["evidence_sufficient"] and not row["predicted_abstain"])],
    }


def main() -> None:
    dataset = cast(dict[str, Any], json.loads(DATASET.read_text(encoding="utf-8")))
    grounding = cast(dict[str, Any], json.loads(GROUNDING.read_text(encoding="utf-8")))
    sources = {
        str(source["id"]): str(source["content"])
        for source in cast(list[dict[str, Any]], dataset["sources"])
    }
    metrics = {
        mode: evaluate_mode(cast(dict[str, Any], grounding["deterministic"][mode])["rows"], sources, mode)
        for mode in ("dense", "fts5", "hybrid")
    }
    if isinstance(grounding.get("real_ollama"), dict):
        metrics.update(
            {
                f"real_ollama_{mode}": evaluate_mode(
                    cast(dict[str, Any], grounding["real_ollama"][mode])["rows"],
                    sources,
                    f"real_ollama_{mode}",
                )
                for mode in ("dense", "fts5", "hybrid")
            }
        )
    payload = {
        "dataset_version": dataset["dataset_version"],
        "method": "retrieved evidence is sufficient only when a manually labelled relevant source is present; citation coverage uses exact source IDs",
        "metrics": metrics,
    }
    REPORT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
