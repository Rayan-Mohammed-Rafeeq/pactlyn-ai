# Pactlyn Testing Checklist

Complete testing guide to ensure all features work correctly.

## 🧪 Quick Test (5 minutes)

**Goal**: Verify core functionality is working

### 1. Launch Check
```bash
# Terminal 1: Start Ollama
ollama serve

# Terminal 2: Start Pactlyn
cd d:\Projects\pactlyn-ai
uv run pactlyn
```

**Expected**: Pactlyn window opens without errors

---

### 2. Model Discovery Test

**Steps**:
1. Go to **Settings → AI Models** tab
2. Wait 5-10 seconds

**Expected**:
- Status changes from "Discovering..." to "Connected"
- "Installed Models" shows your models (qwen3:4b, nomic-embed-text, etc.)
- Model dropdowns auto-populate
- Status message: "✓ Preference saved: [model name]"

**If it fails**:
- Check Ollama is running: `ollama list`
- Click "Refresh Models" manually
- Check terminal for errors

---

### 3. Commitment Capture Test

**Steps**:
1. Go to **Home** page
2. Type: `I need to send the report to Sarah by Friday 5pm`
3. Click **"Capture"** button
4. Wait 10-30 seconds (AI processing)

**Expected**:
- Review dialog appears
- Extracted fields:
  - Title: "Send report to Sarah"
  - Person: "Sarah"
  - Due date: "Friday 5pm" (parsed to actual date)
  - Type: TASK or DEADLINE
- Click "Save" → Shows success

**If it fails**:
- Check timeout setting (should be 600s in Settings → AI Models)
- Try shorter text: "Email John by Tuesday"
- Check Ollama terminal for errors

---

### 4. View Commitment

**Steps**:
1. Go to **Commitments** page
2. Look for your captured commitment

**Expected**:
- Your commitment appears in the list
- Status: Active
- Can double-click to mark Complete
- Can click to view details

---

### 5. Assistant Query Test

**Steps**:
1. Go to **Assistant** page
2. Search mode: "Commitments & Records" (should be default)
3. Type: `What am I waiting for?`
4. Click **"Ask local context"**
5. Wait 20-60 seconds

**Expected**:
- Answer appears with proper formatting (bold, bullets work)
- No citation brackets like [1] or [doc1] in the text
- If you have no "waiting" items, it says "You have no pending items"

**If it fails**:
- Model might be too slow (check it's qwen3:4b, not qwen2.5:7b)
- Check timeout (600s)
- Try simpler question: "What's due this week?"

---

## 🔬 Comprehensive Test (20 minutes)

### Test 1: Document Upload & Q&A

**Steps**:
1. Go to **Documents** page
2. Click **"Upload Document"**
3. Select a PDF (any PDF, ideally text-based not scanned)
4. Wait for "Processing complete" (10-60 seconds depending on size)
5. Go to **Assistant** page
6. Change search mode to **"Uploaded Documents"**
7. Type: `Summarize this document`
8. Click **"Ask local context"**
9. Wait for response

**Expected**:
- Document appears in Documents list with page count
- Assistant generates summary
- Shows **"📄 Sources:"** section below answer
- Source shows document name and page numbers
- No [1] [2] [3] brackets in answer text

**If it fails**:
- Check PDF is not scanned/image-only (won't work without OCR)
- Check Qdrant is running (no lock errors on startup)
- Try smaller PDF first

---

### Test 2: Memory Extraction

**Steps**:
1. After capturing commitments (Test 3 from Quick Test)
2. Go to **Memory** page
3. Look for entries

**Expected**:
- See episodic entries like "summarize doc" or your commitment text
- Each shows:
  - Source: USER_CAPTURE
  - Type: PERSONAL_TASK or similar
  - Responsibility: USER
  - Contact info if person was mentioned

**What it means**:
- Facts are being extracted from your captures
- Knowledge graph is being built
- These power Assistant queries

---

### Test 3: Hybrid Search

**Steps**:
1. Upload a document about a specific topic (e.g., project requirements)
2. Capture a related commitment: "Complete Phase 1 requirements by Monday"
3. Go to **Assistant** page
4. Change search mode to **"Both (Hybrid)"**
5. Ask: `What are the requirements for Phase 1?`

**Expected**:
- Answer combines info from:
  - Your uploaded requirements document
  - Your captured commitment
- Sources section shows both document and commitment references

**If it fails**:
- Make sure commitment and document actually relate to same topic
- Try mode "Uploaded Documents" first, then "Commitments", then "Both"

---

### Test 4: Reminder Test (Quick)

**Steps**:
1. Capture commitment with near deadline:
   - "Test reminder in 2 minutes"
   - Set due date to 2 minutes from now
2. Wait 2 minutes
3. Check for desktop notification

**Expected**:
- Desktop notification appears at deadline time
- Shows commitment title
- Action buttons available

**Note**: Full reminder testing requires waiting. For quick test, just verify:
- Commitment with deadline shows "Reminder" field
- Can edit reminder time

---

### Test 5: Full-Text Search

**Steps**:
1. Capture several commitments with different words:
   - "Send report to Sarah"
   - "Call John about budget"
   - "Review proposal with team"
2. Go to **Commitments** page
3. Use search box: Type "Sarah"

**Expected**:
- Only "Send report to Sarah" appears
- Other commitments hidden
- Clear search → All appear again

---

### Test 6: Commitment Status Changes

**Steps**:
1. Go to **Commitments** page
2. Select a commitment
3. Click **"Complete"** button
4. Check status filter dropdown → Select "Completed"

**Expected**:
- Commitment marked as completed
- Disappears from "Active" view
- Appears in "Completed" filter

**Try other actions**:
- **Postpone**: Move to future date
- **Snooze**: Hide temporarily
- **Cancel**: Mark as cancelled
- **Edit**: Change details

---

### Test 7: Theme Switching

**Steps**:
1. Go to **Settings → General** tab
2. Find "Color Theme" dropdown
3. Switch from Light to Dark (or vice versa)

**Expected**:
- UI immediately changes colors
- All pages reflect new theme
- Close Pactlyn, reopen → Theme persists

---

### Test 8: Model Preference Persistence

**Steps**:
1. Go to **Settings → AI Models**
2. Change assistant model (select different one from dropdown)
3. See status: "✓ Preference saved: [model]"
4. Close Pactlyn completely
5. Reopen Pactlyn
6. Go to Settings → AI Models

**Expected**:
- Selected model still shows in dropdown
- Preference was saved and restored

---

## 🔧 Advanced Tests (Developer/QA)

### Test 9: Offline Mode

**Steps**:
1. Disconnect from internet (disable WiFi)
2. Open Pactlyn (Ollama already running locally)
3. Capture commitment
4. Ask Assistant query
5. Upload document and query it

**Expected**:
- All features work (LLM, embeddings, RAG)
- Only email features unavailable
- No error messages about network

---

### Test 10: Large Document

**Steps**:
1. Upload large PDF (50+ pages)
2. Wait for processing (may take 1-2 minutes)
3. Ask specific question: "What's mentioned on page 25?"

**Expected**:
- Processing completes without errors
- Query returns relevant info
- Cites correct page number

---

### Test 11: Multiple Documents

**Steps**:
1. Upload 3 different PDFs
2. Ask: "Compare the key points across all documents"

**Expected**:
- Answer synthesizes info from all 3
- Sources section lists all 3 documents with relevant pages

---

### Test 12: Error Recovery

**Test 12a: Ollama Crash**
1. Stop Ollama (`Ctrl+C` in terminal)
2. Try to capture commitment
3. Expected: Error message, offers offline fallback
4. Restart Ollama → Try again → Should work

**Test 12b: Qdrant Lock**
1. Force-quit Pactlyn (don't close gracefully)
2. Restart Pactlyn
3. Expected: Either starts normally OR shows Qdrant lock error
4. If lock error: Run cleanup, restart

---

### Test 13: Backup & Restore

**Steps**:
1. Capture 2-3 commitments
2. Go to **Settings → General**
3. Click **"Create backup"**
4. Save to `pactlyn-test-backup.pactlyn`
5. Capture 1 more commitment (so DB is different)
6. Click **"Restore from backup"**
7. Select `pactlyn-test-backup.pactlyn`
8. Confirm restore
9. Pactlyn restarts

**Expected**:
- After restore, only original 2-3 commitments exist
- Latest commitment is gone (as expected - restored to earlier state)

---

### Test 14: Email Draft (Optional - Requires Resend)

**Only if you have Resend configured:**

**Steps**:
1. Go to **Settings → Email**
2. Click **"Test Connection"**
3. Expected: ✓ Connection successful
4. Go to **Email Centre**
5. Click **"New Draft"**
6. Fill in recipient, subject, body
7. Save draft
8. Click **"Approve"**
9. Review exact payload
10. Click **"Approve exact payload"**

**Expected**:
- Draft saved
- Payload preview shows exact content
- After approval, email queued
- Check Resend dashboard for delivery

---

## 🐛 Common Issues & Fixes

### Issue: "Checking..." stuck forever

**Cause**: Ollama not running or wrong URL

**Fix**:
```bash
# Check Ollama is running
ollama list

# Start if not running
ollama serve

# In Pactlyn: Settings → AI Models → Refresh Models
```

---

### Issue: Timeout after 60 seconds

**Cause**: Timeout too short or model too slow

**Fix**:
```bash
# Check your model speed
ollama run qwen3:4b "test"

# If slow, switch model:
# Settings → AI Models → Select qwen3:4b (faster)
```

---

### Issue: No citation markers removed

**Cause**: Old code still running

**Fix**:
```bash
# Kill Pactlyn completely
# In PowerShell:
Get-Process python | Stop-Process -Force

# Restart
uv run pactlyn
```

---

### Issue: Qdrant lock error on startup

**Cause**: Previous instance didn't clean up

**Fix**:
```powershell
# Remove lock files
Remove-Item "$env:USERPROFILE\.pactlyn\qdrant\.lock" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:USERPROFILE\.pactlyn\qdrant\storage\.lock" -Force -ErrorAction SilentlyContinue

# Restart Pactlyn
```

---

### Issue: Document upload fails

**Cause**: Scanned PDF (images only) or corrupt file

**Fix**:
- Try different PDF (text-based)
- Check PDF opens in reader
- Check file size (very large PDFs slow)

---

### Issue: Assistant gives empty answers

**Cause**: No relevant data or search mode mismatch

**Fix**:
- Check search mode matches your query:
  - Asking about documents? Use "Uploaded Documents"
  - Asking about tasks? Use "Commitments & Records"
- Verify you have data:
  - Commitments page has entries
  - Documents page has uploads

---

## ✅ Test Results Checklist

Mark each test as you complete it:

**Quick Tests**:
- [ ] Launch Check
- [ ] Model Discovery
- [ ] Commitment Capture
- [ ] View Commitment
- [ ] Assistant Query

**Comprehensive Tests**:
- [ ] Document Upload & Q&A
- [ ] Memory Extraction
- [ ] Hybrid Search
- [ ] Reminder Test
- [ ] Full-Text Search
- [ ] Commitment Status Changes
- [ ] Theme Switching
- [ ] Model Preference Persistence

**Advanced Tests** (optional):
- [ ] Offline Mode
- [ ] Large Document
- [ ] Multiple Documents
- [ ] Error Recovery
- [ ] Backup & Restore
- [ ] Email Draft

---

## 📊 Performance Benchmarks

**Expected timings** (qwen3:4b on GTX 1650 4GB):

| Operation | Expected Time | Acceptable Range |
|-----------|---------------|------------------|
| Commitment capture | 10-30s | Up to 60s |
| Document Q&A | 20-60s | Up to 90s |
| Assistant query | 15-45s | Up to 60s |
| Document upload (10 pages) | 5-15s | Up to 30s |
| Model discovery | 5-10s | Up to 20s |

**If slower**:
- Switch to faster model (qwen2.5:3b)
- Close other GPU apps
- Check GPU isn't thermal throttling

---

## 🔄 Automated Testing

**Run the test suite**:

```bash
cd d:\Projects\pactlyn-ai

# Run all tests
uv run pytest

# Run with coverage
uv run coverage run --source=src/pactlyn -m pytest
uv run coverage report -m

# Run specific test file
uv run pytest tests/unit/test_capture.py

# Run with verbose output
uv run pytest -v -s
```

**Expected**:
- All tests pass (green)
- Coverage > 70%
- No critical warnings

**Test categories**:
- `tests/unit/` - Unit tests (fast, no external services)
- `tests/integration/` - Integration tests (database, services)
- `tests/ui/` - UI tests (Qt components)

---

## 🎯 Acceptance Criteria

**Pactlyn is working correctly if**:

✅ **Core Features**:
- Captures natural language commitments
- Extracts structured fields (person, deadline, action)
- Saves to database without errors
- Shows commitments in UI

✅ **AI Features**:
- Model discovery finds installed models
- Assistant answers questions about commitments
- No timeout errors (or rare)
- Answers are relevant and formatted

✅ **Document Features**:
- PDFs upload successfully
- Can query document content
- Citations show document name + page
- No brackets [1][2] in answers

✅ **Memory Features**:
- Facts extracted from captures
- Memory page shows entries
- Hybrid search combines sources

✅ **UI Features**:
- Theme switches work
- Search filters work
- Status changes work
- Settings persist across restarts

✅ **Performance**:
- Responses under 60s (qwen3:4b)
- UI stays responsive during processing
- No crashes or freezes

---

## 📝 Bug Reporting

**If you find issues, document**:

1. **What you did** (steps to reproduce)
2. **What you expected**
3. **What actually happened**
4. **Screenshots** (if UI issue)
5. **Terminal logs** (for errors)
6. **System info**:
   - Model: qwen3:4b, qwen2.5:7b, etc.
   - GPU: GTX 1650 4GB
   - OS: Windows/Linux
   - Pactlyn version: `git log -1 --oneline`

**Report at**: [GitHub Issues](https://github.com/Rayan-Mohammed-Rafeeq/pactlyn-ai/issues)

---

## 🚀 Next Steps After Testing

Once all tests pass:

1. **Daily use**: Start capturing real commitments
2. **Upload docs**: Add your actual work documents
3. **Explore features**: Try email, memory, hybrid search
4. **Customize**: Set your preferred theme, models
5. **Backup**: Create first backup for safety

---

**Happy testing! 🧪**
