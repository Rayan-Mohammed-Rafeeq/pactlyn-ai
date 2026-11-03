from __future__ import annotations

import builtins
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from dateutil import parser as date_parser
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pactlyn.storage.models import (
    Commitment,
    CommitmentEvent,
    CommitmentRelationship,
    CommitmentRelationshipType,
    CommitmentStatus,
    CommitmentType,
    Contact,
    Reminder,
)


class CommitmentCandidate(BaseModel):
    """Validated extraction output. It remains a candidate until confirmed."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    type: CommitmentType = CommitmentType.PERSONAL_TASK
    person: str | None = None
    contact_email: str | None = None
    contact_kind: Literal["person", "organisation", "unknown"] = "unknown"
    contact_role: Literal["recipient", "mentioned", "responsible", "unknown"] = "unknown"
    contact_status: Literal["resolved", "ambiguous", "unresolved"] = "unresolved"
    extraction_status: Literal["active", "completed", "postponed", "cancelled"] = "active"
    event_id: str | None = None
    source_span: str = ""
    actor: str | None = None
    object: str | None = None
    beneficiary: str | None = None
    deadline_owner: str | None = None
    condition: str | None = None
    responsibility: Literal[
        "USER_PERFORMS",
        "OTHER_PARTY_PERFORMS",
        "USER_WAITING_FOR",
        "USER_CONTACTS",
        "CONDITIONALLY_EXECUTES",
        "UNKNOWN",
    ] = "UNKNOWN"
    action: str | None = None
    expected_recipient: str | None = None
    reminder_preference: str | None = None
    dependency: str | None = None
    due_at: datetime | None = None
    timezone: str = "UTC"
    reminder_at: datetime | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    needs_confirmation: bool = True
    evidence: str = ""

    @field_validator("due_at", "reminder_at", mode="before")
    @classmethod
    def parse_dates(cls, value: Any) -> Any:
        if value in (None, "") or isinstance(value, datetime):
            return value
        return date_parser.parse(str(value))

    @model_validator(mode="after")
    def canonicalise_timestamps(self) -> CommitmentCandidate:
        try:
            zone = ZoneInfo(self.timezone)
        except KeyError:
            return self
        for field in ("due_at", "reminder_at"):
            value = getattr(self, field)
            if value is not None:
                if value.tzinfo is None:
                    value = value.replace(tzinfo=zone)
                setattr(self, field, value.astimezone(UTC))
        return self


class CommitmentRelationshipCandidate(BaseModel):
    """An edge between candidates in the same capture, addressed by zero-based indexes."""

    source_index: int = Field(ge=0)
    target_index: int = Field(ge=0)
    source_event_id: str | None = None
    target_event_id: str | None = None
    relationship: CommitmentRelationshipType
    evidence: str = ""
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class CaptureResult(BaseModel):
    candidates: list[CommitmentCandidate]
    relationships: list[CommitmentRelationshipCandidate] = Field(default_factory=list)
    explanation: str = ""
    used_local_model: bool = False
    used_fallback: bool = False
    provider_name: str | None = None
    provider_error: str | None = None
    relationship_warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_event_graph(self) -> CaptureResult:
        for index, candidate in enumerate(self.candidates):
            candidate.event_id = candidate.event_id or f"event-{index + 1}"
            candidate.source_span = candidate.source_span or candidate.evidence or candidate.description
        unique: list[CommitmentRelationshipCandidate] = []
        seen: set[tuple[int, int, CommitmentRelationshipType]] = set()
        for relation in self.relationships:
            if relation.source_index >= len(self.candidates) or relation.target_index >= len(self.candidates):
                self.relationship_warnings.append(
                    f"Relationship {relation.relationship.value} references a missing event"
                )
                continue
            if relation.source_index == relation.target_index:
                self.relationship_warnings.append(
                    f"Relationship {relation.relationship.value} cannot reference itself"
                )
                continue
            key = (relation.source_index, relation.target_index, relation.relationship)
            if key in seen:
                self.relationship_warnings.append(f"Duplicate relationship removed: {relation.relationship.value}")
                continue
            seen.add(key)
            relation.source_event_id = self.candidates[relation.source_index].event_id
            relation.target_event_id = self.candidates[relation.target_index].event_id
            unique.append(relation)
        self.relationships = unique
        return self


class CommitmentExtractor:
    """Small deterministic baseline used when Ollama is unavailable.

    The production path is ``OllamaGateway.extract_commitments``. This parser
    keeps capture useful during first-run setup and is deliberately conservative:
    uncertain dates and recipients remain confirmation-required.
    """

    _date_pattern = re.compile(
        r"\b(today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"next week|next month|next (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
        r"end of (?:this )?week|in (?:one|two|three|four|five|six|seven|\d+) days|"
        r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b",
        re.IGNORECASE,
    )
    _email_pattern = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
    _contact_patterns = (
        re.compile(r"\bwait(?:ing)? for\s+(?:the\s+)?(.+?)(?=\s+to\b|\s+that\b|\s+who\b|\s+reply\b|\s*$)", re.I),
        re.compile(r"\bfollow(?: |-)?up with\s+(.+?)(?=\s+if\b|\s+by\b|\s+on\b|\s+next\b|\s+(?:today|tomorrow)\b|\s*$)", re.I),
        re.compile(r"\bpromised\s+(.+?)(?=\s+that\b|\s+to\b|\s+i\s+would\b|\s*,\b|\s*$)", re.I),
        re.compile(r"\bremember that\s+(.+?)\s+owes\b", re.I),
        re.compile(r"\b([A-Za-z][A-Za-z .'-]{1,80})\s+owes me\b", re.I),
        re.compile(r"\bexpecting\s+(?:the\s+)?(.+?)(?=\s+to\b|\s*$)", re.I),
        re.compile(r"\bthe\s+([A-Za-z][A-Za-z .'-]{1,80})\s+(?:should|must|will)\b", re.I),
        re.compile(r"\bthe\s+([A-Za-z][A-Za-z .'-]{1,80})\s+(?:has not|hasn't|did not|didn't)\s+repl", re.I),
        re.compile(r"\bask\s+(.+?)\s+for\b", re.I),
        re.compile(r"\bask\s+(.+?)\s+to\b", re.I),
        re.compile(r"\bcall\s+(.+?)(?=\s+about\b|\s+after\b|\s+tomorrow\b|\s*$)", re.I),
        re.compile(r"\b(?:with|from|contact|email)\s+([A-Za-z][A-Za-z .'-]{1,80}?)(?=\s+for\b|\s+after\b|\s+before\b|\s+next\b|\s+on\b|\s+by\b|\s+(?:today|tomorrow)\b|\s*$)", re.I),
    )

    def extract(self, text: str, *, now: datetime | None = None, timezone_name: str = "UTC") -> CaptureResult:
        """Extract one or more commitments while preserving their source order."""
        special = self._extract_structured_multi(text, now=now, timezone_name=timezone_name)
        if special is not None:
            return special
        segments = self._split_commitments(text)
        if len(segments) <= 1:
            return self._extract_single(text, now=now, timezone_name=timezone_name)
        results = [self._extract_single(segment, now=now, timezone_name=timezone_name) for segment in segments]
        candidates = [item.candidates[0] for item in results if item.candidates]
        relationships: list[CommitmentRelationshipCandidate] = []
        for index in range(len(candidates) - 1):
            relationships.append(
                CommitmentRelationshipCandidate(
                    source_index=index,
                    target_index=index + 1,
                    relationship=CommitmentRelationshipType.FOLLOWED_BY,
                    evidence=segments[index + 1],
                    confidence=0.65,
                )
            )
        return CaptureResult(
            candidates=candidates,
            relationships=relationships,
            explanation="Deterministic extraction of multiple source actions; confirmation is required for uncertain fields",
        )

    @staticmethod
    def _extract_structured_multi(
        source: str,
        *,
        now: datetime | None,
        timezone_name: str,
    ) -> CaptureResult | None:
        """Handle high-signal relationship language without inventing entities."""
        current = now or datetime.now(UTC)
        conditional = re.search(
            r"(?:if\s+)?(?P<name>[A-Z][A-Za-z'-]+)\s+(?:does not|doesn't)\s+(?P<action>.+?)\s+by\s+(?P<first>\w+)[,.]?\s+"
            r"I\s+will\s+(?P<follow>contact|call|email|follow up with)\s+(?:him|her|them|(?P<same>[A-Z][A-Za-z'-]+))\s+on\s+(?P<second>\w+)",
            source,
            re.IGNORECASE,
        )
        if conditional:
            name = conditional.group("name")
            waiting = CommitmentCandidate(
                title=f"Wait for {name}",
                description=source,
                type=CommitmentType.WAITING_FOR,
                person=name,
                contact_kind="person",
                contact_role="responsible",
                contact_status="resolved",
                needs_confirmation=True,
                evidence=source,
            )
            follow_text = f"I will {conditional.group('follow')} {name} on {conditional.group('second')}"
            follow = CommitmentExtractor()._extract_single(follow_text, now=current, timezone_name=timezone_name).candidates[0]
            follow.type = CommitmentType.FOLLOW_UP
            follow.person = name
            follow.contact_kind = "person"
            follow.contact_role = "recipient"
            follow.contact_status = "resolved"
            follow.evidence = source
            return CaptureResult(
                candidates=[waiting, follow],
                relationships=[
                    CommitmentRelationshipCandidate(source_index=0, target_index=1, relationship=CommitmentRelationshipType.FOLLOWED_BY, evidence=source, confidence=0.9),
                    CommitmentRelationshipCandidate(source_index=1, target_index=0, relationship=CommitmentRelationshipType.RESPONSE_REQUIRED_FROM, evidence=source, confidence=0.9),
                ],
                explanation="Extracted waiting and conditional follow-up commitments.",
            )
        waiting_fallback = re.search(
            r"I\s+am\s+waiting\s+for\s+(?P<name>[A-Z][A-Za-z'-]+)(?:'s|\s+)?.*?\.\s*"
            r"If\s+they\s+(?:do not|don't)\s+respond,\s+I\s+will\s+(?P<action>call|contact|email)\s+them\s+on\s+(?P<date>\w+)",
            source,
            re.IGNORECASE,
        )
        if waiting_fallback:
            name = waiting_fallback.group("name")
            waiting = CommitmentCandidate(
                title=f"Wait for {name}", description=source, type=CommitmentType.WAITING_FOR,
                person=name, contact_kind="person", contact_role="responsible", contact_status="resolved",
                needs_confirmation=True, evidence=source,
            )
            follow_text = f"I will {waiting_fallback.group('action')} {name} on {waiting_fallback.group('date')}"
            follow = CommitmentExtractor()._extract_single(follow_text, now=current, timezone_name=timezone_name).candidates[0]
            follow.type = CommitmentType.FOLLOW_UP
            follow.person = name
            follow.contact_kind = "person"
            follow.contact_role = "recipient"
            follow.evidence = source
            return CaptureResult(
                candidates=[waiting, follow],
                relationships=[
                    CommitmentRelationshipCandidate(source_index=0, target_index=1, relationship=CommitmentRelationshipType.FOLLOWED_BY, evidence=source, confidence=0.9),
                    CommitmentRelationshipCandidate(source_index=1, target_index=0, relationship=CommitmentRelationshipType.RESPONSE_REQUIRED_FROM, evidence=source, confidence=0.9),
                ],
                explanation="Extracted waiting and conditional follow-up commitments.",
            )
        approval = re.match(
            r"Once\s+(?P<owner>.+?)\s+(?:confirms|approves|responds),?\s+I\s+will\s+(?P<action>.+)",
            source.strip().rstrip(".!?"),
            re.IGNORECASE,
        )
        if approval:
            owner = approval.group("owner").strip()
            task = CommitmentExtractor()._extract_single(
                f"I will {approval.group('action')}", now=current, timezone_name=timezone_name
            ).candidates[0]
            waiting = CommitmentCandidate(
                title=f"Wait for {owner} approval",
                description=owner,
                type=CommitmentType.WAITING_FOR,
                person=owner,
                contact_kind=CommitmentExtractor._contact_kind(owner),
                contact_role="responsible",
                contact_status="unresolved",
                needs_confirmation=True,
                evidence=source,
            )
            task.evidence = source
            return CaptureResult(
                candidates=[waiting, task],
                relationships=[CommitmentRelationshipCandidate(source_index=1, target_index=0, relationship=CommitmentRelationshipType.DEPENDS_ON, evidence=source, confidence=0.9)],
                explanation="Extracted approval dependency.",
            )
        correction = re.match(r"I said I would (?P<old>.+?), but correction:\s*I will (?P<new>.+)", source.strip(), re.I)
        if correction:
            old = CommitmentExtractor()._extract_single(f"I will {correction.group('old')}", now=current, timezone_name=timezone_name).candidates[0]
            old.extraction_status = "cancelled"
            new = CommitmentExtractor()._extract_single(f"I will {correction.group('new')}", now=current, timezone_name=timezone_name).candidates[0]
            return CaptureResult(
                candidates=[old, new],
                relationships=[CommitmentRelationshipCandidate(source_index=1, target_index=0, relationship=CommitmentRelationshipType.SUPERSEDES, evidence=source, confidence=0.95)],
                explanation="Extracted correction and superseding commitment.",
            )
        return None

    @staticmethod
    def _split_commitments(source: str) -> list[str]:
        if not re.search(r"\b(?:,\s*and\s+|\band\s+|;\s*|\bthen\s+)", source, re.I):
            return [source]
        parts = re.split(
            r"(?:,\s*(?:and\s+)?|\s+and\s+|;\s*|\s+then\s+)(?=(?:i(?:'ll| will| need to| have to)|ask|email|send|submit|follow|contact|call|review|complete|wait|once)\b)",
            source,
            flags=re.IGNORECASE,
        )
        cleaned = [part.strip(" .,!?") for part in parts if part.strip(" .,!?")]
        return cleaned if len(cleaned) > 1 else [source]

    def _extract_single(self, text: str, *, now: datetime | None = None, timezone_name: str = "UTC") -> CaptureResult:
        now = now or datetime.now(UTC)
        try:
            now = now.astimezone(ZoneInfo(timezone_name))
        except KeyError:
            pass
        source = text.strip()
        if not source:
            return CaptureResult(candidates=[], explanation="Empty capture")
        lowered = source.lower()
        if re.search(r"\b(?:no action|nothing to do|no need to|do not need to)\b", lowered):
            return CaptureResult(candidates=[], explanation="No active user commitment was stated")
        commitment_type = CommitmentType.PERSONAL_TASK
        if re.match(r"^[A-Z][A-Za-z'-]+\s+(?:will|should|must)\b", source):
            commitment_type = CommitmentType.WAITING_FOR
        elif any(phrase in lowered for phrase in ("waiting for", "wait for", "expecting", "owed", "owes me", "reply from")):
            commitment_type = CommitmentType.WAITING_FOR
        elif any(phrase in lowered for phrase in ("follow up", "follow-up", "check with")):
            commitment_type = CommitmentType.FOLLOW_UP
        elif self._date_pattern.search(source):
            commitment_type = CommitmentType.DEADLINE

        due_at = self._parse_relative_date(source, now)
        email_match = self._email_pattern.search(source)
        person = self._infer_person(source)
        contact_kind = self._contact_kind(person or (email_match.group(0) if email_match else None))
        needs_confirmation = due_at is None or (due_at < now) or (
            commitment_type in {CommitmentType.WAITING_FOR, CommitmentType.FOLLOW_UP}
            and (person is None or email_match is None)
        )
        title = self._title(source, commitment_type)
        candidate = CommitmentCandidate(
            title=title,
            description=source,
            type=commitment_type,
            person=person,
            contact_email=email_match.group(0) if email_match else None,
            contact_kind=contact_kind,
            contact_role=self._contact_role(source, person),
            contact_status=(
                "resolved"
                if email_match or (person and re.fullmatch(r"(?:Dr\s+)?[A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+)*", person))
                else "unresolved"
            ),
            due_at=due_at,
            timezone=timezone_name,
            reminder_at=due_at - timedelta(hours=24) if due_at else None,
            confidence=0.62 if due_at else 0.45,
            needs_confirmation=needs_confirmation,
            evidence=source,
            action=self._infer_action(source),
            expected_recipient=person,
            actor=(person if commitment_type == CommitmentType.WAITING_FOR else "user"),
            action=self._infer_action(source),
            deadline_owner=(person if commitment_type == CommitmentType.WAITING_FOR else "user") if due_at else None,
            condition=(re.search(r"\bif\s+(.+)", source, re.IGNORECASE).group(0) if re.search(r"\bif\s+(.+)", source, re.IGNORECASE) else None),
            responsibility=(
                "USER_WAITING_FOR" if commitment_type == CommitmentType.WAITING_FOR else
                "USER_CONTACTS" if commitment_type == CommitmentType.FOLLOW_UP else
                "USER_PERFORMS"
            ),
        )
        return CaptureResult(candidates=[candidate], explanation="Deterministic local extraction; confirmation is required for uncertain fields")

    def _parse_relative_date(self, source: str, now: datetime) -> datetime | None:
        match = self._date_pattern.search(source)
        if not match:
            return None
        value = match.group(1).lower()
        if value == "today":
            return now.replace(hour=17, minute=0, second=0, microsecond=0)
        if value == "tomorrow":
            return (now + timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)
        if value == "tonight":
            return now.replace(hour=20, minute=0, second=0, microsecond=0)
        if value == "next week":
            return (now + timedelta(days=7)).replace(hour=17, minute=0, second=0, microsecond=0)
        if value == "next month":
            month = now.month % 12 + 1
            year = now.year + (1 if now.month == 12 else 0)
            return now.replace(year=year, month=month, day=1, hour=17, minute=0, second=0, microsecond=0)
        if value == "end of this week" or value == "end of week":
            return (now + timedelta(days=4 - now.weekday())).replace(hour=17, minute=0, second=0, microsecond=0)
        if value.startswith("in ") and value.endswith(" days"):
            number = value[3:-5].strip()
            words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
            days = words[number] if number in words else int(number) if number.isdigit() else 0
            return (now + timedelta(days=days)).replace(hour=17, minute=0, second=0, microsecond=0)
        weekdays = {day.lower(): index for index, day in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))}
        if value.startswith("next ") and value[5:] in weekdays:
            delta = (weekdays[value[5:]] - now.weekday()) % 7 or 7
            return (now + timedelta(days=delta + 7)).replace(hour=17, minute=0, second=0, microsecond=0)
        if value in weekdays:
            delta = (weekdays[value] - now.weekday()) % 7 or 7
            return (now + timedelta(days=delta)).replace(hour=17, minute=0, second=0, microsecond=0)
        try:
            parsed = date_parser.parse(value, default=now)
            return parsed.replace(tzinfo=parsed.tzinfo or UTC, hour=17, minute=0, second=0, microsecond=0)
        except (ValueError, OverflowError):
            return None

    @staticmethod
    def _infer_person(source: str) -> str | None:
        leading = re.match(r"^([A-Z][A-Za-z'-]+)\s+(?:will|should|must)\b", source)
        if leading:
            return leading.group(1)
        for pattern in CommitmentExtractor._contact_patterns:
            match = pattern.search(source)
            if match:
                value = match.group(1).strip(" .,!?:;\"")
                value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.I)
                if value and not value.lower().startswith(("me ", "them", "him", "her", "someone", "somebody")):
                    return value
        match = re.search(r"\b(?:with|from|to|ask|contact|email)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", source)
        if match:
            return match.group(1)
        waiting_match = re.search(
            r"\bwaiting for (?:the\s+)?([a-z][a-z-]*(?:\s+[a-z][a-z-]*)*?)(?=\s+(?:to|that|who|send|reply|confirm)\b|\s*$)",
            source,
            re.IGNORECASE,
        )
        return waiting_match.group(1) if waiting_match else None

    @staticmethod
    def _contact_kind(person: str | None) -> Literal["person", "organisation", "unknown"]:
        if not person:
            return "unknown"
        lowered = person.lower()
        if "@" in person:
            return "person"
        if any(word in lowered.split() for word in (
            "team", "library", "clinic", "company", "organisation", "organization", "office",
            "vendor", "registrar", "university", "insurance", "insurer", "procurement", "billing",
        )):
            return "organisation"
        if lowered.startswith(("my professor", "my landlord", "my project partner")):
            return "person"
        if lowered in {"placement coordinator", "professor", "landlord", "project partner"}:
            return "person"
        return "person" if re.fullmatch(r"[A-Z][A-Za-z'-]+(?:\s+[A-Z][A-Za-z'-]+)*", person) else "unknown"

    @staticmethod
    def _contact_role(source: str, person: str | None) -> Literal["recipient", "mentioned", "responsible", "unknown"]:
        lowered = source.lower()
        if re.search(r"\b(?:ask|contact|email|follow(?: |-)?up with|promised)\b", lowered):
            return "recipient"
        if re.search(r"\b(?:wait(?:ing)? for|owes me|reply from|expecting)\b", lowered):
            return "responsible"
        return "mentioned" if person else "unknown"

    @staticmethod
    def _infer_action(source: str) -> str | None:
        match = re.search(
            r"\b(?:to|need to|must|should|will|ask .*? to)\s+([a-z][a-z -]{2,80})",
            source,
            re.IGNORECASE,
        )
        return match.group(1).strip(" .,!?") if match else None

    @staticmethod
    def _title(source: str, commitment_type: CommitmentType) -> str:
        cleaned = source.rstrip(".!?").strip()
        if len(cleaned) <= 80:
            return cleaned[:1].upper() + cleaned[1:]
        prefix = {CommitmentType.WAITING_FOR: "Waiting for", CommitmentType.FOLLOW_UP: "Follow up", CommitmentType.DEADLINE: "Deadline"}.get(commitment_type, "Commitment")
        return f"{prefix}: {cleaned[:70]}…"


class CommitmentService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, candidate: CommitmentCandidate, *, confirmed: bool = False, source: str = "manual") -> Commitment:
        status = CommitmentStatus.ACTIVE if confirmed and not candidate.needs_confirmation else CommitmentStatus.NEEDS_CONFIRMATION
        if candidate.type == CommitmentType.WAITING_FOR and confirmed:
            status = CommitmentStatus.WAITING
        if candidate.extraction_status == "completed":
            status = CommitmentStatus.COMPLETED
        elif candidate.extraction_status == "cancelled":
            status = CommitmentStatus.CANCELLED
        elif candidate.extraction_status == "postponed":
            status = CommitmentStatus.POSTPONED
        contact_email = candidate.contact_email
        if candidate.person and not contact_email:
            contact = self.session.scalar(
                select(Contact).where(Contact.name.ilike(candidate.person)).limit(1)
            )
            contact_email = contact.email if contact else None
        commitment = Commitment(
            title=candidate.title,
            description=candidate.description,
            type=candidate.type,
            status=status,
            person=candidate.person,
            contact_email=contact_email,
            event_id=candidate.event_id,
            actor=candidate.actor,
            action=candidate.action,
            object=candidate.object,
            beneficiary=candidate.beneficiary,
            deadline_owner=candidate.deadline_owner,
            condition=candidate.condition,
            responsibility=candidate.responsibility,
            source_span=candidate.source_span,
            due_at=candidate.due_at,
            timezone=candidate.timezone,
            reminder_at=candidate.reminder_at,
            source=source,
            evidence=candidate.evidence,
            confidence=candidate.confidence,
            needs_confirmation=not confirmed and candidate.needs_confirmation,
        )
        self.session.add(commitment)
        self.session.flush()
        self.session.add(CommitmentEvent(commitment_id=commitment.id, event_type="created", detail=candidate.evidence))
        self._update_fts(commitment)
        if confirmed and candidate.reminder_at:
            self.schedule_reminder(commitment.id, candidate.reminder_at)
        return commitment

    def create_many(
        self,
        candidates: list[CommitmentCandidate],
        relationships: list[CommitmentRelationshipCandidate] | None = None,
        *,
        source: str = "manual",
    ) -> list[Commitment]:
        """Persist a capture atomically, then attach validated candidate relationships."""
        commitments = [
            self.create(candidate, confirmed=not candidate.needs_confirmation, source=source)
            for candidate in candidates
        ]
        for relation in relationships or []:
            if relation.source_index >= len(commitments) or relation.target_index >= len(commitments):
                continue
            if relation.source_index == relation.target_index:
                continue
            self.add_relationship(
                commitments[relation.source_index].id,
                commitments[relation.target_index].id,
                relation.relationship,
            )
            self._update_fts(commitments[relation.source_index])
            self._update_fts(commitments[relation.target_index])
        return commitments

    def add_relationship(
        self,
        commitment_id: str,
        related_commitment_id: str,
        relationship: CommitmentRelationshipType | str,
    ) -> CommitmentRelationship:
        if commitment_id == related_commitment_id:
            raise ValueError("A commitment cannot relate to itself")
        self._required(commitment_id)
        self._required(related_commitment_id)
        relation_type = CommitmentRelationshipType(str(relationship))
        existing = self.session.scalar(
            select(CommitmentRelationship).where(
                CommitmentRelationship.commitment_id == commitment_id,
                CommitmentRelationship.related_commitment_id == related_commitment_id,
                CommitmentRelationship.relationship == relation_type,
            )
        )
        if existing:
            return existing
        relation = CommitmentRelationship(
            commitment_id=commitment_id,
            related_commitment_id=related_commitment_id,
            relationship=relation_type,
        )
        self.session.add(relation)
        self.session.flush()
        return relation

    def related(
        self,
        commitment_id: str,
        *,
        relationship: CommitmentRelationshipType | str | None = None,
    ) -> list[tuple[CommitmentRelationship, Commitment]]:
        """Return outgoing and incoming edges with their related records."""
        self._required(commitment_id)
        outgoing = list(
            self.session.scalars(
                select(CommitmentRelationship).where(
                    CommitmentRelationship.commitment_id == commitment_id
                )
            )
        )
        incoming = list(
            self.session.scalars(
                select(CommitmentRelationship).where(
                    CommitmentRelationship.related_commitment_id == commitment_id
                )
            )
        )
        relations = outgoing + incoming
        if relationship is not None:
            relation_type = CommitmentRelationshipType(str(relationship))
            relations = [item for item in relations if item.relationship == relation_type]
        values: list[tuple[CommitmentRelationship, Commitment]] = []
        for item in relations:
            related_id = (
                item.related_commitment_id
                if item.commitment_id == commitment_id
                else item.commitment_id
            )
            related = self.get(related_id)
            if related:
                values.append((item, related))
        return values

    def search_related(self, query_text: str, *, limit: int = 50) -> list[tuple[CommitmentRelationship, Commitment, Commitment]]:
        """Search relationship labels and both endpoint text for local assistant queries."""
        pattern = f"%{query_text.strip()}%"
        relations = list(
            self.session.scalars(
                select(CommitmentRelationship).where(
                    CommitmentRelationship.relationship.ilike(pattern)
                ).limit(limit)
            )
        )
        if not relations:
            relations = list(self.session.scalars(select(CommitmentRelationship).limit(limit)))
        result: list[tuple[CommitmentRelationship, Commitment, Commitment]] = []
        for relation in relations:
            left = self.get(relation.commitment_id)
            right = self.get(relation.related_commitment_id)
            if left and right and (
                not query_text.strip()
                or query_text.casefold() in f"{left.title} {left.description} {right.title} {right.description}".casefold()
            ):
                result.append((relation, left, right))
        return result[:limit]

    def list(self, *, status: CommitmentStatus | None = None, limit: int = 100) -> list[Commitment]:
        query = select(Commitment).order_by(Commitment.due_at.is_(None), Commitment.due_at).limit(limit)
        if status:
            query = query.where(Commitment.status == status)
        return list(self.session.scalars(query))

    def search(
        self,
        query_text: str = "",
        *,
        status: CommitmentStatus | None = None,
        limit: int = 100,
    ) -> builtins.list[Commitment]:
        if not query_text.strip():
            return self.list(status=status, limit=limit)
        identifiers: list[str] = list(
            self.session.execute(
                text(
                    "SELECT commitment_id FROM commitment_fts "
                    "WHERE commitment_fts MATCH :query LIMIT :limit"
                ),
                {"query": query_text.strip().replace("\"", ""), "limit": limit},
            ).scalars()
        )
        if not identifiers:
            return []
        statement = select(Commitment).where(Commitment.id.in_(identifiers))
        if status:
            statement = statement.where(Commitment.status == status)
        commitments = list(self.session.scalars(statement))
        order = {identifier: index for index, identifier in enumerate(identifiers)}
        return sorted(commitments, key=lambda item: order.get(item.id, limit))

    def get(self, commitment_id: str) -> Commitment | None:
        return self.session.get(Commitment, commitment_id)

    def confirm(self, commitment_id: str, *, due_at: datetime | None = None, person: str | None = None) -> Commitment:
        commitment = self._required(commitment_id)
        if due_at:
            commitment.due_at = due_at
        if person:
            commitment.person = person
        commitment.needs_confirmation = False
        commitment.status = CommitmentStatus.WAITING if commitment.type == CommitmentType.WAITING_FOR else CommitmentStatus.ACTIVE
        self.session.add(CommitmentEvent(commitment_id=commitment.id, event_type="confirmed", detail="User confirmed candidate"))
        self._update_fts(commitment)
        if commitment.reminder_at:
            self.schedule_reminder(commitment.id, commitment.reminder_at)
        return commitment

    def complete(self, commitment_id: str) -> Commitment:
        commitment = self._required(commitment_id)
        commitment.status = CommitmentStatus.COMPLETED
        self._dismiss_reminders(commitment.id)
        self.session.add(CommitmentEvent(commitment_id=commitment.id, event_type="completed"))
        return commitment

    def cancel(self, commitment_id: str) -> Commitment:
        commitment = self._required(commitment_id)
        commitment.status = CommitmentStatus.CANCELLED
        self._dismiss_reminders(commitment.id)
        self.session.add(CommitmentEvent(commitment_id=commitment.id, event_type="cancelled"))
        return commitment

    def update(
        self,
        commitment_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        person: str | None = None,
        contact_email: str | None = None,
        due_at: datetime | None = None,
        reminder_at: datetime | None = None,
        status: CommitmentStatus | None = None,
    ) -> Commitment:
        commitment = self._required(commitment_id)
        changed: list[str] = []
        for field, value in {
            "title": title,
            "description": description,
            "person": person,
            "contact_email": contact_email,
            "due_at": due_at,
            "reminder_at": reminder_at,
            "status": status,
        }.items():
            if value is not None and getattr(commitment, field) != value:
                setattr(commitment, field, value)
                changed.append(field)
        if changed:
            commitment.needs_confirmation = False
            self._update_fts(commitment)
            self.session.add(
                CommitmentEvent(
                    commitment_id=commitment.id,
                    event_type="updated",
                    detail=", ".join(changed),
                )
            )
            if reminder_at:
                self.schedule_reminder(commitment.id, reminder_at)
        return commitment

    def postpone(self, commitment_id: str, until: datetime) -> Commitment:
        commitment = self._required(commitment_id)
        commitment.due_at = until
        commitment.status = CommitmentStatus.POSTPONED
        commitment.needs_confirmation = False
        self.session.add(CommitmentEvent(commitment_id=commitment.id, event_type="postponed", detail=until.isoformat()))
        self.schedule_reminder(commitment.id, until)
        return commitment

    def snooze(self, commitment_id: str, until: datetime) -> Reminder:
        commitment = self._required(commitment_id)
        reminder = self.session.scalar(
            select(Reminder)
            .where(Reminder.commitment_id == commitment.id, Reminder.dismissed.is_(False))
            .order_by(Reminder.scheduled_at)
        )
        if reminder is None:
            return self.schedule_reminder(commitment.id, until)
        reminder.snoozed_until = until
        reminder.scheduled_at = until
        reminder.delivered_at = None
        return reminder

    def schedule_reminder(self, commitment_id: str, scheduled_at: datetime) -> Reminder:
        existing = self.session.scalar(select(Reminder).where(Reminder.commitment_id == commitment_id, Reminder.scheduled_at == scheduled_at))
        if existing:
            return existing
        reminder = Reminder(commitment_id=commitment_id, scheduled_at=scheduled_at)
        self.session.add(reminder)
        return reminder

    def _dismiss_reminders(self, commitment_id: str) -> None:
        reminders = self.session.scalars(
            select(Reminder).where(Reminder.commitment_id == commitment_id)
        )
        for reminder in reminders:
            reminder.dismissed = True

    def _required(self, commitment_id: str) -> Commitment:
        commitment = self.get(commitment_id)
        if not commitment:
            raise KeyError(f"Unknown commitment: {commitment_id}")
        return commitment

    def _update_fts(self, commitment: Commitment) -> None:
        self.session.execute(text("DELETE FROM commitment_fts WHERE commitment_id = :id"), {"id": commitment.id})
        related_text = " ".join(
            f"{relation.relationship.value} {related.title} {related.description}"
            for relation, related in self.related(commitment.id)
        )
        self.session.execute(text("INSERT INTO commitment_fts(commitment_id, title, description, person, content) VALUES (:id, :title, :description, :person, :content)"), {
            "id": commitment.id, "title": commitment.title, "description": commitment.description,
            "person": commitment.person or "", "content": f"{commitment.title} {commitment.description} {related_text}",
        })
