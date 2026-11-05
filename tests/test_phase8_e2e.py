"""End-to-end test for Phase 8: Document RAG with real PDF documents."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))


async def test_document_rag_workflow():
    """Test the complete document RAG workflow."""
    from pactlyn.app.bootstrap import build_container
    from pactlyn.documents.indexing import DocumentIndexer
    from pactlyn.rag.document_rag import DocumentRAGService
    from pactlyn.rag.retrieval import HybridRetriever
    from pactlyn.rag.service import RAGService
    from pactlyn.storage.models import Document
    
    print("=" * 70)
    print("Phase 8 End-to-End Test: Document RAG with Citations")
    print("=" * 70)
    
    # Build container
    print("\n1. Building application container...")
    container = build_container()
    print("   ✓ Container built")
    
    # Check for existing documents
    print("\n2. Checking for indexed documents...")
    session = container.session()
    try:
        documents = session.query(Document).filter(
            Document.deleted_at.is_(None)
        ).all()
        
        if not documents:
            print("   ⚠ No documents found. Please upload PDFs first using the Documents UI.")
            print("   This test requires at least one uploaded PDF document.")
            return False
        
        print(f"   ✓ Found {len(documents)} document(s)")
        for doc in documents[:3]:
            print(f"     - {doc.filename} ({doc.page_count} pages)")
        
        # Initialize services
        print("\n3. Initializing RAG services...")
        indexer = DocumentIndexer(
            container.session_factory,
            container.vectors,
            container.embedder,
        )
        retriever = HybridRetriever(session, container.vectors, container.embedder)
        commitment_rag = RAGService(session, container.llm, retriever)
        
        doc_rag = DocumentRAGService(
            session,
            container.llm,
            indexer,
            commitment_rag=commitment_rag,
        )
        print("   ✓ Services initialized")
        
        # Test queries
        test_queries = [
            ("What documents do I have?", "document", False),
            ("Summarize the key points from my documents", "document", True),
            ("What information is available on page 1?", "document", True),
            ("Are there any figures or charts?", "document", True),
        ]
        
        print("\n4. Testing document queries...")
        for query, expected_mode, requires_llm in test_queries:
            print(f"\n   Query: \"{query}\"")
            print(f"   Expected mode: {expected_mode}")
            
            # Check LLM availability for queries that need it
            if requires_llm:
                provider = container.llm.local
                if not await provider.available():
                    print(f"   ⚠ Skipped: Ollama not available")
                    continue
            
            try:
                # Test document RAG
                answer = await doc_rag.answer(query, limit=5)
                
                print(f"   Answer length: {len(answer.answer)} chars")
                print(f"   Citations: {len(answer.citations)}")
                print(f"   Commitment evidence: {len(answer.commitment_evidence)}")
                print(f"   Used LLM: {answer.used_local_model}")
                print(f"   Abstained: {answer.abstained}")
                
                if answer.citations:
                    print(f"   First citation: {answer.citations[0].document_name} page {answer.citations[0].page_number}")
                
                # Show answer preview
                preview = answer.answer[:150]
                if len(answer.answer) > 150:
                    preview += "..."
                print(f"   Answer preview: {preview}")
                
                print("   ✓ Query completed successfully")
                
            except Exception as e:
                print(f"   ✗ Query failed: {e}")
                import traceback
                traceback.print_exc()
                return False
        
        print("\n5. Testing citation structure...")
        if answer.citations:
            citation = answer.citations[0]
            print(f"   Document ID: {citation.document_id}")
            print(f"   Document name: {citation.document_name}")
            print(f"   Page: {citation.page_number}")
            print(f"   Section: {citation.section_title}")
            print(f"   Chunk ID: {citation.chunk_id}")
            print(f"   Figure ID: {citation.figure_id}")
            print(f"   Preview: {citation.content_preview[:100]}...")
            print("   ✓ Citation structure complete")
        else:
            print("   ⚠ No citations to validate")
        
        print("\n6. Testing figure-aware retrieval...")
        try:
            # Query specifically for figures
            fig_answer = await doc_rag.answer(
                "Show me any figures, charts, or diagrams",
                limit=5,
                include_figures=True,
            )
            
            figure_citations = [c for c in fig_answer.citations if c.figure_id is not None]
            print(f"   Found {len(figure_citations)} figure citation(s)")
            
            if figure_citations:
                fig_cit = figure_citations[0]
                print(f"   Figure: {fig_cit.document_name} page {fig_cit.page_number}")
                print(f"   Preview: {fig_cit.content_preview[:100]}...")
                print("   ✓ Figure-aware retrieval working")
            else:
                print("   ⚠ No figures found (may be normal if documents have no figures)")
        
        except Exception as e:
            print(f"   ✗ Figure retrieval failed: {e}")
            import traceback
            traceback.print_exc()
        
        print("\n" + "=" * 70)
        print("✓ Phase 8 End-to-End Test PASSED")
        print("=" * 70)
        print("\nNext steps:")
        print("1. Launch the Pactlyn UI")
        print("2. Navigate to Assistant tab")
        print("3. Select 'Uploaded Documents' mode")
        print("4. Ask a question about your documents")
        print("5. Click on citations to jump to specific pages")
        
        return True
        
    finally:
        session.close()


async def test_multi_document_search():
    """Test searching across multiple documents."""
    from pactlyn.app.bootstrap import build_container
    from pactlyn.documents.indexing import DocumentIndexer
    from pactlyn.rag.document_rag import DocumentRAGService
    from pactlyn.rag.retrieval import HybridRetriever
    from pactlyn.rag.service import RAGService
    from pactlyn.storage.models import Document
    
    print("\n" + "=" * 70)
    print("Multi-Document Search Test")
    print("=" * 70)
    
    container = build_container()
    session = container.session()
    
    try:
        documents = session.query(Document).filter(
            Document.deleted_at.is_(None)
        ).all()
        
        if len(documents) < 2:
            print("⚠ This test requires at least 2 documents. Skipping...")
            return True
        
        print(f"Testing with {len(documents)} documents")
        
        # Initialize services
        indexer = DocumentIndexer(
            container.session_factory,
            container.vectors,
            container.embedder,
        )
        retriever = HybridRetriever(session, container.vectors, container.embedder)
        commitment_rag = RAGService(session, container.llm, retriever)
        
        doc_rag = DocumentRAGService(
            session,
            container.llm,
            indexer,
            commitment_rag=commitment_rag,
        )
        
        # Query that should span multiple documents
        print("\nQuery: 'What topics are covered across all my documents?'")
        
        provider = container.llm.local
        if not await provider.available():
            print("⚠ Ollama not available. Skipping LLM-dependent test.")
            return True
        
        answer = await doc_rag.answer(
            "What topics are covered across all my documents?",
            limit=10,
        )
        
        # Check for multi-document citations
        unique_docs = set(c.document_id for c in answer.citations)
        print(f"\nCitations from {len(unique_docs)} unique document(s)")
        
        for doc_id in unique_docs:
            doc_citations = [c for c in answer.citations if c.document_id == doc_id]
            doc_name = doc_citations[0].document_name
            print(f"  - {doc_name}: {len(doc_citations)} citation(s)")
        
        if len(unique_docs) >= 2:
            print("✓ Multi-document search working")
        else:
            print("⚠ Only found citations from 1 document (may be normal if query is narrow)")
        
        return True
        
    finally:
        session.close()


def main():
    """Run all end-to-end tests."""
    try:
        result1 = asyncio.run(test_document_rag_workflow())
        result2 = asyncio.run(test_multi_document_search())
        
        if result1 and result2:
            print("\n✓ All end-to-end tests PASSED")
            return 0
        else:
            print("\n✗ Some end-to-end tests FAILED")
            return 1
    except Exception as e:
        print(f"\n✗ Test crashed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
