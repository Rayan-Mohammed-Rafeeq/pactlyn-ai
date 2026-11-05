# Phase 8: Assistant Document RAG and Cited Answers

**Status**: ✅ Implemented  
**Date**: 2026-11-05

## Overview

Phase 8 integrates document retrieval into Pactlyn's existing Assistant tab, enabling users to ask questions about uploaded PDFs with properly cited answers. Every factual claim includes clickable citations that jump to the specific page in the DocumentViewer.

## Key Features

### 1. Document-Aware RAG Service

**File**: `src/pactlyn/rag/document_rag.py`

- **DocumentCitation**: Rich citation structure with:
  - Document ID and name
  - Page number (clickable)
  - Section title
  - Chunk or figure reference
  - Content preview

- **DocumentGroundedAnswer**: Answer structure with:
  - Generated answer text
  - List of document citations
  - Optional commitment evidence (for hybrid queries)
  - LLM usage flag
  - Abstention flag

- **DocumentRAGService**: Core service providing:
  - Document chunk + figure hybrid retrieval
  - Query classification (document/commitment/hybrid)
  - Citation grounding validation
  - Hallucination detection
  - Multi-document search support

### 2. Figure-Aware Retrieval

The service searches both:
- **Document chunks**: Text extracted from PDFs
- **Figure descriptions**: Captions and vision model descriptions

This enables queries like:
- "Show me figures about X"
- "What charts are in my documents?"
- "Summarize the diagram on page 5"

### 3. Enhanced Assistant UI

**File**: `src/pactlyn/ui/main_window.py`

Added features:
- **Mode selector**: Choose between:
  - 📝 Commitments & Records (original)
  - 📄 Uploaded Documents (new)
  - 🔍 Both (hybrid)

- **Clickable citations**: Citations formatted as HTML links:
  ```
  [doc1] filename.pdf (page 5)
  ```
  Clicking opens DocumentViewer to that exact page

- **DocumentAssistantWorker**: Background worker for document queries
- **Citation formatting**: Rich HTML display with:
  - Answer text with inline citations
  - Document sources section
  - Commitment context (when applicable)

### 4. DocumentViewer Integration

**File**: `src/pactlyn/ui/documents_page.py`

Added `open_document_by_id(document_id, page_number)` method:
- Opens document by integer ID
- Navigates to specific page
- Called when citation is clicked

## Citation Requirements

The system enforces strict citation discipline:

### ✅ Valid Patterns
- Every factual claim cited: `[doc1]`, `[doc2]`
- Multiple sources for same claim: `[doc1][doc2]`
- Abstentions without citations: "I don't have enough evidence"

### ❌ Invalid Patterns
- Hallucinated citations: `[doc5]` when only 3 docs provided
- Substantial answers without citations (>20 words)
- Invented page numbers

### Grounding Validation

The `_answer_citations_are_grounded()` method checks:
1. All citation markers reference valid document indices
2. Factual answers include at least one citation
3. Abstention phrases don't require citations

## Query Classification

Automatic classification determines retrieval strategy:

| Pattern | Classification | Behavior |
|---------|---------------|----------|
| "document", "PDF", "figure" | document | Search documents only |
| "due", "waiting", "deadline" | commitment | Search commitments only |
| Ambiguous or mixed | hybrid | Search both collections |

## Architecture

### Data Flow

```
User Question
    ↓
Query Classification
    ↓
┌──────────────────┬──────────────────┐
│ Document Search  │ Commitment Search │
│ (chunks+figures) │  (optional)       │
└────────┬─────────┴──────────┬────────┘
         ↓                    ↓
    Build Citations    Build Evidence
         ↓                    ↓
         └────────┬───────────┘
                  ↓
          LLM Generation with
          Citation Instructions
                  ↓
         Grounding Validation
                  ↓
          Format as HTML
                  ↓
          Display in UI
```

### Collection Usage

- **pactlyn_documents**: Document chunks and figure descriptions
  - Metadata: `chunk_type` = "chunk" or "figure"
  - Payload: `document_id`, `chunk_id` or `figure_id`, `page_number`

- **personal_knowledge**: Commitments and memories
  - Used for hybrid queries

## Local-Only Operation

All components use local inference:
- ✅ Ollama for answer generation
- ✅ Nomic-embed-text for embeddings
- ✅ Qdrant local vector store
- ✅ No external API calls

## Testing

### Integration Tests

**File**: `test_phase8_document_rag.py`

Tests (7/7 passing):
1. Import verification
2. DocumentCitation structure
3. DocumentGroundedAnswer structure
4. Citation grounding validation
5. Query classification
6. HTML citation formatting
7. UI integration

Run: `.venv\Scripts\python.exe test_phase8_document_rag.py`

### End-to-End Tests

**File**: `test_phase8_e2e.py`

Tests:
1. Complete RAG workflow with real documents
2. Multi-document search
3. Figure-aware retrieval
4. Citation structure validation

Requires:
- At least 1 uploaded PDF document
- Ollama running locally

Run: `.venv\Scripts\python.exe test_phase8_e2e.py`

## Usage

### From UI

1. Launch Pactlyn application
2. Navigate to **Assistant** tab
3. Select mode:
   - **Uploaded Documents** for document questions
   - **Commitments & Records** for commitment questions
   - **Both (Hybrid)** for mixed queries
4. Enter question and click "Ask local context"
5. Click citations to jump to specific pages

### Example Queries

**Document-Only**:
- "What does the report say about climate change?"
- "Summarize the introduction section"
- "Show me figure 3"
- "What's on page 5?"

**Hybrid**:
- "What did I commit to according to the meeting notes?"
- "Do my documents mention any of my deadlines?"

**Commitment-Only**:
- "What am I waiting for?"
- "Show my tasks due this week"

## Implementation Details

### Citation Marker Format

Answer text uses `[doc1]`, `[doc2]`, etc.

HTML rendering converts to:
```html
<a href="pactlyn://citation_0">[doc1]</a>
```

Click handler:
1. Extracts citation index from URL
2. Looks up citation in `_current_citations` dict
3. Navigates to Documents tab (index 6)
4. Calls `documents_page.open_document_by_id()`

### Figure Search

Figure metadata filter:
```python
query_filter={"chunk_type": "figure"}
```

Returns:
- Figure ID
- Page number
- Caption
- Vision model description
- Similarity score

### Multi-Document Support

The service:
1. Retrieves chunks/figures from all documents
2. Sorts by relevance score
3. Returns top-N across documents
4. Citations include distinct document IDs

## Known Limitations

1. **Page accuracy**: Depends on PDF structure
   - Well-formed PDFs: Exact page navigation
   - Malformed PDFs: May require manual navigation

2. **Figure descriptions**: Quality depends on:
   - LLaVA model availability
   - Image clarity in PDF

3. **Citation markers**: Model must follow format
   - Uses [doc1] style (GPT-style)
   - Some models may prefer other formats

4. **Context window**: Limited by model
   - Default: 8 sources (configurable)
   - Longer documents may need chunking

## Future Enhancements

### Potential Improvements

1. **Table extraction**: Add table-aware retrieval
2. **Cross-reference resolution**: Link related sections
3. **Citation clustering**: Group related citations
4. **Snippet highlighting**: Highlight cited text in viewer
5. **Export citations**: Generate bibliography
6. **Multi-modal answers**: Include figure thumbnails

### Performance Optimizations

1. **Caching**: Cache frequent queries
2. **Batch processing**: Parallel document search
3. **Incremental indexing**: Update only changed docs
4. **Compression**: Reduce vector storage size

## Dependencies

### New Dependencies
- None (uses existing Phase 0-7 infrastructure)

### Required Services
- Ollama (local LLM)
- Qdrant (local vector store)
- PyMuPDF (PDF rendering)

### UI Components
- PySide6 QTextEdit with HTML support
- Anchor click events
- DocumentViewer

## Validation

### Citation Accuracy
- Manual review of 10 sample queries
- Verify citations point to correct pages
- Check for hallucinated references

### Abstention Behavior
- Test with insufficient evidence
- Verify model abstains appropriately
- Check abstention message clarity

### Multi-Document Behavior
- Test with 2+ documents
- Verify citations from multiple sources
- Check answer synthesis quality

## Security Considerations

1. **Citation injection**: All user content HTML-escaped
2. **URL validation**: Only pactlyn:// scheme accepted
3. **Document access**: Checks document exists before opening
4. **XSS prevention**: HTML sanitization in formatting

## Compatibility

- **Python**: 3.11+ (uses native UTC and StrEnum)
- **Qt**: PySide6 6.5+
- **Qdrant**: Local mode (no server)
- **Ollama**: 0.1.0+

## Conclusion

Phase 8 successfully integrates document retrieval into Pactlyn's Assistant, providing:
- ✅ Cited answers with clickable page references
- ✅ Figure-aware search
- ✅ Multi-document support
- ✅ Local-only operation
- ✅ Hallucination detection
- ✅ Hybrid commitment+document queries

The implementation preserves all existing functionality while adding powerful document intelligence capabilities.
