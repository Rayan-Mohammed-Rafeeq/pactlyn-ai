"""Document RAG service with cited answers and figure-aware retrieval."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from pactlyn.documents.indexing import DocumentIndexer
from pactlyn.llm.gateway import LLMGateway
from pactlyn.llm.interfaces import LLMUnavailable
from pactlyn.rag.retrieval import Evidence
from pactlyn.rag.service import GroundedAnswer, RAGService
from pactlyn.storage.models import Document, DocumentChunk, DocumentFigure


@dataclass(frozen=True)
class DocumentCitation:
    """Citation with document metadata for clickable references."""
    document_id: int
    document_name: str
    page_number: int | None
    section_title: str | None
    chunk_id: int | None
    figure_id: int | None
    content_preview: str


@dataclass(frozen=True)
class DocumentGroundedAnswer:
    """Answer with document citations that can be clicked to open pages."""
    answer: str
    citations: list[DocumentCitation]
    commitment_evidence: list[Evidence]  # Still include commitment context
    used_local_model: bool
    abstained: bool = False


class DocumentRAGService:
    """RAG service specialized for document queries with cited answers."""

    def __init__(
        self,
        session: Session,
        gateway: LLMGateway,
        indexer: DocumentIndexer,
        commitment_rag: RAGService | None = None,
    ):
        self.session = session
        self.gateway = gateway
        self.indexer = indexer
        self.commitment_rag = commitment_rag

    async def answer(
        self,
        question: str,
        *,
        limit: int = 8,
        include_figures: bool = True,
        include_commitments: bool = True,
    ) -> DocumentGroundedAnswer:
        """Answer a question using documents (chunks + figures) and optionally commitments.
        
        Args:
            question: User's question
            limit: Total number of document sources to retrieve
            include_figures: Whether to search figure descriptions
            include_commitments: Whether to include commitment context
        
        Returns:
            DocumentGroundedAnswer with citations pointing to specific pages
        """
        # Determine if this is document-focused or commitment-focused
        query_type = self._classify_query(question)
        
        # Search documents (chunks + figures)
        doc_evidence = await self._retrieve_document_evidence(
            question,
            limit=limit,
            include_figures=include_figures,
        )
        
        # Optionally include commitment context for hybrid queries
        commitment_evidence: list[Evidence] = []
        if include_commitments and query_type in {"hybrid", "commitment"}:
            if self.commitment_rag:
                try:
                    commitment_answer = await self.commitment_rag.answer(
                        question,
                        limit=3,  # Fewer commitment results
                    )
                    commitment_evidence = commitment_answer.evidence
                except Exception:
                    # Gracefully degrade if commitment retrieval fails
                    pass
        
        # Parse document evidence into citations
        citations = self._build_citations(doc_evidence)
        
        # If no evidence at all
        if not citations and not commitment_evidence:
            return DocumentGroundedAnswer(
                answer="I could not find supporting information in your documents or records.",
                citations=[],
                commitment_evidence=[],
                used_local_model=False,
                abstained=True,
            )
        
        # If document query but no document evidence
        if query_type == "document" and not citations:
            return DocumentGroundedAnswer(
                answer="I could not find that information in your uploaded documents.",
                citations=[],
                commitment_evidence=commitment_evidence,
                used_local_model=False,
                abstained=True,
            )
        
        # Generate answer with citations
        return await self._generate_cited_answer(
            question,
            citations,
            commitment_evidence,
        )

    async def _retrieve_document_evidence(
        self,
        query: str,
        *,
        limit: int,
        include_figures: bool,
    ) -> list[dict]:
        """Retrieve document chunks and optionally figures.
        
        Returns list of dicts with 'type', 'chunk' or 'figure', 'score', 'content'
        """
        chunk_limit = limit if not include_figures else max(limit // 2, 3)
        figure_limit = limit - chunk_limit if include_figures else 0
        
        results: list[dict] = []
        
        # Search document chunks
        try:
            chunk_results = await self.indexer.search_documents(
                query,
                limit=chunk_limit,
            )
            for hit in chunk_results:
                results.append({
                    "type": "chunk",
                    "data": hit,
                    "score": hit.get("score", 0.0),
                    "content": hit.get("text", ""),
                })
        except Exception:
            # Gracefully handle search failures
            pass
        
        # Search figure descriptions if requested
        if include_figures:
            try:
                figure_results = await self._search_figures(query, limit=figure_limit)
                for fig_data in figure_results:
                    results.append({
                        "type": "figure",
                        "data": fig_data,
                        "score": fig_data.get("score", 0.0),
                        "content": fig_data.get("description", ""),
                    })
            except Exception:
                # Gracefully handle figure search failures
                pass
        
        # Sort by score
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    async def _search_figures(self, query: str, *, limit: int) -> list[dict]:
        """Search figure descriptions using vector similarity.
        
        Returns list of dicts with figure metadata and scores.
        """
        # Get figure embeddings from indexer's vector store
        query_vector = await self.indexer.embedder.embed([query])
        
        # Search in the same collection using metadata filter
        hits = self.indexer.vectors.search(
            collection=self.indexer.collection,
            vector=query_vector[0],
            limit=limit * 3,  # Get more candidates
            query_filter={"chunk_type": "figure"},  # Filter for figures only
        )
        
        # Load figure objects from database
        results = []
        for hit in hits[:limit]:
            figure_id = hit.payload.get("figure_id")
            if not figure_id:
                continue
            
            figure = self.session.get(DocumentFigure, int(figure_id))
            if not figure:
                continue
            
            results.append({
                "figure_id": figure.id,
                "document_id": figure.document_id,
                "page_number": figure.page_number,
                "caption": figure.caption,
                "description": figure.description,
                "score": hit.score,
            })
        
        return results

    def _build_citations(self, evidence: list[dict]) -> list[DocumentCitation]:
        """Convert raw evidence into structured citations with document metadata."""
        citations: list[DocumentCitation] = []
        
        for item in evidence:
            if item["type"] == "chunk":
                hit = item["data"]
                # hit is a dict from search_documents with keys:
                # score, document_id, chunk_index, page_numbers, section_heading, text, filename
                document_id = hit.get("document_id")
                if not document_id:
                    continue
                
                # Get page numbers from the list
                # For multi-page chunks, prefer middle page or most relevant page
                page_numbers = hit.get("page_numbers", [])
                if not page_numbers:
                    page_number = None
                elif len(page_numbers) == 1:
                    page_number = page_numbers[0]
                else:
                    # For multi-page chunks, use the middle page as most representative
                    page_number = page_numbers[len(page_numbers) // 2]
                
                # Look up chunk ID from database for reference
                chunk = (
                    self.session.query(DocumentChunk)
                    .filter(
                        DocumentChunk.document_id == document_id,
                        DocumentChunk.chunk_index == hit.get("chunk_index"),
                    )
                    .first()
                )
                
                citations.append(DocumentCitation(
                    document_id=document_id,
                    document_name=hit.get("filename", "unknown"),
                    page_number=page_number,
                    section_title=hit.get("section_heading"),
                    chunk_id=chunk.id if chunk else None,
                    figure_id=None,
                    content_preview=hit.get("text", "")[:1000],  # Increased to 1000 chars for better context
                ))
            
            elif item["type"] == "figure":
                fig_data = item["data"]
                figure_id = fig_data.get("figure_id")
                if not figure_id:
                    continue
                
                figure = self.session.get(DocumentFigure, figure_id)
                if not figure:
                    continue
                
                doc = self.session.get(Document, figure.document_id)
                if not doc:
                    continue
                
                citations.append(DocumentCitation(
                    document_id=doc.id,
                    document_name=doc.filename,
                    page_number=figure.page_number,
                    section_title=None,
                    chunk_id=None,
                    figure_id=figure.id,
                    content_preview=f"Figure: {figure.caption or 'Untitled'}\n{figure.description[:150]}",
                ))
        
        return citations

    async def _generate_cited_answer(
        self,
        question: str,
        citations: list[DocumentCitation],
        commitment_evidence: list[Evidence],
    ) -> DocumentGroundedAnswer:
        """Generate an answer using LLM with proper citation instructions."""
        import logging
        logger = logging.getLogger(__name__)
        
        provider = self.gateway.local
        if not await provider.available():
            raise LLMUnavailable(f"{provider.name} is unavailable")
        
        # Build context with citation markers
        doc_context_parts = []
        for idx, citation in enumerate(citations, start=1):
            citation_id = f"[doc{idx}]"
            if citation.figure_id:
                doc_context_parts.append(
                    f"{citation_id} {citation.document_name} (page {citation.page_number})\n"
                    f"Figure: {citation.content_preview}"
                )
            else:
                section = f" - {citation.section_title}" if citation.section_title else ""
                doc_context_parts.append(
                    f"{citation_id} {citation.document_name} (page {citation.page_number}){section}\n"
                    f"{citation.content_preview}"
                )
        
        doc_context = "\n\n".join(doc_context_parts)
        
        # Add commitment context if present
        commitment_context = ""
        if commitment_evidence:
            commitment_parts = [
                f"[source:{item.source_type}/{item.source_id}]\n{item.content}"
                for item in commitment_evidence
            ]
            commitment_context = "\n\nAdditional context from your commitments:\n" + "\n\n".join(commitment_parts)
        
        full_context = doc_context + commitment_context
        
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a document assistant. Answer the user's question using ONLY the provided document excerpts. "
                    "\n\n"
                    "CRITICAL CITATION RULES:\n"
                    "1. You MUST cite every factual claim using the exact markers provided: [doc1], [doc2], [doc3], etc.\n"
                    "2. Place citation markers immediately after the claim: 'Paris is the capital of France [doc1].'\n"
                    "3. If a document does not support your answer, do NOT cite it.\n"
                    "4. If the documents do not contain enough information to answer, say 'The provided documents do not contain this information.'\n"
                    "5. NEVER invent facts, page numbers, or citation markers not provided to you.\n"
                    "\n"
                    "Available citation markers in your evidence below: " + ", ".join(f"[doc{i}]" for i in range(1, len(citations) + 1))
                ),
            },
            {
                "role": "user",
                "content": f"Question: {question}\n\nDocument evidence:\n{full_context}\n\nAnswer the question and cite your sources:",
            },
        ]
        
        # Log for debugging
        logger.info(f"Sending to LLM - Question: {question}")
        logger.info(f"Citations available: {len(citations)}")
        logger.info(f"Context preview (first 300 chars): {full_context[:300]}")
        logger.info(f"FULL CONTEXT:\n{full_context}\n---END CONTEXT---")
        
        try:
            answer = await asyncio.wait_for(provider.complete(messages), timeout=300)
        except (LLMUnavailable, TimeoutError) as exc:
            raise LLMUnavailable(f"Local document answer failed: {exc}") from exc
        
        # Log for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"LLM raw answer (first 300 chars): {answer[:300]}")
        
        # Verify citations are grounded (check for hallucinated citation markers)
        is_grounded = self._answer_citations_are_grounded(answer, len(citations))
        logger.info(f"Citation grounding check: {is_grounded} (citations available: {len(citations)})")
        
        # Check if answer is actually an abstention
        abstention_phrases = [
            "don't have enough",
            "could not find",
            "insufficient",
            "not available",
            "cannot determine",
            "do not contain",
            "does not contain",
        ]
        is_abstention = any(phrase in answer.lower() for phrase in abstention_phrases)
        
        if not is_grounded:
            logger.warning(f"Answer failed grounding validation. Answer length: {len(answer)}, Expected citations: {len(citations)}")
            return DocumentGroundedAnswer(
                answer="I don't have enough document evidence to provide a properly cited answer.",
                citations=citations,
                commitment_evidence=commitment_evidence,
                used_local_model=True,
                abstained=True,
            )
        
        return DocumentGroundedAnswer(
            answer=answer,
            citations=citations,
            commitment_evidence=commitment_evidence,
            used_local_model=True,
            abstained=is_abstention,  # Set flag based on content analysis
        )

    def _classify_query(self, question: str) -> Literal["document", "commitment", "hybrid"]:
        """Classify whether query is about documents, commitments, or both."""
        doc_keywords = {
            "document", "pdf", "paper", "report", "figure", "chart", "table",
            "page", "section", "chapter", "article", "study", "file", "uploaded",
        }
        commitment_keywords = {
            "due", "waiting", "commitment", "promised", "scheduled", "meeting",
            "deadline", "responsible", "assigned", "task", "follow-up",
        }
        
        question_lower = question.lower()
        
        has_doc = any(keyword in question_lower for keyword in doc_keywords)
        has_commitment = any(keyword in question_lower for keyword in commitment_keywords)
        
        if has_doc and not has_commitment:
            return "document"
        if has_commitment and not has_doc:
            return "commitment"
        
        # Default to hybrid if ambiguous or both
        return "hybrid"

    @staticmethod
    def _answer_citations_are_grounded(answer: str, citation_count: int) -> bool:
        """Check that the answer only uses valid citation markers."""
        import re
        import logging
        logger = logging.getLogger(__name__)
        
        # Find all citation markers in the answer
        cited_indices = set()
        for match in re.finditer(r"\[doc(\d+)\]", answer):
            cited_indices.add(int(match.group(1)))
        
        logger.info(f"Found citation markers in answer: {cited_indices} (available: 1-{citation_count})")
        
        # Check all cited indices are valid
        if cited_indices and max(cited_indices) > citation_count:
            logger.warning(f"Hallucinated citation detected: max index {max(cited_indices)} > {citation_count}")
            return False  # Hallucinated citation
        
        # If answer has factual content but no citations, that's suspicious
        # (unless it's an abstention message)
        abstention_phrases = [
            "don't have enough",
            "could not find",
            "insufficient",
            "not available",
            "cannot determine",
            "do not contain",
        ]
        has_abstention = any(phrase in answer.lower() for phrase in abstention_phrases)
        
        word_count = len(answer.split())
        
        if not has_abstention and not cited_indices and word_count > 20:
            logger.warning(f"Substantial answer ({word_count} words) with no citations and no abstention")
            return False  # Substantial answer with no citations
        
        logger.info(f"Answer is grounded: {len(cited_indices)} citations, {word_count} words, abstention={has_abstention}")
        return True
