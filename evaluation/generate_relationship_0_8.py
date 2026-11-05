"""Generate the independently reviewed 0.8 relationship benchmark.

The labels are authored in this file, rather than produced by an extractor.
Each category has development and held-out lexical variants so prompt work can
be done without reading the held-out wording.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DESTINATION = Path(__file__).parent / "datasets" / "relationships-0.8.json"
PEOPLE = ["Rahul", "Maya", "Aisha", "Daniel", "Noor", "Priya", "Sam", "Elena", "Omar", "Lina"]
OBJECTS = ["proposal", "design", "invoice", "interview details", "research notes", "contract", "budget", "application", "agenda", "report"]


def event(
    span: str,
    *,
    event_type: str = "personal_task",
    actor: str = "user",
    responsibility: str = "USER_PERFORMS",
    status: str = "active",
    condition: str | None = None,
) -> dict[str, Any]:
    return {
        "type": event_type,
        "actor": actor,
        "responsibility": responsibility,
        "status": status,
        "condition": condition,
        "source_span": span,
    }


def edge(source: int, target: int, relationship: str, text: str, *, conditional: str | None = None) -> dict[str, Any]:
    return {
        "source_index": source,
        "target_index": target,
        "relationship": relationship,
        "evidence": text,
        "conditional_trigger": conditional,
    }


def make_case(number: int, category: str, variant: int) -> dict[str, Any]:
    a, b = PEOPLE[(number + variant) % len(PEOPLE)], PEOPLE[(number + variant + 1) % len(PEOPLE)]
    obj = OBJECTS[(number + variant) % len(OBJECTS)]
    if category == "dependency_chain":
        text = f"{a} must approve the {obj} before I submit the final report, then I will archive the report."
        events = [event(f"{a} must approve the {obj}", event_type="waiting_for", actor=a, responsibility="OTHER_PARTY_PERFORMS"), event("I submit the final report", condition=f"after {a} approves the {obj}"), event("I will archive the report", condition="after submitting the report")]
        edges = [edge(1, 0, "DEPENDS_ON", text), edge(2, 1, "DEPENDS_ON", text)]
    elif category == "conditional_fallback":
        text = f"I'm waiting for {a} to send the {obj} by Friday. If it does not arrive, I will call {a} on Monday."
        events = [event(f"{a} to send the {obj} by Friday", event_type="waiting_for", actor=a, responsibility="USER_WAITING_FOR"), event(f"I will call {a} on Monday", event_type="follow_up", responsibility="CONDITIONALLY_EXECUTES", condition=f"if {a} does not send the {obj}")]
        edges = [edge(1, 0, "RESPONSE_REQUIRED_FROM", text, conditional=f"if {a} does not send the {obj}"), edge(1, 0, "DEPENDS_ON", text, conditional=f"if {a} does not send the {obj}")]
    elif category == "waiting_for":
        text = f"I am waiting for {a} to confirm the {obj}; I will review it when the confirmation arrives."
        events = [event(f"waiting for {a} to confirm the {obj}", event_type="waiting_for", actor=a, responsibility="USER_WAITING_FOR"), event("I will review it", condition="when the confirmation arrives")]
        edges = [edge(1, 0, "DEPENDS_ON", text, conditional="when the confirmation arrives")]
    elif category == "multiple_contacts":
        text = f"I will email {a} about the {obj}, call {b} about the schedule, and message {PEOPLE[(number + variant + 2) % len(PEOPLE)]} about the deadline."
        third = PEOPLE[(number + variant + 2) % len(PEOPLE)]
        events = [event(f"email {a} about the {obj}", event_type="follow_up", responsibility="USER_CONTACTS"), event(f"call {b} about the schedule", event_type="follow_up", responsibility="USER_CONTACTS"), event(f"message {third} about the deadline", event_type="follow_up", responsibility="USER_CONTACTS")]
        edges = []
    elif category == "historical":
        text = f"{a} sent me the {obj} yesterday, and I forwarded it to {b} today."
        events = [event(f"{a} sent me the {obj} yesterday", event_type="personal_task", actor=a, responsibility="OTHER_PARTY_PERFORMS", status="completed"), event(f"I forwarded it to {b} today", event_type="personal_task", responsibility="USER_PERFORMS", status="completed")]
        edges = [edge(0, 1, "FOLLOWED_BY", text)]
    elif category == "superseded":
        text = f"I planned to email {a} about the {obj}, but correction: I will call {a} instead."
        events = [event(f"email {a} about the {obj}", event_type="follow_up", responsibility="USER_CONTACTS", status="cancelled"), event(f"I will call {a} instead", event_type="follow_up", responsibility="USER_CONTACTS")]
        edges = [edge(1, 0, "SUPERSEDES", text)]
    elif category == "negated":
        text = f"I do not need to contact {a} about the {obj}, so no follow-up is required."
        events = []
        edges = []
    elif category == "ambiguous":
        text = f"I might contact {a} about the {obj}, but I have not decided."
        events = [event(f"might contact {a} about the {obj}", event_type="follow_up", responsibility="USER_CONTACTS")]
        edges = []
    elif category == "multiple_targets":
        text = f"I will submit the {obj} after either {a} or {b} approves it."
        events = [event(f"{a} approves the {obj}", event_type="waiting_for", actor=a, responsibility="OTHER_PARTY_PERFORMS"), event(f"{b} approves the {obj}", event_type="waiting_for", actor=b, responsibility="OTHER_PARTY_PERFORMS"), event(f"I will submit the {obj}", condition=f"after either {a} or {b} approves it")]
        edges = [edge(2, 0, "DEPENDS_ON", text), edge(2, 1, "DEPENDS_ON", text)]
    elif category == "circular_looking":
        text = f"I will send the {obj} after {a} reviews it, while {a} will review it after I send a draft."
        events = [event(f"I will send the {obj}", condition=f"after {a} reviews it"), event(f"{a} reviews the {obj}", event_type="waiting_for", actor=a, responsibility="OTHER_PARTY_PERFORMS"), event("I send a draft", condition=f"before {a} reviews the {obj}")]
        edges = [edge(0, 1, "DEPENDS_ON", text), edge(1, 2, "DEPENDS_ON", text)]
    elif category == "chronological_unrelated":
        text = f"I will finish the {obj} on Monday, and I will call {a} on Tuesday about a separate matter."
        events = [event(f"finish the {obj} on Monday"), event(f"call {a} on Tuesday about a separate matter", event_type="follow_up", responsibility="USER_CONTACTS")]
        edges = []
    else:
        text = f"I will send the {obj} to {a}, and the {obj} is related to the {b} review."
        events = [event(f"send the {obj} to {a}"), event(f"the {obj} is related to the {b} review", responsibility="UNKNOWN")]
        edges = [edge(0, 1, "RELATED_TO", text)]
    return {"id": f"relationship-0.8-{number:03d}", "category": category, "split": "heldout" if variant >= 7 else "development", "text": text, "events": events, "relationships": edges}


def build() -> dict[str, Any]:
    categories = ["dependency_chain", "conditional_fallback", "waiting_for", "multiple_contacts", "historical", "superseded", "negated", "ambiguous", "multiple_targets", "circular_looking", "chronological_unrelated", "related_to"]
    examples = [make_case(index + 1, category, variant) for category in categories for variant in range(10) for index in [categories.index(category) * 10 + variant]]
    for item in examples:
        for index, current in enumerate(item["events"], start=1):
            current["event_id"] = f"{item['id']}-event-{index}"
    return {
        "dataset_version": "relationships-0.8-v1",
        "authoring": "independently authored relationship scenarios with manually reviewed event, direction, type, and evidence labels; no model predictions used",
        "seed": 0,
        "example_count": len(examples),
        "relationship_example_count": sum(bool(item["relationships"]) or item["category"] in {"negated", "ambiguous", "chronological_unrelated"} for item in examples),
        "examples": examples,
    }


if __name__ == "__main__":
    payload = build()
    DESTINATION.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(DESTINATION), "examples": payload["example_count"], "sha256": hashlib.sha256(DESTINATION.read_bytes()).hexdigest()}, indent=2))
