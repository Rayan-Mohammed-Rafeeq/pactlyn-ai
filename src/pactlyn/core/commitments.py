from __future__ import annotations

import builtins
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from dateutil import parser as date_parser
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pactlyn.storage.models import (
    Commitment,
    CommitmentEvent,
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


class CaptureResult(BaseModel):
    candidates: list[CommitmentCandidate]
    explanation: str = ""
    used_local_model: bool = False
    used_fallback: bool = False
    provider_name: str | None = None
    provider_error: str | None = None


class CommitmentExtractor:
    """Small deterministic baseline used when Ollama is unavailable.

    The production path is ``OllamaGateway.extract_commitments``. This parser
    keeps capture useful during first-run setup and is deliberately conservative:
    uncertain dates and recipients remain confirmation-required.
    """

    _date_pattern = re.compile(
        r"\b(today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"next week|next month|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b",
        re.IGNORECASE,
    )
    _email_pattern = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")

    def extract(self, text: str, *, now: datetime | None = None, timezone_name: str = "UTC") -> CaptureResult:
        now = now or datetime.now(UTC)
        try:
            now = now.astimezone(ZoneInfo(timezone_name))
        except KeyError:
            pass
        source = text.strip()
        if not source:
            return CaptureResult(candidates=[], explanation="Empty capture")
        lowered = source.lower()
        commitment_type = CommitmentType.PERSONAL_TASK
        if any(phrase in lowered for phrase in ("waiting for", "expecting", "owed", "reply from")):
            commitment_type = CommitmentType.WAITING_FOR
        elif any(phrase in lowered for phrase in ("follow up", "follow-up", "check with")):
            commitment_type = CommitmentType.FOLLOW_UP
        elif self._date_pattern.search(source):
            commitment_type = CommitmentType.DEADLINE

        due_at = self._parse_relative_date(source, now)
        email_match = self._email_pattern.search(source)
        person = self._infer_person(source)
        needs_confirmation = due_at is None or (commitment_type in {CommitmentType.WAITING_FOR, CommitmentType.FOLLOW_UP} and person is None)
        title = self._title(source, commitment_type)
        candidate = CommitmentCandidate(
            title=title,
            description=source,
            type=commitment_type,
            person=person,
            contact_email=email_match.group(0) if email_match else None,
            due_at=due_at,
            timezone=timezone_name,
            reminder_at=due_at - timedelta(hours=24) if due_at else None,
            confidence=0.62 if due_at else 0.45,
            needs_confirmation=needs_confirmation,
            evidence=source,
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
            return (now + timedelta(days=30)).replace(hour=17, minute=0, second=0, microsecond=0)
        weekdays = {day.lower(): index for index, day in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))}
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
        match = re.search(r"\b(?:with|from|to|ask|contact|email)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", source)
        if match:
            return match.group(1)
        waiting_match = re.search(r"\bwaiting for (?:the\s+)?([a-z][a-z-]*(?:\s+[a-z][a-z-]*)?)", source, re.IGNORECASE)
        return waiting_match.group(1) if waiting_match else None

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
        self.session.execute(text("INSERT INTO commitment_fts(commitment_id, title, description, person, content) VALUES (:id, :title, :description, :person, :content)"), {
            "id": commitment.id, "title": commitment.title, "description": commitment.description,
            "person": commitment.person or "", "content": f"{commitment.title} {commitment.description}",
        })
