"""Personal fact persistence and retrieval.

Personal facts (birthday, full name, university, preferences …) are
stored in the ``personal_facts`` table and the ``personal_facts`` Qdrant
collection.  They are explicitly NOT commitments and must never create
reminders, tasks or deadline items unless the user explicitly requests one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pactlyn.llm.interfaces import LLMUnavailable
from pactlyn.storage.models import (
    PersonalFact,
    PersonalFactCategory,
    PersonalFactConfirmationState,
)
from pactlyn.vectorstore.collections import COLLECTION_PERSONAL_FACTS
from pactlyn.vectorstore.interface import VectorStore


class PersonalFactService:
    """Create, retrieve and update personal facts with Qdrant indexing."""

    def __init__(self, session: Session, vectors: VectorStore, embedder: object):
        self.session = session
        self.vectors = vectors
        self.embedder = embedder

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def upsert(
        self,
        *,
        category: PersonalFactCategory,
        attribute: str,
        value: str,
        display_value: str = "",
        source_text: str = "",
        recurrence: str | None = None,
        confidence: float = 1.0,
        confirmation_state: PersonalFactConfirmationState = PersonalFactConfirmationState.CONFIRMED,
        source_timestamp: datetime | None = None,
    ) -> PersonalFact:
        """Create or update a personal fact identified by (category, attribute).

        Idempotent: if the same (category, attribute) pair already exists and
        the value has not changed the existing row is returned without any
        write.  A change in value updates the row and re-indexes it.
        """
        existing = self.session.scalar(
            select(PersonalFact).where(
                PersonalFact.deleted_at.is_(None),
                PersonalFact.category == category,
                PersonalFact.attribute == attribute,
            )
        )

        if existing is not None:
            if existing.value == value:
                # No change – return early without touching the DB.
                return existing
            # Value changed: update the row.
            existing.value = value
            existing.display_value = display_value or value
            existing.confidence = confidence
            existing.confirmation_state = confirmation_state
            if source_text:
                existing.source_text = source_text
            if source_timestamp is not None:
                existing.source_timestamp = source_timestamp
            if recurrence is not None:
                existing.recurrence = recurrence
            existing.indexed = False          # will be re-indexed below
            self.session.flush()
            fact = existing
        else:
            fact = PersonalFact(
                category=category,
                attribute=attribute,
                value=value,
                display_value=display_value or value,
                source_text=source_text,
                source_timestamp=source_timestamp,
                recurrence=recurrence,
                confidence=confidence,
                confirmation_state=confirmation_state,
                indexed=False,
            )
            self.session.add(fact)
            self.session.flush()

        # FTS5 index
        self._update_fts(fact)

        # Qdrant index
        await self._index_vector(fact)

        self.session.commit()
        return fact

    async def _index_vector(self, fact: PersonalFact) -> None:
        embed_text = self._embed_text(fact)
        try:
            vectors = await self.embedder.embed([embed_text])  # type: ignore[attr-defined]
            if not vectors or not vectors[0]:
                raise ValueError("Embedding provider returned no vector")
            self.vectors.upsert(
                COLLECTION_PERSONAL_FACTS,
                fact.id,
                vectors[0],
                {
                    "fact_id": fact.id,
                    "category": fact.category.value,
                    "attribute": fact.attribute,
                    "value": fact.value,
                    "display_value": fact.display_value,
                    "source_text": fact.source_text,
                },
            )
            fact.indexed = True
        except LLMUnavailable:
            fact.indexed = False

    def _update_fts(self, fact: PersonalFact) -> None:
        self.session.execute(
            text("DELETE FROM personal_fact_fts WHERE fact_id = :fid"),
            {"fid": fact.id},
        )
        self.session.execute(
            text(
                "INSERT INTO personal_fact_fts(fact_id, attribute, value, display_value, source_text) "
                "VALUES (:fid, :attr, :val, :dv, :st)"
            ),
            {
                "fid": fact.id,
                "attr": fact.attribute,
                "val": fact.value,
                "dv": fact.display_value,
                "st": fact.source_text,
            },
        )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(
        self,
        category: PersonalFactCategory,
        attribute: str,
    ) -> PersonalFact | None:
        """Exact lookup by category + attribute."""
        return self.session.scalar(
            select(PersonalFact).where(
                PersonalFact.deleted_at.is_(None),
                PersonalFact.category == category,
                PersonalFact.attribute == attribute,
            )
        )

    def get_by_attribute(self, attribute: str) -> PersonalFact | None:
        """Lookup by attribute name alone (case-insensitive)."""
        return self.session.scalar(
            select(PersonalFact).where(
                PersonalFact.deleted_at.is_(None),
                PersonalFact.attribute == attribute.lower().replace(" ", "_"),
            )
        )

    def list_facts(self, *, category: PersonalFactCategory | None = None) -> list[PersonalFact]:
        query = (
            select(PersonalFact)
            .where(PersonalFact.deleted_at.is_(None))
            .order_by(PersonalFact.category, PersonalFact.attribute)
        )
        if category is not None:
            query = query.where(PersonalFact.category == category)
        return list(self.session.scalars(query))

    def keyword_lookup(self, terms: list[str], *, limit: int = 10) -> list[dict[str, Any]]:
        """FTS5 keyword search over personal facts."""
        if not terms:
            return []
        fts_query = " OR ".join(f'"{t}"' for t in terms if t.strip())
        if not fts_query:
            return []
        rows = list(
            self.session.execute(
                text(
                    "SELECT pf.* FROM personal_facts pf "
                    "JOIN personal_fact_fts fts ON pf.id = fts.fact_id "
                    "WHERE fts MATCH :q AND pf.deleted_at IS NULL "
                    "LIMIT :lim"
                ),
                {"q": fts_query, "lim": limit},
            ).mappings()
        )
        return [dict(r) for r in rows]

    def structured_profile_lookup(self, question: str) -> list[PersonalFact]:
        """Map common question patterns to structured fact lookups.

        Returns a list of matching facts (typically 0 or 1).  The caller
        decides how to surface the answer; this method never invents facts.

        Only matches first-person questions about the user's own profile.
        Questions about other people's attributes are excluded.
        """
        lowered = question.casefold()

        # Early exit: if the question is about someone else's attribute, skip
        # structured lookup and fall through to RAG.
        _THIRD_PERSON_MARKERS = (
            "my father", "my mother", "my brother", "my sister", "my friend",
            "my colleague", "my partner", "my spouse", "his birthday", "her birthday",
            "their birthday", "his name", "her name",
        )
        if any(marker in lowered for marker in _THIRD_PERSON_MARKERS):
            return []

        probes: list[tuple[PersonalFactCategory, str]] = []

        # Birthday / date of birth — user's own only
        if any(w in lowered for w in ("birthday", "born", "birth date", "date of birth", "dob",
                                       "age", "how old", "years old", "year of birth")):
            probes += [
                (PersonalFactCategory.BIRTHDAY, "date_of_birth"),
                (PersonalFactCategory.BIRTHDAY, "birthday"),
                (PersonalFactCategory.BIRTHDAY, "birth_year"),
            ]

        # Name
        if any(w in lowered for w in ("name", "full name", "my name", "called")):
            probes += [
                (PersonalFactCategory.IDENTITY, "full_name"),
                (PersonalFactCategory.IDENTITY, "name"),
            ]

        # University / school / study
        if any(w in lowered for w in ("university", "college", "study", "studying", "school", "attend", "enrolled")):
            probes += [
                (PersonalFactCategory.EDUCATION, "university"),
                (PersonalFactCategory.EDUCATION, "college"),
                (PersonalFactCategory.EDUCATION, "course"),
                (PersonalFactCategory.EDUCATION, "programme"),
            ]

        # Email preference / tone
        if any(w in lowered for w in ("email", "tone", "prefer", "communication")):
            probes += [
                (PersonalFactCategory.PREFERENCE, "email_tone"),
                (PersonalFactCategory.PREFERENCE, "email_preference"),
            ]

        # Project
        if any(w in lowered for w in ("project", "working on", "current project")):
            probes += [(PersonalFactCategory.CAREER, "current_project")]

        # Generic: search by keyword in attribute / display_value
        results: list[PersonalFact] = []
        seen: set[str] = set()
        for cat, attr in probes:
            fact = self.get(cat, attr)
            if fact is not None and fact.id not in seen:
                results.append(fact)
                seen.add(fact.id)

        # If no exact probe matched, fall back to LIKE scan on display_value
        if not results:
            import re
            tokens = [
                t for t in re.findall(r"[A-Za-z]{3,}", lowered)
                if t not in {
                    "what", "when", "where", "who", "how", "tell", "about",
                    "the", "my", "your", "you", "can", "please", "know",
                    "and", "for", "are", "was", "have", "has", "did", "does",
                }
            ]
            for token in tokens[:4]:
                rows = list(
                    self.session.scalars(
                        select(PersonalFact).where(
                            PersonalFact.deleted_at.is_(None),
                            PersonalFact.display_value.ilike(f"%{token}%"),
                        ).limit(5)
                    )
                )
                for fact in rows:
                    if fact.id not in seen:
                        results.append(fact)
                        seen.add(fact.id)

        return results

    async def reindex_pending(self) -> int:
        """Re-embed personal facts that failed indexing earlier."""
        rows = list(
            self.session.scalars(
                select(PersonalFact).where(
                    PersonalFact.deleted_at.is_(None),
                    PersonalFact.indexed.is_(False),
                )
            )
        )
        count = 0
        for fact in rows:
            await self._index_vector(fact)
            count += 1
        self.session.commit()
        return count

    def delete(self, fact_id: str) -> None:
        """Soft-delete a fact and remove its Qdrant vector."""
        fact = self.session.get(PersonalFact, fact_id)
        if fact is None:
            return
        fact.deleted_at = datetime.utcnow()
        self.vectors.delete(COLLECTION_PERSONAL_FACTS, fact_id)
        self.session.execute(
            text("DELETE FROM personal_fact_fts WHERE fact_id = :fid"),
            {"fid": fact_id},
        )
        self.session.commit()

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _embed_text(fact: PersonalFact) -> str:
        """Build the text that will be embedded for this fact."""
        parts = [fact.attribute.replace("_", " "), fact.display_value or fact.value]
        if fact.source_text:
            parts.append(fact.source_text)
        return " · ".join(p for p in parts if p)
