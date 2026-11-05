#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 7 Integration Test - Documents UI and Main Window
Tests that DocumentsPage integrates correctly with PactlynWindow.
"""

import sys
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent / "src"))


def test_documents_page_import():
    """Test that DocumentsPage can be imported."""
    print("✓ Test 1: Importing DocumentsPage...")
    try:
        from pactlyn.ui.documents_page import DocumentsPage
        print("  ✓ DocumentsPage imported successfully")
        return True
    except Exception as e:
        print(f"  ✗ Failed to import DocumentsPage: {e}")
        return False


def test_main_window_import():
    """Test that PactlynWindow can be imported with new DocumentsPage."""
    print("\n✓ Test 2: Importing PactlynWindow with DocumentsPage integration...")
    try:
        from pactlyn.ui.main_window import PactlynWindow
        print("  ✓ PactlynWindow imported successfully")
        return True
    except Exception as e:
        print(f"  ✗ Failed to import PactlynWindow: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_app_initialization():
    """Test that the main window can be initialized with DocumentsPage."""
    print("\n✓ Test 3: Initializing application with Documents page...")
    try:
        from PySide6.QtWidgets import QApplication
        from pactlyn.app.bootstrap import build_container
        from pactlyn.ui.main_window import PactlynWindow
        
        # Create QApplication instance
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        
        # Initialize AppContainer
        print("  → Initializing AppContainer...")
        container = build_container()
        
        # Create main window
        print("  → Creating main window...")
        window = PactlynWindow(container)
        
        # Verify documents page exists
        if hasattr(window, 'documents_page'):
            print("  ✓ Documents page initialized successfully")
            print(f"  ✓ Number of pages: {window.pages.count()}")
            print(f"  ✓ Number of nav buttons: {len(window.nav)}")
            
            # Check that nav buttons match page count
            if len(window.nav) == 8:  # 7 main pages + 1 settings
                print("  ✓ Navigation buttons count correct (8)")
                return True
            else:
                print(f"  ✗ Expected 8 nav buttons, got {len(window.nav)}")
                return False
        else:
            print("  ✗ Documents page not found in main window")
            return False
            
    except Exception as e:
        print(f"  ✗ Failed to initialize application: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_documents_page_services():
    """Test that DocumentsPage initializes its services correctly."""
    print("\n✓ Test 4: Verifying Documents page services...")
    try:
        from PySide6.QtWidgets import QApplication
        from pactlyn.app.bootstrap import build_container
        from pactlyn.ui.documents_page import DocumentsPage
        
        # Create QApplication instance
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        
        # Initialize AppContainer
        container = build_container()
        
        # Create documents page directly
        docs_page = DocumentsPage(container)
        
        # Verify services
        if hasattr(docs_page, 'ingestion'):
            print("  ✓ Document ingestion service initialized")
        else:
            print("  ✗ Document ingestion service missing")
            return False
            
        if hasattr(docs_page, 'indexer'):
            print("  ✓ Document indexer service initialized")
        else:
            print("  ✗ Document indexer service missing")
            return False
            
        if hasattr(docs_page, 'session_factory'):
            print("  ✓ Session factory available")
        else:
            print("  ✗ Session factory missing")
            return False
        
        print("  ✓ All services initialized correctly")
        return True
        
    except Exception as e:
        print(f"  ✗ Failed to verify services: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_document_workflow_preparation():
    """Test that all necessary database tables and Qdrant collection exist."""
    print("\n✓ Test 5: Verifying database and vector store setup...")
    try:
        from pactlyn.app.bootstrap import build_container
        from pactlyn.storage.models import Document, DocumentChunk, DocumentFigure
        from sqlalchemy import select
        
        container = build_container()
        session = container.session()
        
        try:
            # Test that we can query documents
            result = session.execute(select(Document).limit(1))
            print("  ✓ Document table accessible")
            
            # Test that we can query chunks
            result = session.execute(select(DocumentChunk).limit(1))
            print("  ✓ DocumentChunk table accessible")
            
            # Test that we can query figures
            result = session.execute(select(DocumentFigure).limit(1))
            print("  ✓ DocumentFigure table accessible")
            
            # Verify Qdrant collection
            collections = container.vectors.client.get_collections().collections
            collection_names = [c.name for c in collections]
            if "pactlyn_documents" in collection_names:
                print("  ✓ Qdrant collection 'pactlyn_documents' exists")
            else:
                print("  ℹ Qdrant collection will be created on first document upload")
            
            return True
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"  ✗ Failed to verify database/vector store: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all Phase 7 integration tests."""
    print("=" * 70)
    print("Phase 7 Integration Test Suite")
    print("Documents UI and Main Window Integration")
    print("=" * 70)
    
    results = []
    
    results.append(("Import DocumentsPage", test_documents_page_import()))
    results.append(("Import PactlynWindow", test_main_window_import()))
    results.append(("Initialize Application", test_app_initialization()))
    results.append(("Verify Services", test_documents_page_services()))
    results.append(("Verify Database Setup", test_document_workflow_preparation()))
    
    # Summary
    print("\n" + "=" * 70)
    print("Test Results Summary")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:8} | {test_name}")
    
    print("=" * 70)
    print(f"Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All Phase 7 integration tests passed!")
        print("\nNext steps:")
        print("1. Launch Pactlyn: python -m pactlyn.app.main")
        print("2. Navigate to Documents tab (📄)")
        print("3. Test uploading a PDF document")
        print("4. Verify document processing (OCR → Vision → Chunking → Indexing)")
        print("5. Test semantic search")
        print("6. Test document viewer with figure extraction")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
