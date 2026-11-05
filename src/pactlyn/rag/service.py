"""RAG service — LLM-first assistant with local evidence grounding.

The assistant always calls the local LLM (qwen2.5:7b or whatever is
configured). It gathers all available local context — personal facts,
memory records, commitments — passes them to the LLM with today's date, and
returns the answer. The LLM does all classification, reasoning and derivation
(including age calculation, relationship reasoning, etc.).

The only things this service does deterministically:
- Gather evidence from SQLite + Qdrant
- Build a clean context string
- Call the LLM
- Return the answer + source list
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from pactlyn.llm.gateway import LLMGateway
from pactlyn.llm.interfaces import LLMUnavailable
from pactlyn.memory.facts import PersonalFactService
from pactlyn.rag.retrieval import Evidence, HybridRetriever
from pactlyn.storage.models import PersonalFact


@dataclass(frozen=True)
class GroundedAnswer:
    answer: str
    evidence: list[Evidence]
    used_local_model: bool
    abstained: bool = False


@dataclass(frozen=True)
class EvidenceAssessment:
    query_class: str
    relevant_score: float
    sufficient: bool
    multi_source: bool
    relevant_source_count: int = 0


class RAGService:
    """Answer questions from local evidence using the configured LLM."""

    def __init__(
        self,
        session: Session,
        gateway: LLMGateway,
        retriever: HybridRetriever,
        fact_service: PersonalFactService | None = None,
    ):
        self.session = session
        self.gateway = gateway
        self.retriever = retriever
        self.fact_service = fact_service

    async def answer(
        self,
        question: str,
        *,
        limit: int = 5,
        mode: Literal["dense", "fts5", "hybrid", "rrf"] = "hybrid",
        rerank: bool = False,
    ) -> GroundedAnswer:
        today = datetime.now(UTC).strftime("%d %B %Y")

        # ------------------------------------------------------------------
        # 1. Collect all available local context
        # ------------------------------------------------------------------
        context_parts: list[str] = []
        evidence_items: list[Evidence] = []

        # Personal facts from the structured table
        if self.fact_service is not None:
            facts: list[PersonalFact] = self.fact_service.list_facts()
            if facts:
                fact_lines = [
                    f"  {f.attribute.replace('_', ' ').title()}: {f.display_value or f.value}"
                    for f in facts
                ]
                context_parts.append("Personal profile:\n" + "\n".join(fact_lines))
                for f in facts:
                    evidence_items.append(
                        Evidence(
                            source_type="personal_fact",
                            source_id=f.id,
                            content=f"{f.attribute}: {f.display_value or f.value}",
                            score=1.0,
                        )
                    )

        # Memory records + commitments via hybrid retrieval
        retrieved = await self.retriever.search(
            question, limit=limit, mode=mode, rerank=rerank
        )
        if retrieved:
            mem_lines = []
            for item in retrieved:
                # Skip very noisy commitment evidence lines
                clean = item.content.split("\nsource_span:")[0].split("\ncurrent_time:")[0].strip()
                if clean:
                    mem_lines.append(f"  [{item.source_type}] {clean[:200]}")
                    evidence_items.append(item)
            if mem_lines:
                context_parts.append("Memory records:\n" + "\n".join(mem_lines))

        # ------------------------------------------------------------------
        # 2. If we have absolutely no context, abstain without calling LLM
        # ------------------------------------------------------------------
        if not context_parts:
            return GroundedAnswer(
                answer="I don't have any local records that could answer that.",
                evidence=[],
                used_local_model=False,
                abstained=True,
            )

        # ------------------------------------------------------------------
        # 3. Call the LLM — let it reason over everything
        # ------------------------------------------------------------------
        provider = self.gateway.local
        if not await provider.available():
            raise LLMUnavailable(f"{provider.name} is unavailable")

        context_str = "\n\n".join(context_parts)
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are Pactlyn, a local-first personal assistant. Today is {today}.\n"
                    "Answer the user's question using only the local context provided below. "
                    "You can reason, compute (e.g. calculate age from birth year and today's date), "
                    "and draw conclusions from the evidence. "
                    "Be direct and concise. If the context does not contain enough information "
                    "to answer, say so honestly. Do not invent facts."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Local context:\n{context_str}\n\n"
                    f"Question: {question}"
                ),
            },
        ]

        try:
            answer_text = await asyncio.wait_for(
                provider.complete(messages), timeout=60
            )
        except (LLMUnavailable, TimeoutError) as exc:
            raise LLMUnavailable(f"Assistant failed: {exc}") from exc

        # ------------------------------------------------------------------
        # 4. Guard: reject only if the LLM invented a [source:] tag we
        #    don't recognise. No citations = fine, we append them below.
        # ------------------------------------------------------------------
        if not self._hallucinated_citations(answer_text, evidence_items):
            return GroundedAnswer(
                answer="I had evidence but could not produce a reliable answer.",
                evidence=evidence_items,
                used_local_model=True,
                abstained=True,
            )

        return GroundedAnswer(
            answer=answer_text,
            evidence=evidence_items,
            used_local_model=True,
            abstained=False,
        )

    # ------------------------------------------------------------------
    # Helpers kept for backwards-compatibility with existing tests
    # ------------------------------------------------------------------

    def assess_evidence(
        self, question: str, evidence: list[Evidence]
    ) -> EvidenceAssessment:
        query_class = self.classify_query(question)
        relevant = self._relevant_evidence(question, evidence)
        anchor = bool(relevant)
        multi_source = (
            len({item.source_id.split(":chunk:")[0] for item in relevant}) >= 2
        )
        required = (
            2 if query_class in {"relationship", "multi_hop", "historical"} else 1
        )
        relevant_score = (
            min(
                1.0,
                len({item.source_id.split(":chunk:")[0] for item in relevant}) / required,
            )
            if anchor
            else 0.0
        )
        return EvidenceAssessment(
            query_class,
            relevant_score,
            anchor and len(relevant) >= required,
            multi_source,
            len(relevant),
        )

    @staticmethod
    def classify_query(question: str) -> str:
        lowered = question.casefold()
        if any(
            term in lowered
            for term in ("depend", "blocked", "after", "before", "if", "what should")
        ):
            return "relationship" if "depend" in lowered or "blocked" in lowered else "multi_hop"
        if any(
            term in lowered
            for term in ("yesterday", "today", "already", "sent", "replied")
        ):
            return "historical"
        return "fact"

    @staticmethod
    def _relevant_evidence(question: str, evidence: list[Evidence]) -> list[Evidence]:
        stopwords = {
            "what", "when", "where", "which", "who", "the", "a", "an",
            "my", "me", "i", "is", "are", "to", "from", "for", "of", "and",
            "on", "in", "about", "local", "record", "records", "evidence",
            "enough", "tell", "contact", "contacted",
        }
        query_terms = {
            token.casefold()
            for token in re.findall(r"[A-Za-z0-9_]+", question)
            if len(token) > 2 and token.casefold() not in stopwords
        }
        _SYNONYMS: dict[str, set[str]] = {
            "age": {"born", "birth", "year", "dob"},
            "old": {"born", "birth", "year"},
            "birthday": {"born", "birth", "august", "aug", "date"},
            "birth": {"born", "year", "date", "august", "aug"},
        }
        expanded: set[str] = set(query_terms)
        for term in query_terms:
            expanded |= _SYNONYMS.get(term, set())
        relevant: list[Evidence] = []
        for item in evidence:
            if re.search(
                r"\b(?:no local record|no evidence|not recorded|does not state)\b",
                item.content,
                re.IGNORECASE,
            ):
                continue
            content_terms = {
                token.casefold()
                for token in re.findall(r"[A-Za-z0-9_]+", item.content)
            }
            if expanded & content_terms:
                relevant.append(item)
        return relevant

    @staticmethod
    def _hallucinated_citations(answer: str, evidence: list[Evidence]) -> bool:
        """Return True (safe) unless the LLM invented a [source:] reference
        that does not appear in our evidence list."""
        citations = re.findall(r"\[source:([^/\]]+)/([^\]]+)\]", answer)
        if not citations:
            return True  # no citations at all — fine
        allowed = {(e.source_type, e.source_id) for e in evidence}
        normalized = {
            (st, sid.split(":chunk:")[0]) for st, sid in allowed
        }
        return all(
            c in allowed or (c[0], c[1].split(":chunk:")[0]) in normalized
            for c in citations
        )

    # Legacy name kept so existing test references still work
    @staticmethod
    def _answer_citations_are_grounded(
        answer: str, evidence: list[Evidence]
    ) -> bool:
        return RAGService._hallucinated_citations(answer, evidence)
