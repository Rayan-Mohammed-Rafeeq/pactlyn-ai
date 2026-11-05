"""Score answerability decisions from the mixed 0.8 RAG run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPORT = Path(__file__).parent / "reports" / "answerability-0.8.json"
MULTIHOP = Path(__file__).parent / "reports" / "multihop-rag-0.8.json"


def main() -> None:
    report = json.loads(MULTIHOP.read_text(encoding="utf-8"))
    rows = report.get("real_ollama", {}).get("rows", [])
    if not rows:
        rows = report.get("rows", [])
    evaluated: list[dict[str, Any]] = []
    for row in rows:
        true_abstain = not row["answerable"]
        predicted_abstain = not row["evidence_complete"]
        evaluated.append({**row, "true_abstain": true_abstain, "predicted_abstain": predicted_abstain})
    tp = sum(row["true_abstain"] and row["predicted_abstain"] for row in evaluated)
    fp = sum(not row["true_abstain"] and row["predicted_abstain"] for row in evaluated)
    fn = sum(row["true_abstain"] and not row["predicted_abstain"] for row in evaluated)
    answerable = [row for row in evaluated if row["answerable"]]
    evaluated_answers = [row for row in answerable if row.get("answer_evaluated")]
    citations = [row for row in answerable if row["citations"]]
    citation_hits = sum(set(row["citations"]) <= set(row["ids"]) for row in citations)
    payload = {
        "dataset_version": "rag-0.8-v1",
        "source_report": str(MULTIHOP),
        "sample_denominator": len(evaluated),
        "answerable_denominator": len(answerable),
        "unanswerable_denominator": len(evaluated) - len(answerable),
        "answer_accuracy": {"correct": sum(row["answer_correct_proxy"] for row in evaluated_answers), "denominator": len(evaluated_answers), "accuracy": round(sum(row["answer_correct_proxy"] for row in evaluated_answers) / max(len(evaluated_answers), 1), 4) if evaluated_answers else None},
        "groundedness": {"grounded_answers": sum(row["answer_correct_proxy"] and row["citation_correct"] for row in evaluated_answers), "denominator": len(evaluated_answers), "rate": round(sum(row["answer_correct_proxy"] and row["citation_correct"] for row in evaluated_answers) / max(len(evaluated_answers), 1), 4) if evaluated_answers else None},
        "citation_precision": {"correct": citation_hits, "denominator": len(citations), "precision": round(citation_hits / max(len(citations), 1), 4) if citations else None},
        "citation_recall": {"covered_answerable": sum(row["citation_correct"] for row in evaluated_answers), "denominator": len(evaluated_answers), "recall": round(sum(row["citation_correct"] for row in evaluated_answers) / max(len(evaluated_answers), 1), 4) if evaluated_answers else None},
        "abstention_precision": {"correct": tp, "denominator": tp + fp, "precision": round(tp / max(tp + fp, 1), 4)},
        "abstention_recall": {"correct": tp, "denominator": tp + fn, "recall": round(tp / max(tp + fn, 1), 4)},
        "false_abstention_rate": {"false_abstentions": fp, "answerable_denominator": len(answerable), "rate": round(fp / max(len(answerable), 1), 4)},
        "unsupported_answer_rate": {"unsupported": sum(bool(row["answerable"]) and bool(row.get("answer_evaluated")) and not bool(row["predicted_abstain"]) and not bool(row["answer_correct_proxy"]) for row in evaluated), "answerable_denominator": len(evaluated_answers), "rate": round(sum(bool(row["answerable"]) and bool(row.get("answer_evaluated")) and not bool(row["predicted_abstain"]) and not bool(row["answer_correct_proxy"]) for row in evaluated) / max(len(evaluated_answers), 1), 4) if evaluated_answers else None},
        "answer_coverage_on_answerable": {"covered": sum(not row["predicted_abstain"] for row in answerable), "denominator": len(answerable), "rate": round(sum(not row["predicted_abstain"] for row in answerable) / max(len(answerable), 1), 4)},
        "failures": [row for row in evaluated if bool(row["true_abstain"]) != bool(row["predicted_abstain"]) or (bool(row["answerable"]) and bool(row.get("answer_evaluated")) and not bool(row["answer_correct_proxy"]))][:30],
    }
    REPORT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
