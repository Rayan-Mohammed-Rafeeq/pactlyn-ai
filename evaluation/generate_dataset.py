from __future__ import annotations

import json
from pathlib import Path


def build_dataset() -> list[dict[str, object]]:
    people = ["Rahul", "Maya", "the placement coordinator", "my professor", "the HR team", "Alex", "the landlord", "my project partner", "the clinic", "the library"]
    actions = ["send the proposal", "finish the assignment", "review the contract", "book an appointment", "submit the application", "call about the invoice", "share the notes", "prepare the presentation", "renew the membership", "reply to the message"]
    examples: list[dict[str, object]] = []
    for index in range(150):
        person = people[index % len(people)]
        action = actions[index % len(actions)]
        variant = index % 10
        if variant == 0:
            text = f"I will {action} by Friday."
            expected_type = "deadline"
        elif variant == 1:
            text = f"Remind me to {action} tomorrow."
            expected_type = "deadline"
        elif variant == 2:
            text = f"I'm waiting for {person} to confirm the next step."
            expected_type = "waiting_for"
        elif variant == 3:
            text = f"Follow up with {person} if they have not replied by Monday."
            expected_type = "follow_up"
        elif variant == 4:
            text = f"I promised {person} that I would {action}."
            expected_type = "personal_task"
        elif variant == 5:
            text = f"Please remember that {person} owes me an update next week."
            expected_type = "waiting_for"
        elif variant == 6:
            text = f"Can you help me postpone {action} until next month?"
            expected_type = "personal_task"
        elif variant == 7:
            text = f"I already completed {action}; do not remind me again."
            expected_type = "personal_task"
        elif variant == 8:
            text = f"Maybe I should {action}, but I'm not sure when."
            expected_type = "personal_task"
        else:
            text = f"{action.capitalize()} and ask {person} for context."
            expected_type = "personal_task"
        examples.append({"id": f"commitment-{index + 1:03d}", "text": text, "expected": {"type": expected_type, "requires_confirmation": variant in {2, 5, 8}, "has_deadline": variant in {0, 1, 3}}})
    return examples


if __name__ == "__main__":
    destination = Path(__file__).parent / "datasets" / "commitments.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(build_dataset(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(build_dataset())} examples to {destination}")
