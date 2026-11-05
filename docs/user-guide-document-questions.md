# User Guide: Asking Questions About Your Documents

This guide shows you how to use Pactlyn's Assistant to ask questions about your uploaded PDF documents with cited answers.

## Quick Start

### 1. Upload Documents

First, make sure you have PDF documents uploaded:

1. Click **Documents** in the left sidebar
2. Click **Upload Document** button
3. Select a PDF file
4. Wait for processing to complete

You can also drag and drop PDF files into the Documents page.

### 2. Ask Questions

1. Click **Assistant** in the left sidebar
2. Select search mode:
   - **📄 Uploaded Documents** - Search only your PDFs
   - **📝 Commitments & Records** - Search only your commitments
   - **🔍 Both (Hybrid)** - Search both
3. Type your question
4. Click **Ask local context**

### 3. Read Cited Answers

The answer will include:
- Main answer text with inline citations like `[doc1]`, `[doc2]`
- Document sources section listing all cited documents
- Page numbers for each citation

**Click any citation** to jump directly to that page in the document!

## Example Questions

### About Document Content

- "What does the report say about climate change?"
- "Summarize the introduction section"
- "What are the main findings?"
- "Explain the methodology"

### About Specific Pages

- "What's on page 5?"
- "Summarize pages 10-15"
- "What does page 3 discuss?"

### About Figures and Charts

- "Show me any figures or charts"
- "What does figure 3 show?"
- "Are there any diagrams?"
- "Describe the charts in the document"

### Multi-Document Questions

- "What topics are covered across all my documents?"
- "Compare the findings in my research papers"
- "What documents mention artificial intelligence?"

### Hybrid Questions (Documents + Commitments)

- "What did I commit to according to the meeting notes?"
- "Do my documents mention any of my deadlines?"
- "What actions items are in my uploaded PDFs?"

## Understanding Citations

### Citation Format

Citations appear as `[doc1]`, `[doc2]`, etc.

Each citation is **clickable** and links to a specific page.

### Citation Sources Section

Below the answer, you'll see:

```
📄 Document Sources:
- [doc1] report.pdf (page 5)
- [doc2] analysis.pdf (page 12) - Introduction
```

### Commitment Context

For hybrid queries, you may also see:

```
📝 Commitment Context:
- commitment/c123
- memory/m456
```

## How It Works

### Local-Only Processing

All processing happens on your computer:
- ✅ No data sent to external servers
- ✅ Uses Ollama (local AI)
- ✅ Qdrant (local vector database)
- ✅ Your documents never leave your machine

### Search Strategy

The Assistant uses **hybrid search**:
1. **Semantic search**: Understands meaning, not just keywords
2. **Keyword search**: Finds exact terms
3. **Figure search**: Searches image descriptions and captions

### Citation Accuracy

The system:
- ✅ Only cites information actually in documents
- ✅ Provides page numbers for verification
- ✅ Detects when evidence is insufficient
- ✅ Never invents citations

If the system doesn't have enough information, it will say:
> "I don't have enough document evidence to answer that question."

## Tips for Better Results

### 1. Be Specific

❌ "Tell me about it"  
✅ "What does the climate report say about emissions?"

### 2. Ask One Thing at a Time

❌ "Summarize everything and tell me about figures and what's on page 5"  
✅ "Summarize the main findings"  
✅ "What figures are included?"  
✅ "What's discussed on page 5?"

### 3. Use Document Mode for Document Questions

- Select **📄 Uploaded Documents** mode
- Faster and more focused results
- Better citations

### 4. Verify Citations

- Click citations to check the source
- Read the original context
- Citations include page numbers for easy verification

### 5. Upload Related Documents Together

- The Assistant can search across multiple documents
- Better for comparative questions
- Finds connections between documents

## Troubleshooting

### "Local assistant unavailable"

**Cause**: Ollama is not running

**Solution**:
1. Start Ollama: Open command prompt and run `ollama serve`
2. Check settings: Settings → General → Ollama endpoint
3. Default: `http://localhost:11434`

### "Could not find supporting information"

**Causes**:
- Document not processed yet
- Question too vague
- Information not in documents

**Solutions**:
- Wait for document processing (check Documents tab)
- Rephrase question more specifically
- Check if information is actually in your documents

### Citations Not Clickable

**Cause**: HTML rendering issue

**Solution**:
- Restart Pactlyn
- Check that you're using the Assistant output area (not copying elsewhere)

### Wrong Page Opens

**Causes**:
- PDF structure issues
- Complex PDF with non-standard page numbering

**Solutions**:
- Use page number in citation as reference
- Navigate manually if needed
- Some PDFs have display page ≠ logical page

### No Figure Results

**Causes**:
- Document has no figures
- Figures not yet processed
- Vision model not available

**Solutions**:
- Check Documents tab for processing status
- Ensure LLaVA model is available in Ollama
- Wait for background processing to complete

## Privacy & Security

### What Stays Local

- ✅ All document content
- ✅ All search queries
- ✅ All generated answers
- ✅ All embeddings and vectors

### What Never Leaves Your Computer

- ✅ PDF files
- ✅ Extracted text
- ✅ Figure descriptions
- ✅ Citations and metadata

### Network Usage

The system only uses network for:
- Downloading Ollama models (one-time)
- Nothing else - completely offline after setup

## Advanced Usage

### Combining Modes

Use **🔍 Both (Hybrid)** mode to:
- Find commitments mentioned in documents
- Cross-reference your records with PDFs
- Ask about documents in context of your work

### Search Limits

Default: Top 8 most relevant sources

For exhaustive search:
- Ask multiple related questions
- Focus on specific sections
- Break complex questions into parts

### Figure-Focused Queries

To search figures specifically:
- "Show me figures about X"
- "What charts are available?"
- "Describe the diagrams"

The system prioritizes figure descriptions for these queries.

## FAQ

**Q: Can I search multiple PDFs at once?**  
A: Yes! The Assistant searches all uploaded documents and cites the most relevant ones.

**Q: How accurate are the citations?**  
A: Citations point to the specific pages containing the information. You can always click to verify.

**Q: What file formats are supported?**  
A: Currently only PDF files. More formats coming in future updates.

**Q: Can I delete the answer and ask again?**  
A: Yes, just type a new question and click "Ask local context" again.

**Q: Do I need internet to use this?**  
A: No! After downloading Ollama models, everything works offline.

**Q: How long does processing take?**  
A: Small PDFs: seconds. Large PDFs: minutes. Check Documents tab for status.

**Q: Can I export the answers?**  
A: Currently, copy and paste from the answer area. Export feature coming soon.

## Getting Help

If you encounter issues:

1. Check the Documents tab - is processing complete?
2. Check Ollama is running: `ollama list`
3. Review the troubleshooting section above
4. Check logs in Settings → General → Data directory

## What's Next?

After Phase 8, you can:
- Ask questions about your documents ✅
- Get cited answers ✅
- Click citations to jump to pages ✅
- Search figures and charts ✅
- Combine document + commitment search ✅

Future enhancements:
- Table extraction and search
- Multi-lingual document support
- Export answers with citations
- Highlight cited text in viewer
- Citation clustering

---

**Version**: Phase 8 (2026-11-05)  
**Feedback**: Report issues or suggestions via GitHub
