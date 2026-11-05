"""Idempotent migration: reclassify existing birthday commitments as personal facts.

This module finds any Commitment row whose title or evidence indicates a birthday
statement, creates (or updates) the corresponding PersonalFact, invalidates the
commitment, and preserves the audit trail.

Running the migration multiple times is safe — it is fully idempotent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from pactlyn.memory.facts import PersonalFactService
from pactlyn.storage.models import (
    Commitment,
    CommitmentStatus,
    PersonalFactCategory,
    PersonalFactConfirmationState,
)
from pactlyn.vectorstore.interface import VectorStore

_BIRTHDAY_IN_TITLE = re.compile(r"\bbirthday\b|\bborn\b", re.IGNORECASE)
_BIRTHDAY_IN_EVIDENCE = re.compile(
    r"\b(?:birthday|born|date\s+of\s+birth|birth\s+year)\b", re.IGNORECASE
)

# ISO date pattern (YYYY-MM-DD)
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# Informal date patterns
_INFORMAL_DATE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+"
    r"(\d{4})\b",
    re.IGNORECASE,
)

_MONTH_NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


@dataclass
class MigrationResult:
    reclassified: int = 0
    already_migrated: int = 0
    ambiguous: int = 0
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def _parse_birthday_date(text: str) -> tuple[str, str] | None:
    """Return (iso_value, display_value) or None if no date found."""
    # Try ISO first
    m = _ISO_DATE.search(text)
    if m:
        iso = m.group(1)
        parts = iso.split("-")
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        try:
            dt = datetime(year, month, day)
            display = dt.strftime("%-d %B %Y")
            return iso, display
        except ValueError:
            return None

    # Try informal date
    m = _INFORMAL_DATE.search(text)
    if m:
        day = int(m.group(1))
        month_name = m.group(2).lower()
        year = int(m.group(3))
        month_num = _MONTH_NAMES.get(month_name)
        if month_num is None:
            return None
        try:
            dt = datetime(year, month_num, day)
            iso = dt.strftime("%Y-%m-%d")
            display = dt.strftime("%-d %B %Y")
            return iso, display
        except ValueError:
            return None

    return None


# Year-only pattern — e.g. "born in the year 2005" or "my birth year is 2005"
_YEAR_ONLY = re.compile(r"\b((?:19|20)\d{2})\b")


def _parse_birthday_year_only(text: str) -> tuple[str, str] | None:
    """Return (year_string, year_string) for a year-only birth year."""
    m = _YEAR_ONLY.search(text)
    if m:
        year = m.group(1)
        return year, year  # value = "2005", display = "2005"
    return None


async def migrate_birthday_commitments(
    session: Session,
    vectors: VectorStore,
    embedder: object,
) -> MigrationResult:
    """Find birthday commitments and reclassify them as personal facts.

    Safe to call multiple times:
    - If the personal fact already exists with the same value, does nothing.
    - If the commitment is already cancelled/completed, skips it.
    - Does not delete any commitment; sets status to CANCELLED and adds an
      audit note in the commitment's description to preserve history.
    """
    result = MigrationResult()
    fact_service = PersonalFactService(session, vectors, embedder)

    # Find candidate birthday commitments.
    # Include ALL statuses — even completed/cancelled ones may hold the source text.
    all_commitments = list(
        session.scalars(select(Commitment))
    )

    birthday_commitments: list[Commitment] = []
    for commitment in all_commitments:
        if _BIRTHDAY_IN_TITLE.search(commitment.title) or (
            commitment.evidence and _BIRTHDAY_IN_EVIDENCE.search(commitment.evidence)
        ):
            birthday_commitments.append(commitment)

    if not birthday_commitments:
        return result

    for commitment in birthday_commitments:
        # Try to extract a date from the commitment's source material.
        source_texts = [
            commitment.title,
            commitment.evidence,
            commitment.description,
            commitment.source_span,
        ]
        parsed = None
        year_only = False
        source_text_used = ""
        for text in source_texts:
            if text:
                parsed = _parse_birthday_date(text)
                if parsed is not None:
                    source_text_used = text
                    break
        # If no full date, try extracting a year alone (e.g. "born in the year 2005")
        if parsed is None:
            for text in source_texts:
                if text:
                    parsed = _parse_birthday_year_only(text)
                    if parsed is not None:
                        source_text_used = text
                        year_only = True
                        break

        if parsed is None:
            result.ambiguous += 1
            result.errors.append(
                f"Commitment {commitment.id!r} ({commitment.title!r}) appears to be a "
                "birthday but no date could be extracted. Manual review required."
            )
            continue

        iso_value, display_value = parsed
        attribute = "birth_year" if year_only else "date_of_birth"

        # Check whether the fact already exists with the same value.
        existing = fact_service.get(PersonalFactCategory.BIRTHDAY, attribute)
        if existing is not None and existing.value == iso_value:
            result.already_migrated += 1
            _invalidate_commitment(session, commitment)
            continue

        # Create (or update) the personal fact.
        await fact_service.upsert(
            category=PersonalFactCategory.BIRTHDAY,
            attribute=attribute,
            value=iso_value,
            display_value=display_value,
            source_text=source_text_used or commitment.evidence or commitment.title,
            recurrence="YEARLY" if not year_only else None,
            confidence=0.95,
            confirmation_state=PersonalFactConfirmationState.CONFIRMED,
        )
        # Fact stored — invalidate the commitment.
        _invalidate_commitment(session, commitment)
        result.reclassified += 1

    session.commit()
    return result


def _invalidate_commitment(session: Session, commitment: Commitment) -> None:
    """Mark a birthday commitment as cancelled with an audit note."""
    commitment.status = CommitmentStatus.CANCELLED
    if "Reclassified as personal fact" not in (commitment.description or ""):
        commitment.description = (
            (commitment.description + "\n" if commitment.description else "")
            + "[Reclassified as personal fact — birthday / date-of-birth]"
        )
