"""Regression tests for the personal-fact memory system.

Covers:
- InputClassifier classification correctness
- PersonalFactService persistence, deduplication, lookup
- Qdrant indexing via PersonalFactService
- RAGService structured fact lookup (birthday retrieval)
- KnowledgeGraphRepository personal-fact nodes
- Graph audit-event suppression ("Commitment captured" removed)
- Migration helper (birthday commitment reclassification)
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from pactlyn.memory.classification import InputClass, InputClassifier, PersonalFactHint
from pactlyn.memory.facts import PersonalFactService
from pactlyn.memory.graph import GraphNodeKind, KnowledgeGraphRepository
from pactlyn.memory.migrate_facts import migrate_birthday_commitments
from pactlyn.rag.embeddings import DeterministicTestEmbedding
from pactlyn.rag.retrieval import HybridRetriever
from pactlyn.rag.service import RAGService
from pactlyn.storage.models import (
    Commitment,
    CommitmentEvent,
    CommitmentStatus,
    PersonalFact,
    PersonalFactCategory,
    PersonalFactConfirmationState,
)
from pactlyn.vectorstore.qdrant_local import LocalQdrantStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fact_service(session: Session, tmp_path) -> PersonalFactService:
    vectors = LocalQdrantStore(tmp_path / "qdrant")
    return PersonalFactService(session, vectors, DeterministicTestEmbedding())


# ===========================================================================
# Phase 2 — InputClassifier
# ===========================================================================


class TestInputClassifier:
    """Classification correctness for all supported input classes."""

    def setup_method(self) -> None:
        self.clf = InputClassifier()

    # ---- birthday ----

    def test_birthday_iso_statement(self) -> None:
        result = self.clf.classify("2005-08-18 is my birthday.")
        assert InputClass.PERSONAL_FACT in result.classes
        assert PersonalFactHint.BIRTHDAY in result.fact_hints
        assert InputClass.COMMITMENT not in result.classes

    def test_birthday_informal_statement(self) -> None:
        result = self.clf.classify("18th aug 2005 is my birthday.")
        assert InputClass.PERSONAL_FACT in result.classes
        assert PersonalFactHint.BIRTHDAY in result.fact_hints
        assert InputClass.COMMITMENT not in result.classes

    def test_birthday_reversed_order(self) -> None:
        result = self.clf.classify("My birthday is 18 August 2005.")
        assert InputClass.PERSONAL_FACT in result.classes
        assert PersonalFactHint.BIRTHDAY in result.fact_hints
        assert InputClass.COMMITMENT not in result.classes

    def test_birthday_born_on(self) -> None:
        result = self.clf.classify("I was born on 18 August 2005.")
        assert InputClass.PERSONAL_FACT in result.classes
        assert PersonalFactHint.BIRTHDAY in result.fact_hints

    # ---- identity / name ----

    def test_name_statement(self) -> None:
        result = self.clf.classify("My full name is Rayan Mohammed Rafeeq.")
        assert InputClass.PERSONAL_FACT in result.classes
        # Either NAME or IDENTITY hint is acceptable
        assert any(h in result.fact_hints for h in (PersonalFactHint.NAME, PersonalFactHint.IDENTITY))

    # ---- education ----

    def test_university_statement(self) -> None:
        result = self.clf.classify("My university is NMIT.")
        assert InputClass.PERSONAL_FACT in result.classes
        assert PersonalFactHint.EDUCATION in result.fact_hints

    def test_study_ai_ml(self) -> None:
        result = self.clf.classify("I study Artificial Intelligence and Machine Learning.")
        assert InputClass.PERSONAL_FACT in result.classes

    # ---- preference ----

    def test_email_preference(self) -> None:
        result = self.clf.classify("I prefer concise emails.")
        assert InputClass.PERSONAL_FACT in result.classes
        assert PersonalFactHint.PREFERENCE in result.fact_hints

    def test_professional_emails(self) -> None:
        result = self.clf.classify("My email style is professional.")
        assert InputClass.PERSONAL_FACT in result.classes

    # ---- genuine commitment ----

    def test_commitment_no_personal_fact(self) -> None:
        result = self.clf.classify("I need to submit my report by Friday.")
        assert InputClass.COMMITMENT in result.classes
        assert PersonalFactHint.BIRTHDAY not in result.fact_hints

    def test_commitment_deadline(self) -> None:
        result = self.clf.classify("Send the proposal by Monday.")
        assert InputClass.COMMITMENT in result.classes

    # ---- waiting-for ----

    def test_waiting_for(self) -> None:
        result = self.clf.classify("I'm waiting for HR to send my interview schedule.")
        assert InputClass.WAITING_FOR in result.classes

    # ---- follow-up ----

    def test_follow_up(self) -> None:
        result = self.clf.classify("I need to follow up with the professor next week.")
        assert InputClass.FOLLOW_UP in result.classes

    # ---- event ----

    def test_event_interview(self) -> None:
        result = self.clf.classify("My interview is on Monday.")
        assert InputClass.EVENT in result.classes
        # An interview statement is an event, not a personal-fact
        assert InputClass.PERSONAL_FACT not in result.classes

    # ---- multi-class ----

    def test_multi_class_preference_and_commitment(self) -> None:
        result = self.clf.classify(
            "I prefer concise emails and I need to reply to the professor by Friday."
        )
        assert InputClass.PERSONAL_FACT in result.classes
        assert InputClass.COMMITMENT in result.classes

    # ---- primary classification ----

    def test_primary_is_first_class(self) -> None:
        result = self.clf.classify("18th aug 2005 is my birthday.")
        assert result.primary == InputClass.PERSONAL_FACT

    # ---- has_personal_fact helper ----

    def test_has_personal_fact_true(self) -> None:
        result = self.clf.classify("My name is Rayan.")
        assert result.has_personal_fact is True

    def test_has_personal_fact_false(self) -> None:
        result = self.clf.classify("Submit report by Friday.")
        assert result.has_personal_fact is False


# ===========================================================================
# Phase 1 — PersonalFactService persistence
# ===========================================================================


class TestPersonalFactService:
    """Persistence, deduplication, and lookup."""

    @pytest.mark.asyncio
    async def test_create_birthday_fact(self, tmp_path, session: Session) -> None:
        svc = _make_fact_service(session, tmp_path)
        fact = await svc.upsert(
            category=PersonalFactCategory.BIRTHDAY,
            attribute="date_of_birth",
            value="2005-08-18",
            display_value="18 August 2005",
            source_text="18th aug 2005 is my birthday.",
            recurrence="YEARLY",
        )
        assert fact.id is not None
        assert fact.value == "2005-08-18"
        assert fact.display_value == "18 August 2005"
        assert fact.recurrence == "YEARLY"
        assert fact.category == PersonalFactCategory.BIRTHDAY
        assert fact.confirmation_state == PersonalFactConfirmationState.CONFIRMED

    @pytest.mark.asyncio
    async def test_create_is_idempotent_when_value_unchanged(self, tmp_path, session: Session) -> None:
        svc = _make_fact_service(session, tmp_path)
        f1 = await svc.upsert(
            category=PersonalFactCategory.BIRTHDAY,
            attribute="date_of_birth",
            value="2005-08-18",
            display_value="18 August 2005",
        )
        f2 = await svc.upsert(
            category=PersonalFactCategory.BIRTHDAY,
            attribute="date_of_birth",
            value="2005-08-18",
            display_value="18 August 2005",
        )
        assert f1.id == f2.id
        total = len(svc.list_facts(category=PersonalFactCategory.BIRTHDAY))
        assert total == 1

    @pytest.mark.asyncio
    async def test_update_when_value_changes(self, tmp_path, session: Session) -> None:
        svc = _make_fact_service(session, tmp_path)
        f1 = await svc.upsert(
            category=PersonalFactCategory.IDENTITY,
            attribute="full_name",
            value="Rayan",
        )
        f2 = await svc.upsert(
            category=PersonalFactCategory.IDENTITY,
            attribute="full_name",
            value="Rayan Mohammed Rafeeq",
        )
        assert f1.id == f2.id
        assert f2.value == "Rayan Mohammed Rafeeq"

    @pytest.mark.asyncio
    async def test_get_exact_lookup(self, tmp_path, session: Session) -> None:
        svc = _make_fact_service(session, tmp_path)
        await svc.upsert(
            category=PersonalFactCategory.EDUCATION,
            attribute="university",
            value="NMIT",
            display_value="NMIT",
        )
        found = svc.get(PersonalFactCategory.EDUCATION, "university")
        assert found is not None
        assert found.value == "NMIT"

    @pytest.mark.asyncio
    async def test_list_all_facts(self, tmp_path, session: Session) -> None:
        svc = _make_fact_service(session, tmp_path)
        await svc.upsert(
            category=PersonalFactCategory.BIRTHDAY, attribute="date_of_birth", value="2005-08-18"
        )
        await svc.upsert(
            category=PersonalFactCategory.IDENTITY, attribute="full_name", value="Rayan"
        )
        facts = svc.list_facts()
        assert len(facts) == 2

    @pytest.mark.asyncio
    async def test_delete_soft_deletes(self, tmp_path, session: Session) -> None:
        svc = _make_fact_service(session, tmp_path)
        fact = await svc.upsert(
            category=PersonalFactCategory.OTHER, attribute="test_attr", value="test"
        )
        svc.delete(fact.id)
        assert svc.get(PersonalFactCategory.OTHER, "test_attr") is None

    @pytest.mark.asyncio
    async def test_qdrant_indexed_after_upsert(self, tmp_path, session: Session) -> None:
        svc = _make_fact_service(session, tmp_path)
        fact = await svc.upsert(
            category=PersonalFactCategory.BIRTHDAY,
            attribute="date_of_birth",
            value="2005-08-18",
            display_value="18 August 2005",
        )
        # The fact should be marked as indexed after a successful embed.
        refreshed = session.get(PersonalFact, fact.id)
        assert refreshed is not None
        assert refreshed.indexed is True

    @pytest.mark.asyncio
    async def test_birthday_not_stored_as_commitment(self, tmp_path, session: Session) -> None:
        """Creating a birthday personal fact must NOT produce any Commitment row."""
        svc = _make_fact_service(session, tmp_path)
        await svc.upsert(
            category=PersonalFactCategory.BIRTHDAY,
            attribute="date_of_birth",
            value="2005-08-18",
        )
        session.commit()
        from sqlalchemy import select
        commitments = list(session.scalars(select(Commitment)))
        assert len(commitments) == 0

    @pytest.mark.asyncio
    async def test_provenance_preserved_after_update(self, tmp_path, session: Session) -> None:
        svc = _make_fact_service(session, tmp_path)
        await svc.upsert(
            category=PersonalFactCategory.PREFERENCE,
            attribute="email_tone",
            value="professional",
            source_text="I prefer professional emails.",
        )
        await svc.upsert(
            category=PersonalFactCategory.PREFERENCE,
            attribute="email_tone",
            value="concise",
            source_text="I now prefer concise emails.",
        )
        fact = svc.get(PersonalFactCategory.PREFERENCE, "email_tone")
        assert fact is not None
        # Source text should have been updated to the latest statement.
        assert "concise" in fact.source_text


# ===========================================================================
# Phase 3 — RAG service with personal facts
# ===========================================================================


class _FactsProvider:
    """Test LLM that echoes the user message content back so tests can
    verify the facts were included in what was sent to the model."""

    name = "test-facts"
    is_local = True

    async def available(self) -> bool:
        return True

    async def complete(self, messages, *, json_schema=None) -> str:
        # Return the user message content so tests can assert on its contents
        user_content = next(
            (m["content"] for m in messages if m["role"] == "user"), ""
        )
        return f"Answer based on context: {user_content[:600]}"

    async def stream(self, messages):
        yield ""

    async def list_models(self):
        return []


class TestRAGServiceStructuredLookup:
    """RAGService sends personal facts to the LLM as context."""

    @pytest.mark.asyncio
    async def test_birthday_included_in_context(self, tmp_path, session: Session) -> None:
        """Birthday fact must appear in the context sent to the LLM."""
        vectors = LocalQdrantStore(tmp_path / "qdrant")
        embedder = DeterministicTestEmbedding()
        fact_svc = PersonalFactService(session, vectors, embedder)
        await fact_svc.upsert(
            category=PersonalFactCategory.BIRTHDAY,
            attribute="date_of_birth",
            value="2005-08-18",
            display_value="18 August 2005",
        )
        session.commit()

        from pactlyn.llm.gateway import LLMGateway

        service = RAGService(
            session,
            LLMGateway(_FactsProvider()),  # type: ignore[arg-type]
            HybridRetriever(session, vectors, embedder),
            fact_svc,
        )
        answer = await service.answer("When is my birthday?")
        assert answer.abstained is False
        assert answer.used_local_model is True
        assert "18 August 2005" in answer.answer or "2005-08-18" in answer.answer
        vectors.close()

    @pytest.mark.asyncio
    async def test_name_included_in_context(self, tmp_path, session: Session) -> None:
        vectors = LocalQdrantStore(tmp_path / "qdrant")
        embedder = DeterministicTestEmbedding()
        fact_svc = PersonalFactService(session, vectors, embedder)
        await fact_svc.upsert(
            category=PersonalFactCategory.IDENTITY,
            attribute="full_name",
            value="Rayan Mohammed Rafeeq",
            display_value="Rayan Mohammed Rafeeq",
        )
        session.commit()

        from pactlyn.llm.gateway import LLMGateway

        service = RAGService(
            session,
            LLMGateway(_FactsProvider()),  # type: ignore[arg-type]
            HybridRetriever(session, vectors, embedder),
            fact_svc,
        )
        answer = await service.answer("What is my full name?")
        assert answer.abstained is False
        assert "Rayan Mohammed Rafeeq" in answer.answer
        vectors.close()

    @pytest.mark.asyncio
    async def test_no_facts_no_evidence_abstains(self, tmp_path, session: Session) -> None:
        """With no facts and no memory records, the service abstains."""
        vectors = LocalQdrantStore(tmp_path / "qdrant")
        embedder = DeterministicTestEmbedding()
        fact_svc = PersonalFactService(session, vectors, embedder)

        from pactlyn.llm.gateway import LLMGateway

        service = RAGService(
            session,
            LLMGateway(_FactsProvider()),  # type: ignore[arg-type]
            HybridRetriever(session, vectors, embedder),
            fact_svc,
        )
        answer = await service.answer("What is my father's birthday?")
        assert answer.abstained is True
        vectors.close()

    @pytest.mark.asyncio
    async def test_university_included_in_context(self, tmp_path, session: Session) -> None:
        vectors = LocalQdrantStore(tmp_path / "qdrant")
        embedder = DeterministicTestEmbedding()
        fact_svc = PersonalFactService(session, vectors, embedder)
        await fact_svc.upsert(
            category=PersonalFactCategory.EDUCATION,
            attribute="university",
            value="NMIT",
            display_value="NMIT",
        )
        session.commit()

        from pactlyn.llm.gateway import LLMGateway

        service = RAGService(
            session,
            LLMGateway(_FactsProvider()),  # type: ignore[arg-type]
            HybridRetriever(session, vectors, embedder),
            fact_svc,
        )
        answer = await service.answer("Where do I study?")
        assert answer.abstained is False
        assert "NMIT" in answer.answer
        vectors.close()


# ===========================================================================
# Phase 4 — Knowledge graph personal-fact nodes
# ===========================================================================


class TestGraphPersonalFactNodes:
    """PersonalFact rows must produce PERSONAL_FACT graph nodes, not commitments."""

    @pytest.mark.asyncio
    async def test_birthday_produces_personal_fact_node(self, tmp_path, session: Session) -> None:
        vectors = LocalQdrantStore(tmp_path / "qdrant")
        svc = PersonalFactService(session, vectors, DeterministicTestEmbedding())
        await svc.upsert(
            category=PersonalFactCategory.BIRTHDAY,
            attribute="date_of_birth",
            value="2005-08-18",
            display_value="18 August 2005",
            source_text="18th aug 2005 is my birthday.",
        )
        session.commit()

        graph = KnowledgeGraphRepository(session).build()
        pf_nodes = [n for n in graph.nodes if n.kind == GraphNodeKind.PERSONAL_FACT]
        assert len(pf_nodes) == 1
        assert pf_nodes[0].label == "18 August 2005"
        vectors.close()

    @pytest.mark.asyncio
    async def test_no_commitment_node_for_birthday(self, tmp_path, session: Session) -> None:
        vectors = LocalQdrantStore(tmp_path / "qdrant")
        svc = PersonalFactService(session, vectors, DeterministicTestEmbedding())
        await svc.upsert(
            category=PersonalFactCategory.BIRTHDAY,
            attribute="date_of_birth",
            value="2005-08-18",
            display_value="18 August 2005",
        )
        session.commit()

        graph = KnowledgeGraphRepository(session).build()
        commitment_nodes = [n for n in graph.nodes if n.kind == GraphNodeKind.COMMITMENT]
        assert len(commitment_nodes) == 0
        vectors.close()

    @pytest.mark.asyncio
    async def test_multiple_personal_facts_produce_multiple_nodes(
        self, tmp_path, session: Session
    ) -> None:
        vectors = LocalQdrantStore(tmp_path / "qdrant")
        svc = PersonalFactService(session, vectors, DeterministicTestEmbedding())
        await svc.upsert(
            category=PersonalFactCategory.BIRTHDAY, attribute="date_of_birth", value="2005-08-18"
        )
        await svc.upsert(
            category=PersonalFactCategory.IDENTITY, attribute="full_name", value="Rayan"
        )
        await svc.upsert(
            category=PersonalFactCategory.EDUCATION, attribute="university", value="NMIT"
        )
        session.commit()

        graph = KnowledgeGraphRepository(session).build()
        pf_nodes = [n for n in graph.nodes if n.kind == GraphNodeKind.PERSONAL_FACT]
        assert len(pf_nodes) == 3
        vectors.close()

    @pytest.mark.asyncio
    async def test_personal_fact_node_in_graph_stats(self, tmp_path, session: Session) -> None:
        vectors = LocalQdrantStore(tmp_path / "qdrant")
        svc = PersonalFactService(session, vectors, DeterministicTestEmbedding())
        await svc.upsert(
            category=PersonalFactCategory.BIRTHDAY, attribute="date_of_birth", value="2005-08-18"
        )
        session.commit()

        graph = KnowledgeGraphRepository(session).build()
        assert graph.stats.personal_facts == 1
        vectors.close()

    @pytest.mark.asyncio
    async def test_personal_fact_records_present(self, tmp_path, session: Session) -> None:
        vectors = LocalQdrantStore(tmp_path / "qdrant")
        svc = PersonalFactService(session, vectors, DeterministicTestEmbedding())
        await svc.upsert(
            category=PersonalFactCategory.BIRTHDAY,
            attribute="date_of_birth",
            value="2005-08-18",
            display_value="18 August 2005",
        )
        session.commit()

        graph = KnowledgeGraphRepository(session).build()
        pf_records = [r for r in graph.records if r.source_type == "personal_fact"]
        assert len(pf_records) == 1
        assert "18 August 2005" in pf_records[0].content
        vectors.close()


# ===========================================================================
# Phase 5 — Graph audit-event suppression
# ===========================================================================


class TestGraphAuditEventSuppression:
    """'Commitment captured' must NOT appear as a graph node."""

    def test_created_event_not_in_graph(self, session: Session) -> None:
        commitment = Commitment(
            title="Submit report",
            status=CommitmentStatus.ACTIVE,
            source="test",
        )
        session.add(commitment)
        session.flush()
        # "created" is the audit-only event type that caused the orange nodes.
        session.add(
            CommitmentEvent(
                commitment_id=commitment.id,
                event_type="created",
                detail="Captured from user statement.",
            )
        )
        session.commit()

        graph = KnowledgeGraphRepository(session).build()
        node_labels = {n.label for n in graph.nodes}
        assert "Commitment captured" not in node_labels

    def test_completed_event_stays_in_graph(self, session: Session) -> None:
        commitment = Commitment(
            title="Finish essay",
            status=CommitmentStatus.COMPLETED,
            source="test",
        )
        session.add(commitment)
        session.flush()
        session.add(
            CommitmentEvent(
                commitment_id=commitment.id,
                event_type="completed",
                detail="Marked done.",
            )
        )
        session.commit()

        graph = KnowledgeGraphRepository(session).build()
        node_labels = {n.label for n in graph.nodes}
        assert "Commitment completed" in node_labels

    def test_updated_event_not_in_graph(self, session: Session) -> None:
        commitment = Commitment(
            title="Plan trip",
            status=CommitmentStatus.ACTIVE,
            source="test",
        )
        session.add(commitment)
        session.flush()
        session.add(
            CommitmentEvent(
                commitment_id=commitment.id,
                event_type="updated",
                detail="Status changed.",
            )
        )
        session.commit()

        graph = KnowledgeGraphRepository(session).build()
        node_labels = {n.label for n in graph.nodes}
        assert "Commitment updated" not in node_labels


# ===========================================================================
# Phase 7 — Migration helper
# ===========================================================================


class TestBirthdayMigration:
    """migrate_birthday_commitments() reclassification."""

    @pytest.mark.asyncio
    async def test_birthday_commitment_reclassified(self, tmp_path, session: Session) -> None:
        vectors = LocalQdrantStore(tmp_path / "qdrant")
        embedder = DeterministicTestEmbedding()

        # Simulate the wrong commitment that was created before this fix.
        bad = Commitment(
            title="User birthday celebration",
            description="Birthday reminder",
            evidence="18th aug 2005 is my birthday.",
            source_span="18th aug 2005 is my birthday.",
            status=CommitmentStatus.NEEDS_CONFIRMATION,
            source="assistant",
        )
        session.add(bad)
        session.commit()

        result = await migrate_birthday_commitments(session, vectors, embedder)

        assert result.reclassified == 1
        assert result.errors == []

        # Verify the commitment was cancelled.
        session.expire(bad)
        assert bad.status == CommitmentStatus.CANCELLED

        # Verify the personal fact was created.
        from sqlalchemy import select

        facts = list(session.scalars(select(PersonalFact)))
        assert len(facts) == 1
        assert facts[0].value == "2005-08-18"
        assert facts[0].display_value == "18 August 2005"
        assert facts[0].category == PersonalFactCategory.BIRTHDAY
        vectors.close()

    @pytest.mark.asyncio
    async def test_migration_is_idempotent(self, tmp_path, session: Session) -> None:
        vectors = LocalQdrantStore(tmp_path / "qdrant")
        embedder = DeterministicTestEmbedding()

        bad = Commitment(
            title="Birthday reminder",
            evidence="18th aug 2005 is my birthday.",
            source_span="18th aug 2005 is my birthday.",
            status=CommitmentStatus.NEEDS_CONFIRMATION,
            source="assistant",
        )
        session.add(bad)
        session.commit()

        # Run twice.
        r1 = await migrate_birthday_commitments(session, vectors, embedder)
        r2 = await migrate_birthday_commitments(session, vectors, embedder)

        assert r1.reclassified == 1
        # Second run: fact already exists, commitment already cancelled.
        assert r2.reclassified == 0 or r2.already_migrated == 0  # nothing new done

        from sqlalchemy import select

        facts = list(session.scalars(select(PersonalFact)))
        assert len(facts) == 1  # no duplicates
        vectors.close()

    @pytest.mark.asyncio
    async def test_unrelated_commitments_preserved(self, tmp_path, session: Session) -> None:
        vectors = LocalQdrantStore(tmp_path / "qdrant")
        embedder = DeterministicTestEmbedding()

        unrelated = Commitment(
            title="Submit report",
            description="Final report due Friday",
            status=CommitmentStatus.ACTIVE,
            source="test",
        )
        session.add(unrelated)
        session.commit()

        await migrate_birthday_commitments(session, vectors, embedder)

        session.expire(unrelated)
        assert unrelated.status == CommitmentStatus.ACTIVE  # untouched
        vectors.close()


# ===========================================================================
# Gateway birthday guard
# ===========================================================================


class TestGatewayBirthdayGuard:
    """_validate_result() must suppress birthday commitments."""

    def test_birthday_statement_produces_no_candidates(self) -> None:
        """The gateway validation stage must suppress candidates for birthday inputs."""
        from datetime import UTC, datetime

        from pactlyn.core.commitments import CaptureResult, CommitmentCandidate
        from pactlyn.llm.gateway import LLMGateway
        from pactlyn.storage.models import CommitmentType

        # Build a fake result as if the LLM produced a "birthday celebration" commitment.
        candidate = CommitmentCandidate(
            title="User birthday celebration",
            description="Birthday reminder",
            type=CommitmentType.DEADLINE,
            evidence="18th aug 2005 is my birthday.",
            source_span="18th aug 2005 is my birthday.",
            needs_confirmation=True,
        )
        fake_result = CaptureResult(candidates=[candidate], explanation="test")
        source = "18th aug 2005 is my birthday."
        now = datetime.now(UTC)

        validated = LLMGateway._validate_result(fake_result, source, now)
        assert validated.candidates == []
        assert "personal fact" in validated.explanation.lower()
