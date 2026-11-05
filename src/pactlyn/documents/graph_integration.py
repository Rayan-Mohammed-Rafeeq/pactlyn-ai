"""Document-to-graph integration: Extract entities and relationships from documents."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from pactlyn.llm.gateway import LLMGateway
from pactlyn.llm.interfaces import LLMUnavailable
from pactlyn.storage.models import (
    Commitment,
    Contact,
    Document,
    DocumentChunk,
    MemoryKind,
    MemoryRecord,
)


@dataclass(frozen=True)
class ExtractedEntity:
    """Entity extracted from document content."""
    entity_type: Literal["person", "organization", "project", "event", "concept"]
    name: str
    context: str  # Surrounding text
    document_id: str
    page_number: int | None
    chunk_id: str
    confidence: float = 0.8


@dataclass(frozen=True)
class ExtractedRelationship:
    """Relationship extracted from document content."""
    subject: str  # Entity name
    predicate: str  # Relationship type
    object: str  # Related entity name
    context: str  # Evidence text
    document_id: str
    page_number: int | None
    chunk_id: str
    confidence: float = 0.7


@dataclass(frozen=True)
class DocumentGraphExtraction:
    """Complete extraction result from a document."""
    document_id: str
    document_name: str
    entities: list[ExtractedEntity]
    relationships: list[ExtractedRelationship]
    extraction_timestamp: datetime
    used_local_model: bool


class DocumentGraphIntegration:
    """Service for integrating documents into the knowledge graph."""
    
    def __init__(self, session: Session, gateway: LLMGateway):
        self.session = session
        self.gateway = gateway
    
    async def extract_from_document(
        self,
        document_id: str,
        *,
        chunk_limit: int = 10,
    ) -> DocumentGraphExtraction:
        """Extract entities and relationships from a document.
        
        Args:
            document_id: Document to process
            chunk_limit: Maximum chunks to process
        
        Returns:
            DocumentGraphExtraction with entities and relationships
        """
        # Get document
        doc = self.session.get(Document, document_id)
        if not doc:
            raise ValueError(f"Document {document_id} not found")
        
        # Get chunks for extraction
        chunks = (
            self.session.query(DocumentChunk)
            .filter(
                DocumentChunk.document_id == document_id,
                DocumentChunk.chunk_type == "text",
            )
            .order_by(DocumentChunk.chunk_index)
            .limit(chunk_limit)
            .all()
        )
        
        if not chunks:
            return DocumentGraphExtraction(
                document_id=document_id,
                document_name=doc.filename,
                entities=[],
                relationships=[],
                extraction_timestamp=datetime.now(UTC),
                used_local_model=False,
            )
        
        # Extract from each chunk
        all_entities: list[ExtractedEntity] = []
        all_relationships: list[ExtractedRelationship] = []
        used_local = False
        
        for chunk in chunks:
            try:
                result = await self._extract_from_chunk(chunk, doc.filename)
                all_entities.extend(result["entities"])
                all_relationships.extend(result["relationships"])
                used_local = True
            except Exception:
                # Continue on failure
                continue
        
        # Deduplicate entities by name (case-insensitive)
        entities_by_name: dict[str, ExtractedEntity] = {}
        for entity in all_entities:
            key = entity.name.lower().strip()
            if key not in entities_by_name:
                entities_by_name[key] = entity
        
        return DocumentGraphExtraction(
            document_id=document_id,
            document_name=doc.filename,
            entities=list(entities_by_name.values()),
            relationships=all_relationships,
            extraction_timestamp=datetime.now(UTC),
            used_local_model=used_local,
        )
    
    async def _extract_from_chunk(
        self,
        chunk: DocumentChunk,
        document_name: str,
    ) -> dict:
        """Extract entities and relationships from a single chunk."""
        provider = self.gateway.local
        if not await provider.available():
            raise LLMUnavailable("Local model unavailable")
        
        # Get page number
        try:
            page_nums = json.loads(chunk.page_numbers) if chunk.page_numbers else []
            page_number = page_nums[0] if page_nums else None
        except Exception:
            page_number = None
        
        # Build extraction prompt
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract named entities and relationships from document text. "
                    "Focus on people, organizations, projects, and key concepts. "
                    "Output valid JSON only. Format:\n"
                    '{\n'
                    '  "entities": [{"type": "person|organization|project|event|concept", "name": "...", "context": "..."}],\n'
                    '  "relationships": [{"subject": "...", "predicate": "...", "object": "...", "context": "..."}]\n'
                    '}\n'
                    "Rules:\n"
                    "1. Extract only explicitly mentioned entities\n"
                    "2. Use specific names (not pronouns or generics)\n"
                    "3. Preserve exact names from text\n"
                    "4. Relationships must connect named entities\n"
                    "5. Context should be the verbatim quote\n"
                    "6. Limit to 10 entities and 10 relationships per chunk\n"
                    "7. If no entities found, return empty arrays"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Document: {document_name}\n"
                    f"Page: {page_number or 'unknown'}\n\n"
                    f"Text:\n{chunk.content[:1500]}\n\n"
                    "Extract entities and relationships:"
                ),
            },
        ]
        
        try:
            response = await asyncio.wait_for(
                provider.complete(messages),
                timeout=30,
            )
        except (LLMUnavailable, TimeoutError) as exc:
            raise LLMUnavailable(f"Extraction failed: {exc}") from exc
        
        # Parse JSON response
        try:
            # Try to extract JSON from response
            response_clean = response.strip()
            if "```json" in response_clean:
                # Extract from code block
                start = response_clean.find("```json") + 7
                end = response_clean.find("```", start)
                response_clean = response_clean[start:end].strip()
            elif "```" in response_clean:
                # Extract from generic code block
                start = response_clean.find("```") + 3
                end = response_clean.find("```", start)
                response_clean = response_clean[start:end].strip()
            
            data = json.loads(response_clean)
        except json.JSONDecodeError:
            # Fallback: empty extraction
            data = {"entities": [], "relationships": []}
        
        # Convert to dataclasses
        entities = []
        for ent in data.get("entities", [])[:10]:
            if not isinstance(ent, dict):
                continue
            
            entity_type = ent.get("type", "concept")
            if entity_type not in {"person", "organization", "project", "event", "concept"}:
                entity_type = "concept"
            
            name = ent.get("name", "").strip()
            if not name or len(name) < 2:
                continue
            
            entities.append(ExtractedEntity(
                entity_type=entity_type,
                name=name,
                context=ent.get("context", "")[:500],
                document_id=chunk.document_id,
                page_number=page_number,
                chunk_id=chunk.id,
                confidence=0.8,
            ))
        
        relationships = []
        for rel in data.get("relationships", [])[:10]:
            if not isinstance(rel, dict):
                continue
            
            subject = rel.get("subject", "").strip()
            predicate = rel.get("predicate", "").strip()
            obj = rel.get("object", "").strip()
            
            if not (subject and predicate and obj):
                continue
            
            relationships.append(ExtractedRelationship(
                subject=subject,
                predicate=predicate,
                object=obj,
                context=rel.get("context", "")[:500],
                document_id=chunk.document_id,
                page_number=page_number,
                chunk_id=chunk.id,
                confidence=0.7,
            ))
        
        return {"entities": entities, "relationships": relationships}
    
    def link_to_existing_contacts(
        self,
        entities: list[ExtractedEntity],
    ) -> dict[str, str]:
        """Match extracted person entities to existing contacts.
        
        Returns dict mapping entity name to contact ID.
        """
        # Get all contacts
        contacts = self.session.query(Contact).all()
        
        matches: dict[str, str] = {}
        
        for entity in entities:
            if entity.entity_type != "person":
                continue
            
            entity_name_lower = entity.name.lower().strip()
            
            # Try to match by name
            for contact in contacts:
                contact_name = contact.name or ""
                if not contact_name:
                    continue
                
                contact_name_lower = contact_name.lower().strip()
                
                # Exact match
                if entity_name_lower == contact_name_lower:
                    matches[entity.name] = contact.id
                    break
                
                # Partial match (one contains the other)
                if (entity_name_lower in contact_name_lower or 
                    contact_name_lower in entity_name_lower):
                    matches[entity.name] = contact.id
                    break
        
        return matches
    
    def create_memory_records(
        self,
        extraction: DocumentGraphExtraction,
        *,
        user_verified: bool = False,
    ) -> list[str]:
        """Create memory records for extracted entities.
        
        Args:
            extraction: Extraction result
            user_verified: Whether user has reviewed the extraction
        
        Returns:
            List of created memory record IDs
        """
        memory_ids: list[str] = []
        
        # Create semantic memories for key entities
        for entity in extraction.entities:
            # Skip low-confidence or generic entities
            if entity.confidence < 0.6:
                continue
            
            if entity.entity_type in {"concept"} and len(entity.name) < 4:
                continue
            
            # Create memory content
            page_ref = f" (page {entity.page_number})" if entity.page_number else ""
            content = (
                f"{entity.entity_type.title()}: {entity.name}\n"
                f"From {extraction.document_name}{page_ref}\n"
                f"Context: {entity.context[:200]}"
            )
            
            memory = MemoryRecord(
                kind=MemoryKind.SEMANTIC,
                content=content,
                source_type="document",
                source_id=f"{entity.document_id}:chunk:{entity.chunk_id}",
                confidence=entity.confidence,
                user_verified=user_verified,
                indexed=False,  # Will be indexed by background process
            )
            
            self.session.add(memory)
            self.session.flush()
            memory_ids.append(memory.id)
        
        return memory_ids
    
    def link_to_commitments(
        self,
        extraction: DocumentGraphExtraction,
        keywords: list[str],
    ) -> list[tuple[str, str]]:
        """Find commitments mentioned in document.
        
        Args:
            extraction: Extraction result
            keywords: Keywords to match (from entities/relationships)
        
        Returns:
            List of (commitment_id, evidence_text) tuples
        """
        if not keywords:
            return []
        
        # Get active commitments
        commitments = self.session.query(Commitment).filter(
            Commitment.deleted_at.is_(None)
        ).all()
        
        matches: list[tuple[str, str]] = []
        
        for commitment in commitments:
            # Check if commitment description mentions any keywords
            desc_lower = commitment.description.lower()
            
            for keyword in keywords:
                if keyword.lower() in desc_lower:
                    # Find which entity/relationship mentioned this
                    evidence = ""
                    for entity in extraction.entities:
                        if keyword.lower() in entity.name.lower():
                            evidence = entity.context
                            break
                    
                    matches.append((commitment.id, evidence))
                    break  # One match per commitment
        
        return matches[:10]  # Limit matches
