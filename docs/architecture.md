# Pactlyn architecture

Pactlyn is a single-user, local-first desktop process. SQLite is the source of
truth for commitments, reminders, email history, approvals and memories.
Qdrant local persistent mode is a dedicated semantic index and never replaces
relational records. The Qdrant client is owned by the application container so
only one application process writes local mode.

The dependency direction is UI → application services → domain/storage and
provider interfaces. LLM, email, credentials, notifications and vector store
adapters are replaceable boundaries. Model output is parsed through Pydantic,
then confirmation and policy checks occur before effects.

The capture graph is a typed LangGraph workflow:

`normalise → extract → validate → approval (when uncertain) → persist`

Before extraction reaches the LangGraph workflow, `InputClassifier` runs a
deterministic pre-classification pass. If the input is classified as
`PERSONAL_FACT`, the `PersonalFactService` path is taken instead of the
commitment capture graph. Inputs that produce both `PERSONAL_FACT` and
`COMMITMENT` classes run both paths so neither information type is lost.

External effects are passed into the graph as explicit callbacks. The email
service hashes the complete payload when approved and sends only if that exact
hash still matches. The hash includes From, To, CC/BCC, Reply-To, subject, both
body formats, custom headers and attachments; editing any field invalidates the
approval. Retries reuse a stable idempotency key, and uncertain outcomes are not
auto-retried.

## Email configuration and delivery

Email configuration has two stores with different trust levels:

* `EmailSettingsRepository` persists non-secret identity, sender, receiving,
  signature, tone, reply and polling preferences in SQLite
  (`UserProfile`, `UserPreference`, `EmailAccount`).
* `CredentialStore` persists the Resend API key only in the OS keyring.

`EmailPreferences.resolved()` applies `PACTLYN_RESEND_*` environment fallbacks
only until the user first saves Settings → Email. The `email.initialized`
preference then makes SQLite authoritative. `AppContainer` builds the Resend
provider from the keyring key, falling back to the environment key only before
the first save and when no keyring value exists. `refresh_email_provider()`
rebuilds it after settings changes.

`EmailComposer` combines saved preferences with drafts and replies. New drafts
use the configured `Name <verified-address>` sender, default reply-to and
signature. Replies use the actual sender of the inbound message and preserve its
`In-Reply-To` and `References` headers. Personal mailbox domains are rejected as
senders.

`ResendProvider.check_connection()` performs read-only domain and receiving
checks; it never sends. Outbound mail is created as an `EmailSendAction` draft,
approved with an exact-payload hash, and sent only by `process_queue`. Inbound
mail is polled by `InboundEmailSync`, which stores provider IDs and threading
metadata, upserts contacts, matches threads and requires review for uncertain
associations. Incoming replies can mark a waiting commitment as response
received but never complete it automatically.

The production desktop capture worker calls the selected local Ollama gateway
asynchronously, validates structured Pydantic candidates, presents the editable
review dialog, and persists confirmed candidates plus provenance-aware episodic
memory. The assistant page uses the same Ollama embedding provider through
SQLite FTS5/Qdrant reciprocal-rank-fusion retrieval; answers cite the retrieved
local source identifiers and are not generated when local evidence is absent.

Embedding model name and discovered dimension are persisted in
`model_configurations`. Changing the active local embedding model invalidates
derived Qdrant points and marks canonical SQLite memory records for reindexing;
source records are preserved.

Qdrant collections are `commitment_memories`, `email_context`, `personal_knowledge`
and `personal_facts`. Memory records retain source type and source ID, and
deletion removes the corresponding point. Personal facts have their own
collection and FTS5 table (`personal_fact_fts`) so they can be retrieved without
vector search.

## Personal fact memory

`PersonalFactService` in `pactlyn.memory.facts` stores stable facts about the
user (birthday, full name, university, email preference, current project, contact
details, etc.) in the `personal_facts` SQLite table and the `personal_facts`
Qdrant collection. Personal facts are not commitments — they produce no tasks,
deadlines or reminders unless the user explicitly requests one.

### Classification

`InputClassifier` in `pactlyn.memory.classification` runs a fast deterministic
pre-classification pass over every user input before extraction. It returns an
ordered set of `InputClass` values:

```
PERSONAL_FACT | COMMITMENT | WAITING_FOR | FOLLOW_UP | EVENT | GENERAL_NOTE
```

A single sentence can carry more than one class (e.g. a preference statement
together with a deadline). Classification happens before any LLM call.

A birthday statement is detected by a hard override pattern that always yields
`PERSONAL_FACT / birthday` regardless of the date it contains. This means "18th
August 2005 is my birthday" can never be misclassified as a deadline.

### Extraction

When classification produces `PERSONAL_FACT`, `LLMGateway.extract_personal_facts()`
sends the input to the local model with a focused system prompt. The prompt
supplies a concrete rule for birthdays: the value must be an ISO date, the
display value must be a readable string, and the recurrence must be `YEARLY`.
Category and attribute keys are normalised to lowercase snake\_case. The result
is a `PersonalFactExtractionResult` containing one or more `PersonalFactCandidate`
objects.

### Commitment guard

`LLMGateway._validate_result()` detects birthday/date-of-birth language and
suppresses any extracted commitment candidates, returning an explanation that
birthday statements are personal facts. This prevents a past-dated birthday
from entering the overdue or needs-confirmation commitment queue.

### Storage

`PersonalFactService.upsert()` stores a personal fact identified by
`(category, attribute)`. The operation is idempotent: if the same pair already
exists with the same value it returns the existing row without a write. A
changed value updates the row and re-indexes it. Every fact is embedded and
upserted into the `personal_facts` Qdrant collection. An FTS5 virtual table
(`personal_fact_fts`) enables keyword retrieval.

Categories: `identity`, `birthday`, `education`, `career`, `preference`,
`contact_information`, `personal_relationship`, `other`.

Confirmation state: `confirmed` (default), `needs_confirmation`, `contradicted`.

Recurrence: `YEARLY` for birthdays, `null` for all other facts.

### Retrieval

`RAGService.answer()` runs a **structured personal-fact lookup first**. If a
matching confirmed fact is found, the answer is returned directly without
reaching the LLM or the vector store. For a question such as "When is my
birthday?" the answer is:

```
Your birthday is 18 August 2005.

Source: Personal profile → Birthday
```

Third-person possession markers ("my father's birthday", "her name") bypass the
structured lookup and fall through to hybrid RAG. If no evidence is found at
all, the service abstains explicitly.

`HybridRetriever.search()` now queries all three collections
(`commitment_memories`, `personal_knowledge`, `personal_facts`) and includes the
`personal_fact_fts` virtual table in its keyword search.

### Graph representation

Personal facts produce `PERSONAL_FACT` graph nodes (teal colour) anchored to
the user's person node through semantic edge types:

```
USER  ─── HAS_BIRTHDAY ──► 18 August 2005 [PERSONAL_FACT]
      ─── STUDIES_AT ────► NMIT [PERSONAL_FACT]
      ─── WORKS_ON ──────► Pactlyn [PERSONAL_FACT]
      ─── PREFERS ───────► Professional email tone [PERSONAL_FACT]
```

Relationship group `personal_facts` covers all personal-fact edge types and can
be selected in the graph filter panel.

### Migration

`pactlyn.memory.migrate_facts.migrate_birthday_commitments()` is an idempotent
helper that scans existing active commitments for birthday language, extracts the
date, creates the corresponding `PersonalFact`, cancels the original commitment,
and preserves the audit trail. Running it a second time is safe — it detects the
existing fact and skips creation.

## Memory knowledge graph

`KnowledgeGraphRepository` in `pactlyn.memory.graph` is the application-service
boundary for the Memory page. It reads canonical rows from SQLite and returns
immutable typed nodes, edges, records, timeline entries, filters and statistics.
The Qt graphics layer never queries the database directly. This keeps graph
rendering, selection and navigation independent from persistence and makes the
repository testable against temporary SQLite databases.

The graph is derived, not stored. There is no graph table and no 0.9 migration.
It reads commitments and validated (non-rejected) commitment relationships,
contacts, email threads/messages/send actions, attachments, commitment events
and non-deleted memory records. Persons are deduplicated by normalized email
and name. Linked memory evidence is attached to the canonical node it belongs
to; a memory whose source no longer exists becomes an independent Memory node.
Project nodes are modelled but not fabricated because no Project table exists.

`BLOCKED_BY`, `DEPENDS_ON`, `FOLLOWED_BY`, `RESPONSE_REQUIRED_FROM`,
`RELATED_TO` and `SUPERSEDES` preserve stored edge direction. Person
responsibility, email participants, email/commitment associations and
attachments become explicit edges with evidence, confidence, review status and
provenance where available. Rejected relationships are not rendered. A hard
node cap (default 600, retaining the most connected/recent nodes) and per-query
row limits bound the work done by the synchronous repository and layout.

`MemoryPage` in `pactlyn.ui.memory_page` provides Graph, Records and Timeline
views using native PySide6 graphics. Layouts are deterministic and
relationship-aware. Selection, dragging, panning, zoom, fit, reset,
expand/collapse, neighbour highlighting, search, filters and detail panels stay
in the UI layer. Navigation emits typed requests that the main window maps to
the existing Commitments and Email Centre pages.

Optional semantic discovery lives in `pactlyn.memory.semantic`. It queries the
local Qdrant collections with the configured embedding provider, maps hits back
to canonical `MemoryRecord` rows through payload memory IDs (with source/content
fallbacks), and returns suggestions for the Graph search. This path never adds
nodes or edges; only canonical provenance can create a graph relationship.

## Local-mode limitation

Qdrant's embedded local mode is appropriate for this single-user desktop but
is not a multi-process server. A future bundled Qdrant server can sit behind
the same `VectorStore` protocol if concurrent access becomes necessary.
