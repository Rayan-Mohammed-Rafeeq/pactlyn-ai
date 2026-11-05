# Common Workflows

Real-world examples of using Pactlyn for different scenarios.

## Table of Contents

- [Project Management](#project-management)
- [Email Follow-ups](#email-follow-ups)
- [Meeting Management](#meeting-management)
- [Document Research](#document-research)
- [Personal Task Tracking](#personal-task-tracking)
- [Waiting For Items](#waiting-for-items)

---

## Project Management

### Scenario: Managing a Software Project

**Goal**: Track tasks, deadlines, and blockers for "Phoenix App Redesign" project

#### Step 1: Capture Initial Tasks

```
Home page → Type naturally:

"Need to complete Phoenix app wireframes by Friday"
"Get design approval from Sarah by next Monday"
"Implement authentication module by Dec 15"
"Waiting for API specs from backend team"
```

Each becomes a structured commitment.

#### Step 2: Track Dependencies

```
Commitments page → Edit commitment:

Task: "Implement authentication"
Depends on: "Waiting for API specs"
Status: Waiting
```

#### Step 3: Daily Check-in

```
Assistant page → Ask:

"What Phoenix tasks are due this week?"
"What am I waiting for on Phoenix project?"
"Show me blocked tasks"
```

Get AI-powered status report.

#### Step 4: Document Upload

```
Documents page → Upload:

- Phoenix_Requirements.pdf
- API_Specification.pdf
- Design_Mockups.pdf
```

#### Step 5: Hybrid Search

```
Assistant page → Search mode: Both (Hybrid) → Ask:

"What are the authentication requirements from the specs and my task list?"
"Summarize all Phoenix deadlines from documents and commitments"
```

---

## Email Follow-ups

### Scenario: Client Communication Tracking

**Goal**: Never forget to follow up with clients

#### Step 1: Capture Email Promises

```
Home page → Type:

"Promised to email Johnson Corp the proposal by Thursday"
"Need to follow up with Sarah if no response by Tuesday"
"Send invoice to Acme Inc by end of month"
```

#### Step 2: Set Reminders

Pactlyn auto-creates reminders. You can adjust:

```
Commitments page → Edit → Reminder:
Set to 24 hours before deadline
```

#### Step 3: Draft Follow-up

```
Email Centre → New Draft:

To: sarah@johnsoncorp.com
Subject: Following up on proposal
Body: [AI can help draft based on commitment context]
Related commitment: "Promised to email Johnson Corp"
```

#### Step 4: Approve & Send

```
Email Centre → Approve:
Review exact payload
Click "Approve exact payload"
Email queued and sent
```

#### Step 5: Track Status

```
Assistant page → Ask:

"What emails have I sent this week?"
"Who am I waiting to hear back from?"
"Show me overdue follow-ups"
```

---

## Meeting Management

### Scenario: Weekly Team Meeting

**Goal**: Track action items and follow-ups from meetings

#### Step 1: Capture During Meeting

```
Home page → Quick capture:

"John will send budget report by Friday"
"Sarah to review design by Tuesday"
"I need to schedule follow-up meeting next week"
"Waiting for legal approval on contract"
```

Use bulk capture: Type all items separated by newlines, capture together.

#### Step 2: Assign Responsibility

AI auto-detects:
- "John will..." → OTHER_PARTY_PERFORMS
- "I need to..." → USER_PERFORMS
- "Waiting for..." → USER_WAITING_FOR

Review and correct if needed.

#### Step 3: Upload Meeting Notes

```
Documents page → Upload:

TeamMeeting_2024-11-05.pdf
```

#### Step 4: Pre-Meeting Prep

Next week:

```
Assistant page → Ask:

"What action items from last week's meeting are still open?"
"Show me tasks assigned to John"
"What are we waiting for before next meeting?"
```

---

## Document Research

### Scenario: Contract Analysis

**Goal**: Answer questions about multiple contracts

#### Step 1: Upload Contracts

```
Documents page → Upload:

- VendorContract_Acme.pdf
- ClientAgreement_Smith.pdf
- NDA_Johnson.pdf
```

Wait for processing (embeddings created).

#### Step 2: Ask Comparative Questions

```
Assistant page → Search mode: Uploaded Documents → Ask:

"What are the termination clauses across all contracts?"
"Compare payment terms in Acme vs Smith contracts"
"List all deadlines mentioned in the documents"
"What are the confidentiality terms in the NDAs?"
```

#### Step 3: Extract Commitments from Documents

```
Assistant page → Ask:

"What deliverables are mentioned in the Smith contract?"
```

Then capture them:

```
Home page → Type:

"Deliver Phase 1 to Smith by March 15 per contract"
"Submit monthly reports to Acme per vendor agreement"
```

#### Step 4: Track Document-Related Tasks

```
Assistant page → Search mode: Both (Hybrid) → Ask:

"What tasks relate to the Acme contract?"
"Show me commitments linked to uploaded agreements"
```

---

## Personal Task Tracking

### Scenario: Balancing Work and Life

**Goal**: Track both work deadlines and personal commitments

#### Work Tasks

```
Home page → Capture:

"Submit quarterly report by Friday 5pm"
"Prepare presentation for Monday meeting"
"Review team code by EOD Thursday"
```

#### Personal Tasks

```
Home page → Capture:

"Call dentist to schedule appointment this week"
"Buy birthday gift for Mom by Saturday"
"Submit tax documents by April 15"
```

#### Daily Planning

```
Assistant page → Ask:

"What's due today?"
"What do I need to do this week?"
"Show me personal vs work tasks"
```

#### Weekly Review

```
Commitments page → Filter:

All statuses → Completed
Review what you accomplished
Mark incomplete as postponed or cancelled if needed
```

---

## Waiting For Items

### Scenario: Dependencies Tracking

**Goal**: Track what you're waiting on from others

#### Step 1: Capture Waiting Items

```
Home page → Type:

"Waiting for John's approval on proposal"
"Waiting for IT to fix server issue"
"Waiting for Sarah to send budget numbers"
"Waiting for client signature on contract"
```

AI auto-categorizes as USER_WAITING_FOR.

#### Step 2: Set Follow-up Reminders

```
Commitments page → Edit each:

Reminder: 3 days from now
Description: "Follow up if no response by [date]"
```

#### Step 3: Daily Check

```
Assistant page → Ask:

"What am I waiting for?"
"Who owes me responses?"
"What's blocking my work?"
```

#### Step 4: Follow Up

When reminder triggers:

```
Email Centre → New Draft:

To: john@company.com
Subject: Following up on proposal approval
Body: "Hi John, checking in on the proposal I sent last week..."
```

#### Step 5: Update Status

After receiving response:

```
Commitments page → Double-click item:
Status changes to Completed
```

Or if still waiting:

```
Commitments page → Snooze:
Hide for 2 more days
```

---

## Advanced Workflow: Research Project

### Scenario: Academic/Technical Research

**Goal**: Track papers, deadlines, and research tasks

#### Phase 1: Literature Review

```
Documents page → Upload:

- Paper_A.pdf
- Paper_B.pdf
- Conference_Guidelines.pdf
```

```
Assistant page → Ask:

"What methodologies are used in Paper A vs Paper B?"
"Summarize the key findings across all papers"
"What are the submission deadlines in the conference guidelines?"
```

#### Phase 2: Capture Deadlines

```
Home page → Capture:

"Submit abstract by January 15"
"Complete experiments by February 28"
"Final paper submission by March 31"
"Prepare presentation by April 15"
```

#### Phase 3: Track Progress

```
Commitments page → Create milestones:

Title: "Literature review complete"
Due: Jan 10
Dependencies: None

Title: "Experiments complete"  
Due: Feb 28
Dependencies: "Literature review complete"

Title: "Paper written"
Due: Mar 25
Dependencies: "Experiments complete"
```

#### Phase 4: Daily Research Log

```
Memory page → Check what's stored:

Facts about papers, methodologies, findings
Relationships between research tasks
Timeline of progress
```

```
Assistant page → Ask:

"What papers discuss [topic]?"
"What experiments are still pending?"
"Summarize my progress this week"
```

---

## Workflow Tips

### Best Practices

**Capture immediately**: Don't wait. Type commitments as they come up in meetings, emails, conversations.

**Review daily**: Spend 5 minutes each morning asking:
- "What's due today?"
- "What am I waiting for?"
- "What should I prioritize?"

**Weekly cleanup**: Every Friday:
- Mark completed items
- Postpone low-priority tasks
- Cancel no-longer-needed commitments

**Use hybrid search**: When tasks relate to documents, use "Both" search mode for context-aware answers.

**Set reminder buffers**: Remind 24-48 hours before deadline, not on the deadline.

### Anti-Patterns (What Not to Do)

**❌ Vague captures**: "Do the thing" → No context, deadline, or person  
**✅ Specific captures**: "Send Q4 report to Sarah by Friday 5pm"

**❌ No follow-ups**: Capture "Waiting for John" and forget  
**✅ Active tracking**: Set reminder, ask "What am I waiting for?" daily

**❌ Ignoring Memory**: Never look at Memory page  
**✅ Explore relationships**: Use Memory to understand task dependencies

**❌ Manual email sending**: Draft in Gmail without tracking  
**✅ Use Email Centre**: Draft, approve, track in one place

**❌ Uploading everything**: Every PDF ever received  
**✅ Upload selectively**: Only documents you need to query

---

## Integration Ideas

### With Existing Tools

**Calendar sync** (coming v0.9):
- Export commitments with due dates to iCal
- Import to Google Calendar, Outlook, etc.

**Browser extension** (future):
- Capture commitments from web pages
- Save research articles directly to Documents

**Mobile companion** (v1.0):
- View-only mobile app
- Check commitments on the go
- Get notifications

**Team collaboration** (future):
- Self-hosted Pactlyn server
- Shared commitments for team projects
- Permission-based access

---

## Custom Workflows

### Create Your Own

**Template: [Workflow Name]**

**Goal**: [What you're trying to achieve]

**Steps**:
1. [Capture step]
2. [Organization step]
3. [Query step]
4. [Follow-up step]

**Assistant queries to use**:
- "[Question 1]"
- "[Question 2]"

**Expected outcome**: [What success looks like]

---

## Next Steps

- Read [User Guide](user-guide.md) for detailed feature explanations
- Check [Settings Guide](settings.md) for configuration options
- Explore [Privacy & Security](privacy.md) for data protection details

---

**Build workflows that work for you! 🚀**
