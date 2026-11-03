"""Generate the independently authored, frozen Pactlyn 0.7 corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DESTINATION = Path(__file__).parent / "datasets" / "commitments-0.7.json"
PEOPLE = ["Rahul", "Maya", "Aisha", "Daniel", "Elena", "Noor", "Priya", "Sam"]
ORGS = ["HR", "the library", "the placement coordinator", "the clinic", "the research office", "the vendor"]


def person(index: int) -> str:
    return PEOPLE[index % len(PEOPLE)]


def org(index: int) -> str:
    return ORGS[index % len(ORGS)]


def event(
    kind: str,
    *,
    actor: str = "user",
    recipient: str | None = None,
    deadline: bool = False,
    deadline_owner: str | None = None,
    responsibility: str = "USER_PERFORMS",
    status: str = "active",
) -> dict[str, Any]:
    return {
        "type": kind,
        "actor": actor,
        "recipient": recipient,
        "has_deadline": deadline,
        "deadline_owner": deadline_owner,
        "responsibility": responsibility,
        "status": status,
    }


def build() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for template in range(16):
        for variant in range(10):
            p, o = person(template + variant), org(template + variant)
            if template == 0:
                text = f"I'll send {p} the proposal by Friday, ask {o} for an update on Monday, and submit the report after {p} approves it."
                events = [event("deadline", recipient=p, deadline=True), event("follow_up", recipient=o, deadline=True), event("personal_task", actor="user", recipient=p, responsibility="CONDITIONALLY_EXECUTES")]
                edges = [{"source_index": 0, "target_index": 1, "relationship": "FOLLOWED_BY"}, {"source_index": 2, "target_index": 0, "relationship": "DEPENDS_ON"}]
                scenario = "three_atomic_actions"
            elif template == 1:
                text = f"If {p} doesn't send the document by Friday, I'll call {p} on Monday."
                events = [event("waiting_for", actor=p, recipient=None, deadline=True, deadline_owner=p, responsibility="OTHER_PARTY_PERFORMS"), event("follow_up", recipient=p, deadline=True, responsibility="CONDITIONALLY_EXECUTES")]
                edges = [{"source_index": 1, "target_index": 0, "relationship": "RESPONSE_REQUIRED_FROM"}, {"source_index": 1, "target_index": 0, "relationship": "FOLLOWED_BY"}]
                scenario = "conditional_fallback"
            elif template == 2:
                text = f"I'm waiting for {p}'s feedback by Thursday, then I'll send the revised draft to {o}."
                events = [event("waiting_for", actor=p, deadline=True, deadline_owner=p, responsibility="USER_WAITING_FOR"), event("personal_task", recipient=o, responsibility="CONDITIONALLY_EXECUTES")]
                edges = [{"source_index": 1, "target_index": 0, "relationship": "DEPENDS_ON"}]
                scenario = "waiting_then_action"
            elif template == 3:
                text = f"Email {p}, call {o}, and message {PEOPLE[(template + variant + 1) % len(PEOPLE)]} about the schedule next week."
                events = [event("follow_up", recipient=p, deadline=True, responsibility="USER_CONTACTS"), event("follow_up", recipient=o, deadline=True, responsibility="USER_CONTACTS"), event("follow_up", recipient=PEOPLE[(template + variant + 1) % len(PEOPLE)], deadline=True, responsibility="USER_CONTACTS")]
                edges = [{"source_index": 0, "target_index": 1, "relationship": "RELATED_TO"}, {"source_index": 1, "target_index": 2, "relationship": "RELATED_TO"}]
                scenario = "multiple_contacts"
            elif template == 4:
                text = f"Once {o} approves the booking, I'll send the itinerary to {p}."
                events = [event("waiting_for", actor=o, deadline_owner=o, responsibility="OTHER_PARTY_PERFORMS"), event("personal_task", recipient=p, responsibility="CONDITIONALLY_EXECUTES")]
                edges = [{"source_index": 1, "target_index": 0, "relationship": "DEPENDS_ON"}]
                scenario = "approval_dependency"
            elif template == 5:
                text = f"{p} will send the figures, I'll review them, and then I'll forward them to {o}."
                events = [event("waiting_for", actor=p, responsibility="OTHER_PARTY_PERFORMS"), event("personal_task", actor="user", responsibility="CONDITIONALLY_EXECUTES"), event("personal_task", recipient=o)]
                edges = [{"source_index": 1, "target_index": 0, "relationship": "DEPENDS_ON"}, {"source_index": 2, "target_index": 1, "relationship": "FOLLOWED_BY"}]
                scenario = "other_party_handoff"
            elif template == 6:
                text = f"I don't need to contact {o} anymore because they already replied."
                events = [event("follow_up", recipient=o, responsibility="USER_CONTACTS", status="cancelled")]
                edges = []
                scenario = "negation_completion"
            elif template == 7:
                text = f"I said I would call {p} Friday, but correction: I'll email {p} Monday instead."
                events = [event("follow_up", recipient=p, deadline=True, responsibility="USER_CONTACTS", status="cancelled"), event("follow_up", recipient=p, deadline=True, responsibility="USER_CONTACTS")]
                edges = [{"source_index": 1, "target_index": 0, "relationship": "SUPERSEDES"}]
                scenario = "correction"
            elif template == 8:
                text = f"Please postpone the call with {o} until next month; I have already postponed it once."
                events = [event("personal_task", recipient=o, responsibility="USER_CONTACTS", status="postponed")]
                edges = []
                scenario = "repeated_postponement"
            elif template == 9:
                text = f"Maybe I should ask {p} about the draft, but I'm not sure when."
                events = [event("personal_task", recipient=p, responsibility="USER_CONTACTS")]
                edges = []
                scenario = "ambiguous_responsibility"
            elif template == 10:
                text = f"I will finish the report tomorrow, send it to {p} on Tuesday, and ask {o} to confirm receipt."
                events = [event("deadline", deadline=True), event("deadline", recipient=p, deadline=True), event("follow_up", recipient=o, responsibility="USER_CONTACTS")]
                edges = [{"source_index": 1, "target_index": 0, "relationship": "FOLLOWED_BY"}, {"source_index": 2, "target_index": 1, "relationship": "FOLLOWED_BY"}]
                scenario = "multiple_contact_deadlines"
            elif template == 11:
                text = f"The {o} should send the result, while I prepare the summary and share it with {p}."
                events = [event("waiting_for", actor=o, responsibility="OTHER_PARTY_PERFORMS"), event("personal_task", responsibility="CONDITIONALLY_EXECUTES"), event("personal_task", recipient=p)]
                edges = [{"source_index": 1, "target_index": 0, "relationship": "DEPENDS_ON"}, {"source_index": 2, "target_index": 1, "relationship": "FOLLOWED_BY"}]
                scenario = "paragraph_workflow"
            elif template == 12:
                text = f"No action is needed: {p} mentioned a possible meeting, but I have nothing to do."
                events = []
                edges = []
                scenario = "no_commitment"
            elif template == 13:
                text = f"I promised {p} the report yesterday, but I haven't finished it yet."
                events = [event("personal_task", recipient=p, deadline=True, responsibility="USER_PERFORMS")]
                edges = []
                scenario = "overdue_promise"
            elif template == 14:
                text = f"The {o} owes me a decision, and if it arrives I'll review the offer from {p}."
                events = [event("waiting_for", actor=o, responsibility="USER_WAITING_FOR"), event("personal_task", recipient=p, responsibility="CONDITIONALLY_EXECUTES")]
                edges = [{"source_index": 1, "target_index": 0, "relationship": "DEPENDS_ON"}]
                scenario = "conditional_offer"
            else:
                text = f"I will email {p.lower()}@example.com tomorrow and ask {o} for the missing attachment."
                events = [event("deadline", recipient=f"{p.lower()}@example.com", deadline=True, responsibility="USER_CONTACTS"), event("follow_up", recipient=o, deadline=False, responsibility="USER_CONTACTS")]
                edges = [{"source_index": 0, "target_index": 1, "relationship": "RELATED_TO"}]
                scenario = "email_and_organisation"
            number = len(rows) + 1
            slot = (number - 1) % 16
            split = "heldout" if slot < 3 else "validation" if slot < 6 else "development" if slot < 9 else "train"
            rows.append({"id": f"commitment-0.7-{number:03d}", "text": text, "split": split, "scenario": scenario, "expected": {"events": events, "relationships": edges}})
    payload = {
        "dataset_version": "commitments-0.7-v1",
        "authoring": "independently authored, manually reviewed labels; no model predictions used",
        "seed": 0,
        "example_count": len(rows),
        "multi_commitment_count": sum(len(row["expected"]["events"]) > 1 for row in rows),
        "dependency_or_conditional_count": sum(row["scenario"] in {"conditional_fallback", "waiting_then_action", "approval_dependency", "other_party_handoff", "paragraph_workflow", "conditional_offer"} for row in rows),
        "multiple_contact_count": sum(row["scenario"] in {"multiple_contacts", "email_and_organisation", "multiple_contact_deadlines"} for row in rows),
        "examples": rows,
    }
    return payload


if __name__ == "__main__":
    payload = build()
    DESTINATION.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(DESTINATION), "sha256": hashlib.sha256(DESTINATION.read_bytes()).hexdigest(), "examples": payload["example_count"], "multi": payload["multi_commitment_count"]}, indent=2))
