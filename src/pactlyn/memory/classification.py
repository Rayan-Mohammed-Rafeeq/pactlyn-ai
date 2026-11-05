"""Input classification: determine what kind of information the user provided.

This stage runs BEFORE extraction so that personal facts are never forced
into the Commitment model.  Classification is deterministic and fast; it does
not require an LLM call.

Supported classes
-----------------
PERSONAL_FACT   – a stable fact about the user (birthday, name, preference …)
COMMITMENT      – a task / deadline / follow-up the user explicitly stated
WAITING_FOR     – the user is waiting for another person / organisation to act
FOLLOW_UP       – the user will contact someone later
EVENT           – an upcoming appointment or meeting (not a user obligation)
GENERAL_NOTE    – information that does not fit any other class
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class InputClass(StrEnum):
    PERSONAL_FACT = "personal_fact"
    COMMITMENT = "commitment"
    WAITING_FOR = "waiting_for"
    FOLLOW_UP = "follow_up"
    EVENT = "event"
    GENERAL_NOTE = "general_note"


class PersonalFactHint(StrEnum):
    """Narrower hint used to pre-populate category/attribute fields."""
    BIRTHDAY = "birthday"
    NAME = "name"
    EDUCATION = "education"
    CAREER = "career"
    PREFERENCE = "preference"
    CONTACT_INFORMATION = "contact_information"
    PERSONAL_RELATIONSHIP = "personal_relationship"
    IDENTITY = "identity"
    OTHER = "other"


@dataclass(frozen=True)
class ClassificationResult:
    classes: tuple[InputClass, ...]     # ordered, highest-confidence first
    fact_hints: tuple[PersonalFactHint, ...]  # non-empty only when PERSONAL_FACT present
    raw_text: str

    @property
    def primary(self) -> InputClass:
        return self.classes[0] if self.classes else InputClass.GENERAL_NOTE

    @property
    def has_personal_fact(self) -> bool:
        return InputClass.PERSONAL_FACT in self.classes

    @property
    def has_commitment(self) -> bool:
        return any(
            c in self.classes
            for c in (
                InputClass.COMMITMENT,
                InputClass.WAITING_FOR,
                InputClass.FOLLOW_UP,
            )
        )


# ---------------------------------------------------------------------------
# Pattern tables
# ---------------------------------------------------------------------------

# Each tuple: (compiled regex, InputClass, optional PersonalFactHint)
_PERSONAL_FACT_PATTERNS: list[tuple[re.Pattern[str], PersonalFactHint]] = [
    # Birthday
    (re.compile(
        r"\b(?:my\s+)?birthday\b|"
        r"\b(?:I\s+was\s+born|born\s+on|date\s+of\s+birth|dob)\b|"
        r"\b(?:is\s+my\s+birthday|my\s+birth(?:day|date))\b",
        re.IGNORECASE,
    ), PersonalFactHint.BIRTHDAY),

    # Full name / identity
    (re.compile(
        r"\b(?:my\s+(?:full\s+)?name\s+is|I\s+(?:am|go\s+by)\s+called|my\s+name\s*[=:])\b",
        re.IGNORECASE,
    ), PersonalFactHint.NAME),

    # Education
    (re.compile(
        r"\b(?:I\s+(?:study|studied|am\s+studying|attend|enrolled(?:\s+at)?)|"
        r"my\s+(?:university|college|course|degree|major|programme|school)\s+is|"
        r"I\s+(?:go\s+to|am\s+at)\s+\w+\s+(?:university|college|institute|school))\b",
        re.IGNORECASE,
    ), PersonalFactHint.EDUCATION),

    # Career / job
    (re.compile(
        r"\b(?:I\s+(?:work\s+at|work\s+for|am\s+(?:a|an)\s+\w+\s+at)|"
        r"my\s+(?:job|role|position|company|employer|current\s+project)\s+is)\b",
        re.IGNORECASE,
    ), PersonalFactHint.CAREER),

    # Email / communication preference
    (re.compile(
        r"\b(?:I\s+prefer|my\s+preference\s+is|I\s+like)\s+(?:\w+\s+){0,3}(?:emails?|tone|communication|messages?)\b|"
        r"\b(?:my\s+(?:email\s+)?(?:style|tone|preference)\s+is)\b",
        re.IGNORECASE,
    ), PersonalFactHint.PREFERENCE),

    # Contact info – email address
    (re.compile(
        r"\bmy\s+(?:email\s+address|email)\s+is\s+[\w.+-]+@[\w-]+\.[a-z]{2,}\b",
        re.IGNORECASE,
    ), PersonalFactHint.CONTACT_INFORMATION),

    # Contact info – phone
    (re.compile(
        r"\bmy\s+(?:phone|mobile|cell|number)\s+(?:number\s+)?is\b",
        re.IGNORECASE,
    ), PersonalFactHint.CONTACT_INFORMATION),

    # Generic "my X is Y" ownership statements – catch-all for identity facts
    # Explicitly exclude event/appointment words to avoid mis-classifying them.
    (re.compile(
        r"\bmy\s+(?!commitment|task|goal|plan|deadline|meeting|appointment|event|reminder|"
        r"interview|exam|class|lecture|session|seminar|conference|presentation)"
        r"[a-z][a-z\s]{1,40}\s+is\b",
        re.IGNORECASE,
    ), PersonalFactHint.IDENTITY),
]

_COMMITMENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(?:I\s+(?:need|have)\s+to|I\s+(?:must|should|will|shall)|"
        r"I(?:'ll| will)\s+(?!am\b|be\b)|"
        r"(?:remind|reminder|don't\s+forget|must(?:n't)?|submit|deliver|complete|finish))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bby\s+(?:friday|monday|tuesday|wednesday|thursday|saturday|sunday|"
        r"tomorrow|today|next\s+\w+|\d{1,2}(?:/|-)\d{1,2}|\d{4}-\d{2}-\d{2})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bdeadline\b", re.IGNORECASE),
]

_WAITING_FOR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(?:wait(?:ing)?\s+for|expecting|owed\s+(?:by|from)|owes\s+me|"
        r"reply\s+from|response\s+from|pending\s+(?:from|on))\b",
        re.IGNORECASE,
    ),
]

_FOLLOW_UP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(?:follow(?:\s+|-)?up\s+with|check\s+with|need\s+to\s+contact|"
        r"circle\s+back|get\s+back\s+to)\b",
        re.IGNORECASE,
    ),
]

_EVENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(?:my\s+)?(?:interview|meeting|appointment|exam|presentation|"
        r"seminar|conference|lecture|class|session|webinar)\s+is\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:i\s+have\s+a|there\s+is\s+a)\s+(?:meeting|appointment|interview|"
        r"class|exam|lecture|session|seminar|conference)\b",
        re.IGNORECASE,
    ),
]

# Strong birthday-is-a-personal-fact overrides
_BIRTHDAY_OVERRIDE = re.compile(
    r"\b(?:\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2})\s+is\s+my\s+birthday\b|"
    r"\bmy\s+birthday\s+is\s+(?:on\s+)?(?:\d{1,2}|\w+)",
    re.IGNORECASE,
)


class InputClassifier:
    """Deterministic, pattern-based input classifier.

    Multi-class output is supported: one sentence can contain both a personal
    fact ("I prefer concise emails") and a commitment ("I need to reply by
    Friday").  When both are detected, both classes are returned and both
    extraction paths will run.
    """

    def classify(self, text: str) -> ClassificationResult:
        cleaned = text.strip()
        if not cleaned:
            return ClassificationResult(
                classes=(InputClass.GENERAL_NOTE,),
                fact_hints=(),
                raw_text=cleaned,
            )

        classes: list[InputClass] = []
        fact_hints: list[PersonalFactHint] = []

        # ---- personal fact detection ----
        # Hard override: anything that explicitly says "X is my birthday"
        # must become a personal fact, never a commitment, regardless of dates.
        if _BIRTHDAY_OVERRIDE.search(cleaned):
            if InputClass.PERSONAL_FACT not in classes:
                classes.insert(0, InputClass.PERSONAL_FACT)
            if PersonalFactHint.BIRTHDAY not in fact_hints:
                fact_hints.insert(0, PersonalFactHint.BIRTHDAY)

        for pattern, hint in _PERSONAL_FACT_PATTERNS:
            if pattern.search(cleaned):
                if InputClass.PERSONAL_FACT not in classes:
                    classes.append(InputClass.PERSONAL_FACT)
                if hint not in fact_hints:
                    fact_hints.append(hint)

        # ---- waiting-for ----
        if any(p.search(cleaned) for p in _WAITING_FOR_PATTERNS):
            classes.append(InputClass.WAITING_FOR)

        # ---- follow-up ----
        if any(p.search(cleaned) for p in _FOLLOW_UP_PATTERNS):
            classes.append(InputClass.FOLLOW_UP)

        # ---- event ----
        if any(p.search(cleaned) for p in _EVENT_PATTERNS):
            # Events only when not already a personal fact
            if InputClass.PERSONAL_FACT not in classes:
                classes.append(InputClass.EVENT)

        # ---- commitment ----
        if any(p.search(cleaned) for p in _COMMITMENT_PATTERNS):
            # Birthday + a date phrase must NOT become a commitment.
            if PersonalFactHint.BIRTHDAY not in fact_hints:
                classes.append(InputClass.COMMITMENT)

        # ---- fallback ----
        if not classes:
            classes.append(InputClass.GENERAL_NOTE)

        return ClassificationResult(
            classes=tuple(classes),
            fact_hints=tuple(fact_hints),
            raw_text=cleaned,
        )
