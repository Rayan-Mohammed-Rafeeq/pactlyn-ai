"""Create the independently authored multi-hop RAG benchmark for 0.8."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

DESTINATION = Path(__file__).parent / "datasets" / "rag-0.8.json"

SOURCES = [
    {"id": "r08-rahul-proposal", "source_type": "commitment", "content": "Rahul promised to send the revised proposal after finance approves the budget, by Friday."},
    {"id": "r08-rahul-budget", "source_type": "email", "content": "From Rahul: finance approved the budget; I will send the revised proposal by Friday."},
    {"id": "r08-review", "source_type": "commitment", "content": "After receiving Rahul's proposal, I will review it and forward it to the placement team."},
    {"id": "r08-placement", "source_type": "email", "content": "The placement team has not acknowledged the proposal yet."},
    {"id": "r08-followup", "source_type": "commitment", "content": "If the placement team does not acknowledge the proposal, I will follow up on Monday."},
    {"id": "r08-professor", "source_type": "commitment", "content": "Professor Mehta must approve the design before I submit the final report."},
    {"id": "r08-report", "source_type": "commitment", "content": "The final report is ready to submit once Professor Mehta approves the design."},
    {"id": "r08-office", "source_type": "contact_note", "content": "The research office receives the final report after submission."},
    {"id": "r08-hr-outbound", "source_type": "email", "content": "I emailed HR asking for the interview schedule on Monday."},
    {"id": "r08-hr-reply", "source_type": "email", "content": "From HR: the interview schedule will be sent tomorrow; no schedule has been attached yet."},
    {"id": "r08-hr-followup", "source_type": "commitment", "content": "I will contact HR next Friday if the interview schedule remains missing."},
    {"id": "r08-history", "source_type": "email", "content": "Rahul sent the proposal yesterday and I forwarded it to the team today."},
    {"id": "r08-correction-old", "source_type": "commitment", "content": "The old commitment to call Rahul about the proposal was cancelled."},
    {"id": "r08-correction-new", "source_type": "commitment", "content": "The replacement commitment is to email Rahul about the proposal on Monday."},
    {"id": "r08-unrelated", "source_type": "commitment", "content": "Renew the gym membership in December; it is unrelated to the research report."},
    {"id": "r08-approval", "source_type": "email", "content": "Professor Mehta confirmed approval of the design on Tuesday."},
    {"id": "r08-team", "source_type": "contact_note", "content": "The project team is the recipient for the forwarded proposal."},
    {"id": "r08-no-bank", "source_type": "memory", "content": "There is no local record about contacting the bank regarding a mortgage."},
]

SPECS = [
    ("waiting_action", "What am I waiting for from Rahul, and what should I do if he does not respond?", ["r08-rahul-proposal", "r08-rahul-budget", "r08-followup"], "Wait for Rahul's proposal and follow up Monday if it does not arrive.", True),
    ("approval_chain", "Which report submission depends on Professor Mehta's approval?", ["r08-professor", "r08-report", "r08-office"], "The final report submission depends on Professor Mehta approving the design.", True),
    ("hr_status", "Has HR replied to my message about the interview schedule, and what remains to do?", ["r08-hr-outbound", "r08-hr-reply", "r08-hr-followup"], "HR replied that the schedule will be sent, and the follow-up remains conditional if it is still missing.", True),
    ("actionable_proposal", "What became actionable after receiving Rahul's proposal?", ["r08-rahul-proposal", "r08-rahul-budget", "r08-review", "r08-team"], "Review the proposal and forward it to the team.", True),
    ("historical", "What happened with Rahul's proposal yesterday and today?", ["r08-history", "r08-team"], "Rahul sent it yesterday and it was forwarded today.", True),
    ("supersession", "Which Rahul follow-up is current after the correction?", ["r08-correction-old", "r08-correction-new"], "The current commitment is to email Rahul Monday; the call commitment was cancelled.", True),
    ("unrelated", "Which responsibility is unrelated to the research report?", ["r08-unrelated", "r08-professor"], "Renewing the gym membership is unrelated.", True),
    ("approval_state", "Has the design approval arrived, and what can happen next?", ["r08-approval", "r08-report", "r08-office"], "Professor Mehta approved the design, so the final report can be submitted and then sent to the research office.", True),
    ("no_answer", "Did I contact the bank about the mortgage?", [], "There is not enough local evidence to determine that.", False),
    ("no_answer_other", "What did Maya promise about the conference venue?", [], "There is not enough local evidence to determine that.", False),
]


def build() -> dict[str, object]:
    queries: list[dict[str, object]] = []
    wrappers = ["{q}", "From the local records, {q}", "Which commitments and messages answer this: {q}", "What evidence supports this question: {q}", "Can you connect the records for this: {q}", "Please answer only from local evidence: {q}"]
    number = 1
    for category, query, relevant, answer, answerable in SPECS:
        for wrapper in wrappers:
            queries.append({"id": f"rag-0.8-{number:03d}", "category": category, "query": wrapper.format(q=query), "relevant": relevant, "answer": answer, "answerable": answerable, "multi_hop": len(relevant) >= 2})
            number += 1
    return {"dataset_version": "rag-0.8-v1", "authoring": "independently authored source records, multi-hop answers, relevance labels, and no-answer labels; no model predictions used", "sources": SOURCES, "queries": queries}


if __name__ == "__main__":
    payload = build()
    DESTINATION.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(DESTINATION), "queries": len(cast(list[object], payload["queries"])), "sha256": hashlib.sha256(DESTINATION.read_bytes()).hexdigest()}, indent=2))
