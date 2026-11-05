# Pactlyn User Guide

Complete guide for using Pactlyn effectively.

## Table of Contents

- [Understanding Pactlyn Pages](#understanding-pactlyn-pages)
- [Your First Commitment](#your-first-commitment)
- [Asking Questions](#asking-questions)
- [Uploading Documents](#uploading-documents)
- [Managing Email](#managing-email)
- [Using Memory](#using-memory)

---

## Understanding Pactlyn Pages

### Home Page — Quick Capture

**Purpose**: Fast input for new commitments

**What you see**:
- Text box: "What would you like Pactlyn to remember?"
- Capture button
- Dashboard cards: Active commitments, Overdue items, Waiting for responses

**How to use**:
1. Type naturally: "I need to submit the Q4 report to Sarah by Friday at 5pm"
2. Click "Capture"
3. Review extracted details
4. Edit if needed
5. Save

### Commitments Page — Task Management

**Purpose**: View and manage all your tracked commitments

**Features**:
- Search commitments
- Filter by status (Active, Completed, Postponed, Snoozed, Cancelled)
- Edit, Complete, Postpone, Snooze, Cancel actions
- Related commitments view

**Statuses explained**:
- **Active**: Current tasks you need to complete
- **Completed**: Done tasks (double-click to mark)
- **Postponed**: Delayed to a later date
- **Snoozed**: Temporarily hidden, will reappear
- **Cancelled**: No longer needed

### Memory Page — Knowledge Graph

**Purpose**: View all extracted facts and relationships

**What's stored here**:
- People you've mentioned
- Deadlines and dates
- Actions and their context
- Relationships between commitments

**Example memory entry**:
```
episodic - summarize doc
Source: USER_CAPTURE
Contact: None
Deadline Owner: USER
Type: PERSONAL_TASK
```

This is searchable via the Assistant.

### Assistant Page — Q&A Interface

**Purpose**: Ask questions about your commitments or documents

**Search Modes**:

1. **Commitments & Records**: Search your captured tasks
   - "What am I waiting for?"
   - "What's due this week?"
   - "Show me tasks related to Project Alpha"

2. **Uploaded Documents**: Search PDFs you've uploaded
   - "Summarize this contract"
   - "What's the deadline mentioned in the agreement?"
   - "Who are the parties in this document?"

3. **Both (Hybrid)**: Search everything
   - "What deadlines relate to documents I uploaded?"
   - "What tasks involve people mentioned in my PDFs?"

**Buttons**:
- **Remember this**: Capture what you typed as a commitment
- **Ask local context**: Query your local data with AI

### Documents Page — PDF Management

**Purpose**: Upload and manage documents for Q&A

**Features**:
- Upload PDFs
- View document list with page counts
- Delete documents
- Documents are indexed for semantic search

**How it works**:
1. Upload a PDF (contract, report, paper, etc.)
2. Pactlyn chunks it into searchable sections
3. Creates embeddings for semantic search
4. Ask questions in Assistant page with "Uploaded Documents" mode

### Email Centre — Follow-up Management

**Purpose**: Draft and send approved follow-up emails

**Features** (requires Resend setup):
- Draft email with AI assistance
- Preview exact payload
- Approve before sending
- Queue for delivery
- Track sent emails
- Poll inbound emails (optional)

**Important**: Every email requires explicit approval of exact content. No automatic sending.

### Settings Page — Configuration

**Tabs**:

1. **General**:
   - Theme (Light/Dark)
   - Data directory location
   - Backup/Restore

2. **Email**:
   - Resend API configuration
   - Sender address
   - Signature
   - Inbound polling

3. **AI Models**:
   - Select chat model
   - Select embedding model
   - Test models
   - View installed models

---

## Your First Commitment

### Step-by-Step

**1. Go to Home page**

**2. Type your commitment naturally**:

Examples that work well:
- "I need to submit my assignment by Friday 5pm"
- "Promised John I'd send the report by EOD Tuesday"
- "Waiting for Sarah's approval on the proposal"
- "Call Mom next Sunday at 3pm"
- "Email client about invoice by end of week"

**3. Click "Capture"**

AI extracts:
- What: Submit assignment / Send report / Get approval / Call Mom
- Who: John / Sarah / Mom
- When: Friday 5pm / EOD Tuesday / Next Sunday 3pm
- Type: USER_PERFORMS / USER_WAITING_FOR

**4. Review the extracted details**

You'll see a form with:
- Title: Brief summary
- Description: Full context
- Type: TASK / DEADLINE / WAITING / EVENT
- Person: Who's involved
- Email: Their contact (if mentioned)
- Due date: Deadline
- Reminder: When to remind you

**5. Edit if needed**

AI isn't perfect! Fix:
- Wrong dates
- Missing people
- Incorrect categorization

**6. Click "Save"**

Done! Your commitment is now:
- Stored in Commitments page
- Searchable via Assistant
- Will trigger reminders
- Facts extracted to Memory

---

## Asking Questions

### Effective Questions

**For Commitments** (Search mode: Commitments & Records):

Good questions:
- "What am I waiting for?" → Lists tasks waiting on others
- "What's due this week?" → Shows upcoming deadlines
- "What did I promise Sarah?" → Filters by person
- "Show me overdue tasks" → Lists past-due items
- "What meetings do I have?" → Event-type commitments

**For Documents** (Search mode: Uploaded Documents):

Good questions:
- "Summarize this document"
- "What are the key points in section 3?"
- "Who are the parties in this agreement?"
- "What's the termination clause?"
- "List all deadlines mentioned"

**For Hybrid** (Search mode: Both):

Good questions:
- "What tasks relate to the Smith project documents?"
- "Summarize commitments and documents about Q4 planning"
- "What deadlines are in my uploaded contracts and my task list?"

### Understanding Answers

**Clean formatting** (no brackets):
- **Bold text** for emphasis
- *Italic* for quotes
- Bullet points for lists

**Sources section** below answer:
- Document names with page numbers
- Clickable to see where info came from

Example:
```
📄 Sources:
Contract_2024.pdf (pages 3, 7, 12)
Meeting_Notes.pdf (page 2)
```

---

## Uploading Documents

### Supported Formats

Currently: **PDF only**

Future: DOCX, TXT, markdown

### How to Upload

1. Go to **Documents** page
2. Click **Upload Document** button
3. Select your PDF
4. Wait for processing (chunking + embedding)
5. Document appears in list

### What Happens During Upload

```mermaid
graph LR
    Upload[Upload PDF] --> Parse[Extract Text]
    Parse --> Chunk[Split into Chunks]
    Chunk --> Embed[Create Embeddings]
    Embed --> Store[Store in Qdrant]
    Store --> Ready[Ready for Q&A]
    
    style Upload fill:#C66F50
    style Ready fill:#1E6B52
```

Processing time: ~5-30 seconds depending on document size

### Document Q&A Tips

**Best practices**:
- Upload documents before asking questions
- Use specific questions: "What's the deadline in section 2?" vs "Tell me about deadlines"
- Reference document names if multiple: "In the Smith contract, what's the payment terms?"
- Check Sources section to verify where AI got the answer

**Limitations**:
- No OCR (scanned PDFs won't work well)
- Image-heavy PDFs may have poor extraction
- Very large PDFs (500+ pages) may be slow

---

## Managing Email

### Setup Resend (Optional)

**Prerequisites**:
- Resend account (free tier works)
- Verified domain in Resend
- Sender email at verified domain

**Configuration**:

1. Go to **Settings → Email**
2. Fill in:
   - Your name
   - Sender email (must be at verified domain)
   - Resend API key (stored securely in OS keyring)
   - Signature (optional)
   - Preferred tone (formal/casual)
3. Click **Test Connection**
4. If successful, email features are enabled

### Drafting Emails

1. Go to **Email Centre**
2. Click **New Draft**
3. Fill in:
   - To (recipient)
   - CC/BCC (optional)
   - Subject
   - Body
   - Related commitment (optional)
4. Optionally add your signature
5. Click **Save**

### Approving and Sending

**Important**: Pactlyn never sends without explicit approval

1. Draft saved in **Drafts** tab
2. Click **Approve**
3. Review **exact payload** including:
   - Recipients
   - Subject
   - Body text
   - Attachments
   - Headers
4. Click **Approve exact payload**
5. Email queued for sending
6. Check **Outbox** for delivery status

### Inbound Email (Optional)

**Setup**:
1. Settings → Email
2. Enter Resend inbound address
3. Enable inbound sync
4. Choose polling interval (5-60 minutes)

**How it works**:
- Pactlyn polls Resend for new emails
- Displays in **Inbox** tab
- Not full Gmail/Outlook sync (Resend only)

---

## Using Memory

### What is Memory?

Memory is Pactlyn's knowledge graph — extracted facts from everything you capture.

**What gets stored**:
- People: "Sarah", "John from accounting"
- Actions: "submit", "email", "call"
- Objects: "report", "invoice", "proposal"
- Deadlines: "Friday 5pm", "EOD Tuesday"
- Relationships: Task A blocks Task B, Person X assigned to Task Y

### Viewing Memory

**Memory Page** shows:
- Episodic entries (user captures)
- Source type (USER_CAPTURE, EMAIL, DOCUMENT)
- Contact info
- Responsibility (who does what)
- Relationships (task dependencies)

**Example entry**:
```
episodic - summarize doc
Source: USER_CAPTURE
Source Span: 0:0-0:10
Contact_Kind: None
Contact_Role: None
Recipient: null
Responsibility: USER
Deadline_Owner: USER
Condition: null
Needs_Confirmation: false
Relationships: []
Type: PERSONAL_TASK
```

### How Memory Powers Assistant

When you ask "What am I waiting for?", Assistant:
1. Searches memory graph for USER_WAITING_FOR type
2. Retrieves related commitments
3. Generates answer with context
4. Cites sources

**Memory enables**:
- Semantic search (meaning, not just keywords)
- Relationship tracking (what blocks what)
- Context-aware answers
- Fact verification

---

## Tips & Tricks

### Commitment Capture

**Be specific**:
- ❌ "Email Sarah" → Missing deadline, unclear about what
- ✅ "Email Sarah the Q4 report by Friday 5pm" → Clear action, deadline

**Include people**:
- ❌ "Get approval on proposal" → Who approves?
- ✅ "Get approval from John on the Smith proposal" → Clear ownership

**Natural dates work**:
- "next Tuesday"
- "end of week"
- "in 3 days"
- "Q4 2024"
- "December 15"

### Search Strategies

**Use filters in Commitments page**:
- Filter by person: Search "Sarah" to see all Sarah-related tasks
- Filter by status: "All statuses" dropdown
- Filter by date: Upcoming, overdue, etc.

**Ask Assistant follow-up questions**:
- First: "What am I waiting for?"
- Then: "When did I last contact John about this?"
- Then: "What's the related document?"

### Performance Optimization

**Model selection** (Settings → AI Models):
- **Fast**: qwen2.5:3b, qwen3:4b (2-4GB VRAM)
- **Balanced**: qwen2.5:7b (6-8GB VRAM)
- **Avoid**: Vision models (llava) for text tasks

**Document upload**:
- Upload during low-activity times
- Split very large PDFs into sections
- Delete old documents you no longer need

---

## Troubleshooting

### "Local assistant unavailable"

**Problem**: Ollama not running

**Solution**:
```bash
ollama serve
```

Keep this terminal open.

### "Discovery Failed" in AI Models

**Problem**: Can't connect to Ollama

**Solution**:
1. Check Ollama is running: `ollama list`
2. Verify URL in Settings (default: http://127.0.0.1:11434)
3. Click "Refresh Models"

### Slow responses (60+ seconds)

**Problem**: Model too large or verbose prompt

**Solution**:
1. Switch to smaller model (qwen2.5:3b)
2. Check timeout setting (should be 600s)
3. Close other GPU-intensive apps

### "Storage folder already accessed" (Qdrant lock)

**Problem**: Leftover lock file from crashed instance

**Solution**:
```bash
rm ~/.pactlyn/qdrant/.lock
rm ~/.pactlyn/qdrant/storage/.lock
```

Then restart Pactlyn.

### Email not sending

**Problem**: Missing configuration or approval

**Solution**:
1. Check Settings → Email → Test Connection
2. Verify sender domain is verified in Resend
3. Ensure you clicked "Approve exact payload"
4. Check Outbox for error messages

---

## Keyboard Shortcuts

(Coming in v0.9)

| Shortcut | Action |
|----------|--------|
| Ctrl+N | New commitment |
| Ctrl+K | Quick capture |
| Ctrl+F | Search commitments |
| Ctrl+, | Open settings |
| Ctrl+Q | Quit |

---

## Next Steps

- Read [Common Workflows](workflows.md) for real-world examples
- Explore [Privacy & Security](privacy.md) to understand data protection
- Check [Offline Mode](offline-mode.md) for internet-free usage
- Join [Discussions](https://github.com/yourusername/pactlyn-ai/discussions) to ask questions

---

**Happy committing! 🎯**
