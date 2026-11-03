"""Create the frozen 0.6 corpus from manually authored, reviewed templates.

The labels in this file are written alongside each template. No model output is used
to create or revise them. Expansion varies names and dates only so the corpus remains
reproducible and auditable.
"""

# The nested template declarations are intentionally concise data fixtures.
# mypy: disable-error-code=no-untyped-def

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

DESTINATION = Path(__file__).parent / "datasets" / "commitments-0.6.json"
NAMES = ["Rahul", "Maya", "Aisha", "Daniel", "Elena", "Noor", "Priya", "Alex", "Sam", "Mei"]
ORGS = ["HR", "the library", "the clinic", "the research office", "the placement coordinator"]


def person(i: int) -> str:
    return NAMES[i % len(NAMES)]


def organisation(i: int) -> str:
    return ORGS[i % len(ORGS)]


def c(kind: str, *, deadline: bool = False, contact: str | None = None, contact_kind: str | None = None, role: str | None = None, status: str = "active") -> dict[str, Any]:
    return {
        "type": kind,
        "has_deadline": deadline,
        "contact": contact,
        "contact_kind": contact_kind,
        "contact_role": role,
        "status": status,
    }


Template = Callable[[int], tuple[str, list[dict[str, Any]], list[dict[str, Any]], str]]


def templates() -> list[Template]:
    def deadline(i: int):
        return f"I will send the proposal by Friday for {person(i)}.", [c("deadline", deadline=True, contact=person(i), contact_kind="person", role="recipient")], [], "single_deadline"

    def task(i: int):
        return f"I need to complete the assignment before the review meeting with {person(i)}.", [c("personal_task", deadline=True, contact=person(i), contact_kind="person", role="recipient")], [], "ambiguous_deadline"

    def waiting(i: int):
        return f"I am waiting for {person(i)} to approve the budget.", [c("waiting_for", contact=person(i), contact_kind="person", role="responsible")], [], "waiting_for"

    def follow(i: int):
        return f"Follow up with {organisation(i)} next Monday if they have not replied.", [c("follow_up", deadline=True, contact=organisation(i), contact_kind="organisation", role="recipient")], [], "follow_up"

    def promise(i: int):
        return f"I promised {person(i)} that I would share the notes, but I have not chosen a date.", [c("personal_task", contact=person(i), contact_kind="person", role="recipient")], [], "promise_without_date"

    def conditional(i: int):
        name = person(i)
        return f"If {name} does not send the figures by Friday, I will contact {name} on Monday.", [c("waiting_for", contact=name, contact_kind="person", role="responsible"), c("follow_up", deadline=True, contact=name, contact_kind="person", role="recipient")], [{"source_index": 0, "target_index": 1, "relationship": "FOLLOWED_BY"}, {"source_index": 1, "target_index": 0, "relationship": "RESPONSE_REQUIRED_FROM"}], "conditional_follow_up"

    def chain(i: int):
        name = person(i)
        return f"Send the proposal to {name} by Friday, ask {organisation(i)} for an update on Monday, and submit the final report once {name} approves it.", [c("deadline", deadline=True, contact=name, contact_kind="person", role="recipient"), c("follow_up", deadline=True, contact=organisation(i), contact_kind="organisation", role="recipient"), c("personal_task", contact=name, contact_kind="person", role="responsible")], [{"source_index": 0, "target_index": 1, "relationship": "FOLLOWED_BY"}, {"source_index": 2, "target_index": 0, "relationship": "DEPENDS_ON"}], "three_action_chain"

    def completion(i: int):
        return f"I already completed the renewal, so do not remind me to contact {organisation(i)}.", [c("personal_task", contact=organisation(i), contact_kind="organisation", role="recipient", status="completed")], [], "completed_negation"

    def postpone(i: int):
        return f"Please postpone the presentation with {person(i)} until next month.", [c("personal_task", contact=person(i), contact_kind="person", role="recipient", status="postponed")], [], "postponement"

    def two_tasks(i: int):
        return f"Complete my assignment tomorrow and email {person(i)} the application on Tuesday.", [c("deadline", deadline=True), c("deadline", deadline=True, contact=person(i), contact_kind="person", role="recipient")], [{"source_index": 0, "target_index": 1, "relationship": "FOLLOWED_BY"}], "two_deadlines"

    def response_then_task(i: int):
        return f"Once {organisation(i)} confirms the booking, I will send the itinerary to {person(i)}.", [c("waiting_for", contact=organisation(i), contact_kind="organisation", role="responsible"), c("personal_task", contact=person(i), contact_kind="person", role="recipient")], [{"source_index": 1, "target_index": 0, "relationship": "DEPENDS_ON"}], "approval_dependency"

    def review_share(i: int):
        return f"{person(i)} will send the documents, and I will review them before sharing them with {organisation(i)}.", [c("waiting_for", contact=person(i), contact_kind="person", role="responsible"), c("personal_task", contact=person(i), contact_kind="person", role="responsible"), c("personal_task", contact=organisation(i), contact_kind="organisation", role="recipient")], [{"source_index": 1, "target_index": 0, "relationship": "DEPENDS_ON"}, {"source_index": 2, "target_index": 1, "relationship": "DEPENDS_ON"}], "handoff_chain"

    def correction(i: int):
        return f"I said I would call {person(i)} Friday, but correction: I will email {person(i)} Monday instead.", [c("follow_up", deadline=True, contact=person(i), contact_kind="person", role="recipient", status="cancelled"), c("follow_up", deadline=True, contact=person(i), contact_kind="person", role="recipient")], [{"source_index": 1, "target_index": 0, "relationship": "SUPERSEDES"}], "correction"

    def repeat(i: int):
        return "Remind me to submit the form tomorrow. I also said earlier that I would submit the form tomorrow.", [c("deadline", deadline=True)], [], "duplicate_commitment"

    def multiple_contacts(i: int):
        return f"Ask {person(i)} for the figures and contact {organisation(i)} about the invoice next week.", [c("follow_up", deadline=True, contact=person(i), contact_kind="person", role="recipient"), c("follow_up", deadline=True, contact=organisation(i), contact_kind="organisation", role="recipient")], [{"source_index": 0, "target_index": 1, "relationship": "RELATED_TO"}], "multiple_contacts"

    def unrelated(i: int):
        return f"I will finish the report by Friday; separately, the weather may change and {person(i)} mentioned a concert.", [c("deadline", deadline=True)], [], "unrelated_activity"

    def contradiction(i: int):
        return f"I will send the contract tomorrow, actually do not send it because {organisation(i)} cancelled the request.", [c("personal_task", contact=organisation(i), contact_kind="organisation", role="recipient", status="cancelled")], [], "contradiction"

    def email(i: int):
        return f"Email {person(i).lower()}@example.com about the renewal tomorrow.", [c("deadline", deadline=True, contact=f"{person(i).lower()}@example.com", contact_kind="person", role="recipient")], [], "email_recipient"

    def no_action(i: int):
        return f"Someone mentioned that {organisation(i)} may hold an event, but I have no action to take.", [], [], "no_action"

    def waiting_chain(i: int):
        return f"I am waiting for {person(i)}'s feedback by Thursday. If they do not respond, I will call them on Friday.", [c("waiting_for", deadline=False, contact=person(i), contact_kind="person", role="responsible"), c("follow_up", deadline=True, contact=person(i), contact_kind="person", role="recipient")], [{"source_index": 0, "target_index": 1, "relationship": "FOLLOWED_BY"}, {"source_index": 1, "target_index": 0, "relationship": "RESPONSE_REQUIRED_FROM"}], "waiting_and_fallback"

    return [deadline, task, waiting, follow, promise, conditional, chain, completion, postpone, two_tasks, response_then_task, review_share, correction, repeat, multiple_contacts, unrelated, contradiction, email, no_action, waiting_chain]


def build() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for template_index, template in enumerate(templates()):
        for variant in range(11):
            text, commitments, relationships, scenario = template(variant + template_index)
            number = len(rows) + 1
            slot = (number - 1) % 22
            split = "heldout" if slot < 3 else "validation" if slot < 6 else "development" if slot < 10 else "train"
            rows.append({
                "id": f"commitment-0.6-{number:03d}",
                "text": text,
                "split": split,
                "scenario": scenario,
                "expected": {"commitments": commitments, "relationships": relationships},
            })
    payload = {
        "dataset_version": "commitments-0.6-v1",
        "authoring": "manually authored and template-reviewed labels; no model predictions used",
        "seed": 0,
        "example_count": len(rows),
        "multi_commitment_count": sum(len(row["expected"]["commitments"]) > 1 for row in rows),
        "examples": rows,
    }
    return payload


if __name__ == "__main__":
    payload = build()
    DESTINATION.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(DESTINATION.read_bytes()).hexdigest()
    print(json.dumps({"path": str(DESTINATION), "examples": payload["example_count"], "multi": payload["multi_commitment_count"], "sha256": digest}, indent=2))
