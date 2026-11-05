"""Document indexing service: chunking, embeddings, and Qdrant storage.

Integrates with Phase 5 background processing pipeline.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from pactlyn.documents.chunking import ChunkingConfig, DocumentChunk, DocumentChunker
from pactlyn.llm.interfaces import EmbeddingUnavailable
from pactlyn.rag.embeddings import record_embedding_dimension
from pactlyn.storage.models import Document, DocumentChunk as DBChunk, DocumentFigure
from pactlyn.vectorstore.collections import COLLECTION_DOCUMENTS
from pactlyn.vectorstore.interface import VectorStore

logger = logging.getLogger(__name__)


class DocumentIndexer:
    """Index documents for semantic search."""

    def __init__(
        self,
        db_session_factory: sessionmaker[Session],
        vector_store: VectorStore,
        embedding_provider: Any,  # EmbeddingProvider protocol
    ):
        """Initialize document indexer.

        Args:
            db_session_factory: Database session factory
            vector_store: Qdrant vector store
            embedding_provider: Embedding model provider (e.g., OllamaProvider)
        """
        self.db_factory = db_session_factory
        self.vectors = vector_store
        self.embedder = embedding_provider
        self.chunker = DocumentChunker(ChunkingConfig())

    def index_document(
        self,
        document_id: str,
        text: str,
        page_count: int | None = None,
    ) -> int:
        """Index a document: chunk text, generate embeddings, store in Qdrant.

        Args:
            document_id: Document ID
            text: Extracted document text
            page_count: Number of pages

        Returns:
            Number of chunks indexed

        Raises:
            EmbeddingUnavailable: If embedding generation fails
        """
        logger.info(f"Indexing document {document_id}")

        # 1. Chunk the document
        chunks = self.chunker.chunk_document(text=text, page_count=page_count)
        logger.info(f"Created {len(chunks)} chunks for document {document_id}")

        if not chunks:
            logger.warning(f"No chunks created for document {document_id}")
            return 0

        # 2. Generate embeddings
        chunk_texts = [chunk.text for chunk in chunks]
        
        try:
            import asyncio
            # Run async embedding in sync context
            vectors = asyncio.run(self.embedder.embed(chunk_texts))
        except EmbeddingUnavailable as e:
            logger.error(f"Embedding generation failed for document {document_id}: {e}")
            raise

        if len(vectors) != len(chunks):
            raise ValueError(
                f"Embedding count mismatch: got {len(vectors)} vectors for {len(chunks)} chunks"
            )

        # Record embedding dimension
        if vectors and hasattr(self.embedder, "dimension") and self.embedder.dimension:
            session = self.db_factory()
            try:
                record_embedding_dimension(
                    session,
                    self.embedder.model_name,
                    self.embedder.dimension,
                )
            finally:
                session.close()

        # 3. Store chunks in SQLite
        session = self.db_factory()
        try:
            # Remove existing chunks for this document
            session.query(DBChunk).filter(DBChunk.document_id == document_id).delete()

            # Create new chunk records
            for chunk, vector in zip(chunks, vectors):
                # Generate consistent UUID for vector ID
                import hashlib
                import uuid
                
                point_id_source = f"{document_id}_chunk_{chunk.chunk_index}"
                point_id_hash = hashlib.md5(point_id_source.encode()).digest()
                vector_id = str(uuid.UUID(bytes=point_id_hash))
                
                db_chunk = DBChunk(
                    document_id=document_id,
                    content=chunk.text,
                    page_numbers=json.dumps(chunk.page_numbers),
                    section_heading=chunk.section_heading,
                    chunk_index=chunk.chunk_index,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    chunk_type=chunk.chunk_type,
                    indexed=True,
                    vector_id=vector_id,
                )
                session.add(db_chunk)

            session.commit()
            logger.info(f"Stored {len(chunks)} chunks in SQLite for document {document_id}")

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to store chunks in SQLite: {e}")
            raise
        finally:
            session.close()

        # 4. Index vectors in Qdrant
        indexed_count = 0
        for chunk, vector in zip(chunks, vectors):
            # Generate UUID for point ID from document ID and chunk index
            import hashlib
            import uuid
            
            point_id_source = f"{document_id}_chunk_{chunk.chunk_index}"
            # Create deterministic UUID from source string
            point_id_hash = hashlib.md5(point_id_source.encode()).digest()
            point_id = str(uuid.UUID(bytes=point_id_hash))

            # Get document filename
            session = self.db_factory()
            try:
                doc = session.query(Document).get(document_id)
                filename = doc.filename if doc else "unknown"
            finally:
                session.close()

            payload = {
                "document_id": document_id,
                "chunk_index": chunk.chunk_index,
                "page_numbers": chunk.page_numbers,
                "section_heading": chunk.section_heading or "",
                "chunk_type": chunk.chunk_type,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "text": chunk.text[:500],  # Store preview for display
                "filename": filename,
            }

            try:
                self.vectors.upsert(
                    collection=COLLECTION_DOCUMENTS,
                    point_id=point_id,
                    vector=vector,
                    payload=payload,
                )
                indexed_count += 1
            except Exception as e:
                logger.error(f"Failed to index chunk {point_id}: {e}")
                # Continue with other chunks

        logger.info(f"Indexed {indexed_count}/{len(chunks)} chunks in Qdrant for document {document_id}")

        return indexed_count

    def delete_document_index(self, document_id: str):
        """Remove document from index.

        Args:
            document_id: Document ID to remove
        """
        logger.info(f"Deleting index for document {document_id}")

        # Get all chunk IDs from SQLite
        session = self.db_factory()
        try:
            chunks = (
                session.query(DBChunk)
                .filter(DBChunk.document_id == document_id)
                .all()
            )

            # Delete from Qdrant
            for chunk in chunks:
                if chunk.vector_id:
                    try:
                        self.vectors.delete(
                            collection=COLLECTION_DOCUMENTS,
                            point_id=chunk.vector_id,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to delete vector {chunk.vector_id}: {e}")

            # Delete from SQLite
            session.query(DBChunk).filter(DBChunk.document_id == document_id).delete()
            session.commit()

            logger.info(f"Deleted {len(chunks)} chunks for document {document_id}")

        finally:
            session.close()

    async def search_documents(
        self,
        query: str,
        limit: int = 5,
        document_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search documents semantically.

        Args:
            query: Search query text
            limit: Maximum results to return
            document_id: Optional filter to specific document

        Returns:
            List of search results with scores and metadata
        """
        # Generate query embedding
        try:
            query_vectors = await self.embedder.embed([query])
            if not query_vectors:
                raise EmbeddingUnavailable("No embedding generated for query")
            query_vector = query_vectors[0]
        except EmbeddingUnavailable as e:
            logger.error(f"Query embedding failed: {e}")
            return []

        # Search Qdrant
        query_filter = {"document_id": document_id} if document_id else None

        try:
            hits = self.vectors.search(
                collection=COLLECTION_DOCUMENTS,
                vector=query_vector,
                limit=limit,
                query_filter=query_filter,
            )
        except Exception as e:
            logger.error(f"Qdrant search failed: {e}")
            return []

        # Enrich results with full text from SQLite
        results: list[dict[str, Any]] = []
        session = self.db_factory()
        try:
            for hit in hits:
                # Extract chunk info from payload
                chunk_index = hit.payload.get("chunk_index")
                doc_id = hit.payload.get("document_id")

                # Get full chunk text from SQLite
                chunk = (
                    session.query(DBChunk)
                    .filter(
                        DBChunk.document_id == doc_id,
                        DBChunk.chunk_index == chunk_index,
                    )
                    .first()
                )

                result = {
                    "score": hit.score,
                    "document_id": doc_id,
                    "chunk_index": chunk_index,
                    "page_numbers": hit.payload.get("page_numbers", []),
                    "section_heading": hit.payload.get("section_heading"),
                    "text": chunk.content if chunk else hit.payload.get("text", ""),
                    "filename": hit.payload.get("filename"),
                }
                results.append(result)

        finally:
            session.close()

        return results

    def get_index_stats(self) -> dict[str, Any]:
        """Get indexing statistics.

        Returns:
            Dictionary with index stats
        """
        session = self.db_factory()
        try:
            total_docs = session.query(Document).count()
            indexed_docs = (
                session.query(Document)
                .filter(Document.status == "indexed")
                .count()
            )
            total_chunks = session.query(DBChunk).count()
            indexed_chunks = (
                session.query(DBChunk)
                .filter(DBChunk.indexed == True)
                .count()
            )

            # Try to get Qdrant collection info
            qdrant_count = None
            qdrant_dimension = None
            try:
                if hasattr(self.vectors, "dimension"):
                    qdrant_dimension = self.vectors.dimension(COLLECTION_DOCUMENTS)
                # Count would require scanning which is expensive
                qdrant_count = indexed_chunks  # Approximate

            except Exception:
                pass

            return {
                "total_documents": total_docs,
                "indexed_documents": indexed_docs,
                "total_chunks": total_chunks,
                "indexed_chunks": indexed_chunks,
                "qdrant_vectors": qdrant_count,
                "embedding_dimension": qdrant_dimension,
            }

        finally:
            session.close()
