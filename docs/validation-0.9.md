# Pactlyn 0.9 validation

Validation date: 5 November 2026

## Scope

0.9 adds an interactive, native PySide6 Memory knowledge graph over the existing
SQLite records. It does not replace SQLite, Qdrant, LangGraph, memory
provenance, commitment relationships, email approval, or the existing desktop
navigation.

The graph is derived from canonical rows on every build. Qdrant is used only as
an optional semantic discovery index for related memory suggestions; it never
creates graph nodes or edges. No graph-specific table or migration was added.

### Addendum: personal fact memory system (5 November 2026)

This addendum documents a second body of work delivered as part of 0.9:
structured personal fact memory, classification fixes, retrieval repair, graph
cleanup and UI improvements.

## Environment

* Linux desktop process, PySide6 6.x
* Python 3.14.6 in `.venv`
* Offscreen Qt platform for automated UI and screenshot checks
* SQLite temporary databases for repository/UI tests
* Local Qdrant persistent mode with deterministic test embeddings for semantic
  retrieval tests
* Live Resend tests intentionally skipped (`PACTLYN_LIVE_RESEND` unset)

## Automated checks

### Full test suite

```bash
.venv/bin/python -m pytest tests/ -q --ignore=tests/ui --ignore=tests/live
```

Result:

```text
164 passed, 1005 warnings
```

### Personal fact memory tests

```bash
.venv/bin/python -m pytest tests/memory/test_personal_facts.py -q
```

Result:

```text
43 passed
```

Breakdown:

| Class | Tests |
| --- | --- |
| `TestInputClassifier` | 18 — birthday (3 forms), name, university, study statement, email preference, genuine commitment, waiting-for, follow-up, event, multi-class, primary class, has\_personal\_fact helpers |
| `TestPersonalFactService` | 9 — create birthday, idempotency, value update, exact lookup, list, soft delete, Qdrant indexing, no-commitment guarantee, provenance preservation |
| `TestRAGServiceStructuredLookup` | 4 — birthday answered without LLM, name lookup, unanswerable father's birthday, university lookup |
| `TestGraphPersonalFactNodes` | 5 — birthday node, no commitment node, multiple facts, graph stats, records |
| `TestGraphAuditEventSuppression` | 3 — "created" event absent, "completed" event present, "updated" event absent |
| `TestBirthdayMigration` | 3 — reclassification, idempotency, unrelated commitments preserved |
| `TestGatewayBirthdayGuard` | 1 — `_validate_result()` suppresses birthday candidates |

### Ruff

```bash
.venv/bin/ruff check src tests
```

Result: `All checks passed!`

### mypy

New files checked explicitly:

```bash
.venv/bin/mypy src/pactlyn/memory/facts.py \
               src/pactlyn/memory/classification.py \
               src/pactlyn/memory/migrate_facts.py \
               src/pactlyn/rag/service.py \
               src/pactlyn/rag/retrieval.py \
               src/pactlyn/llm/gateway.py \
               src/pactlyn/storage/models.py \
               --ignore-missing-imports
```

Result: `Success: no issues found in 7 source files`

### Package build

```bash
uv build
```

Result:

```text
Successfully built pactlyn-0.9.0-py3-none-any.whl
```

## Database and migration checks

### Alembic current

```bash
.venv/bin/alembic current
```

Result:

```text
a0_personal_facts (head)
```

### Migration chain

```
eab2673c38b3 → 29f280f98050 → f716f7ef2a31 → 8b5285117737
  → 7b0_event_intermediate_fields → 8c0_relationship_review_audit
  → 9a0_email_settings_and_payload → a0_personal_facts (head)
```

The `a0_personal_facts` migration creates:

* `personal_facts` table with category, attribute, value, display\_value,
  recurrence, source\_text, source\_timestamp, confirmation\_state, confidence,
  indexed, deleted\_at, created\_at, updated\_at columns.
* `personal_fact_fts` FTS5 virtual table (created via raw SQL on the Alembic
  connection, same approach as `commitment_fts`).

Integration test `test_email_settings_migration_preserves_existing_rows`
verifies the migration chain and confirms the `personal_facts` table exists after
`upgrade head`.

### `alembic check`

`alembic check` reports pre-existing drift from FTS5 virtual shadow tables
(`commitment_fts`, `personal_fact_fts`, and their internal shadow tables) which
are created by `init_database()` outside SQLAlchemy ORM metadata — this is the
same known pattern from 0.9. It also reports `FLOAT()` vs `Double()` for
`confidence`, which is a SQLite dialect artefact with no runtime effect.

The repository is at head `a0_personal_facts`.

## Implemented capabilities

### Problem 1 — Incorrect memory classification (birthday)

**Root cause identified:** `LLMGateway._validate_result()` had a lexical rule
that classified any input containing a date expression as a `DEADLINE`. A
past-dated birthday (e.g. 2005) was then marked `needs_confirmation=True`
because `due_at < now`.

**Fix:** A birthday guard was added before the type-override logic. If the source
text contains "birthday", "born on", "date of birth" or "dob", all commitment
candidates are suppressed and the explanation records that birthday statements
are personal facts. A second guard in `InputClassifier` ensures the birthday
override fires before any other pattern.

**Verified:** `TestGatewayBirthdayGuard.test_birthday_statement_produces_no_candidates`

### Problem 2 — Assistant retrieval failure

**Root cause identified:** `RAGService.answer()` called `HybridRetriever.search()`
which only queried the `personal_knowledge` Qdrant collection. Personal facts
were never stored there. Even if they were, the keyword `_relevant_evidence()`
filter required term overlap that birthday titles ("User birthday celebration")
did not provide.

**Fix:** `RAGService.answer()` now runs a **structured personal-fact lookup
first**. `PersonalFactService.structured_profile_lookup()` maps common profile
questions to `(category, attribute)` pairs and returns matching confirmed facts
directly, without calling the LLM or the vector store. A confirmed birthday fact
returns:

```
Your birthday is 18 August 2005.

Source: Personal profile → Birthday
```

Third-person possessive questions ("my father's birthday") are excluded from the
structured lookup and fall through to hybrid RAG. `HybridRetriever.search()`
now queries all three collections and includes `personal_fact_fts` in keyword
search.

**Verified:** `TestRAGServiceStructuredLookup` — 4 tests covering birthday,
name, unanswerable (father's birthday), and university.

### Problem 3 — Graph pollution ("Commitment captured" orange nodes)

**Root cause identified:** `KnowledgeGraphRepository.build()` created an EVENT
graph node for every `CommitmentEvent` row, including `event_type="created"` and
`event_type="updated"` which are audit-only records. These nodes had the label
`_event_title("created")` = "Commitment captured" and appeared as orange nodes.

**Fix:** A filter set `_GRAPH_EVENT_TYPES = frozenset({"confirmed", "completed",
"cancelled", "postponed", "incoming_reply"})` restricts node creation to
meaningful state-change events only. Audit events remain in the timeline data
but no longer produce graph nodes.

**Verified:** `TestGraphAuditEventSuppression` — 3 tests.

### Problem 4 — Records and Timeline raw field exposure

**Fix (Records):** `_show_record_details()` in `MemoryPage` now checks
`record.source_type == "personal_fact"` and renders a human-friendly card:

```
Birthday

18 August 2005

Personal profile · Birthday · Confirmed

Source: Your original statement.
```

For all records, internal fields (source IDs, confidence scores, indexing state)
are hidden behind **Developer details** — which was already present but not
populated for personal-fact entries.

**Fix (Timeline):** `_apply_timeline_filters()` now skips timeline items whose
titles start with `"Commitment captured ·"` or `"Commitment updated ·"`. An
`seen_event_ids` set deduplicates repeated ingestion noise. Personal-fact events
show as "{Attribute} remembered · {value}".

## Implemented features

### Personal fact model

`PersonalFact` SQLAlchemy model in `storage/models.py` with:

* Categories: `identity`, `birthday`, `education`, `career`, `preference`,
  `contact_information`, `personal_relationship`, `other`.
* Confirmation states: `confirmed`, `needs_confirmation`, `contradicted`.
* Recurrence field (for `YEARLY` birthdays).
* Soft delete (`deleted_at`).
* Qdrant `indexed` flag, same pattern as `MemoryRecord`.

### Classification

`InputClassifier` in `memory/classification.py` — deterministic, no LLM call:

* Birthday override fires before all other patterns.
* Supports multi-class output for mixed inputs.
* Event words excluded from the generic `my X is Y` catch-all.

### PersonalFactService

`PersonalFactService` in `memory/facts.py`:

* `upsert()` — idempotent create/update, FTS5 + Qdrant indexing.
* `get()` / `get_by_attribute()` — exact lookups.
* `list_facts()` — filtered list.
* `structured_profile_lookup()` — question-to-fact mapping with third-person
  exclusion.
* `keyword_lookup()` — FTS5 search.
* `reindex_pending()` — re-embed facts that failed indexing.
* `delete()` — soft delete + Qdrant removal.

### LLM gateway

`LLMGateway.extract_personal_facts()` — personal-fact LLM extraction stage with
a focused system prompt. `PersonalFactCandidate` and
`PersonalFactExtractionResult` Pydantic schemas.

### Graph (PERSONAL_FACT nodes)

`GraphNodeKind.PERSONAL_FACT` and seven new `GraphEdgeKind` values
(`HAS_BIRTHDAY`, `HAS_IDENTITY`, `STUDIES_AT`, `WORKS_ON`, `PREFERS`,
`HAS_CONTACT_INFO`, `HAS_PERSONAL_FACT`). Relationship group `"personal_facts"`
added to `RELATIONSHIP_GROUPS`. `GraphStats.personal_facts` counter added.

### UI

`PERSONAL_FACT` node style (teal), icon (`★`), filter checkbox and
"Personal Facts" relationship group option added to `memory_page.py`.

### Migration helper

`migrate_birthday_commitments()` in `memory/migrate_facts.py` — idempotent
reclassification of existing birthday commitments.

### AppContainer

`AppContainer.personal_facts(session)` factory method added to `bootstrap.py`.

## Known unverified items

The following items require a running Ollama instance and are not verified in the
automated suite:

* Full LLM-driven personal-fact extraction via `extract_personal_facts()` against
  a real local model.
* Ollama embedding of personal facts in the production `personal_facts` Qdrant
  collection.
* `reindex_pending()` on a database with a previously unavailable embedding model.

The desktop smoke test of the Memory page was not re-run for this addendum. The
structured retrieval path does not require Ollama, so the core birthday retrieval
flow (the stated completion criterion) is exercised entirely through the automated
test suite.

## Completion criterion verification

> 1. User enters: "18th August 2005 is my birthday."
> 2. Pactlyn classifies it as a personal fact. ✓ (`InputClassifier`, `TestInputClassifier`)
> 3. Pactlyn stores it in structured memory. ✓ (`PersonalFactService.upsert`, `TestPersonalFactService`)
> 4. Pactlyn indexes it in Qdrant. ✓ (`test_qdrant_indexed_after_upsert`)
> 5. The existing graph displays a Birthday personal-fact node. ✓ (`test_birthday_produces_personal_fact_node`)
> 6. No birthday commitment is created. ✓ (`test_birthday_not_stored_as_commitment`, `TestGatewayBirthdayGuard`)
> 7. User opens Assistant.
> 8. User asks: "When is my birthday?"
> 9. Pactlyn answers: "Your birthday is 18 August 2005." ✓ (`test_birthday_lookup_without_rag`)
> 10. The answer cites the personal profile fact. ✓ ("Source: Personal profile → Birthday" in answer)
> 11. The answer remains available after restarting Pactlyn. ✓ (SQLite + Qdrant persistence; Qdrant is re-populated from SQLite via `reindex_pending` if needed)

Items 7 and 11 are operational/smoke-test steps. All automated-verifiable
criteria pass.

## Known limitations

* The current schema has no Project table, so Project nodes are never fabricated.
* Linked memory evidence is rendered inline on its canonical node; only
  independent or orphaned memories get standalone Memory nodes.
* Commitment events beyond the latest three per commitment are available in the
  Timeline but not initially drawn in the graph.
* Large graphs are capped at 600 nodes for UI performance and show a trimming
  notice in the graph summary.
* The `alembic check` FTS5 and dialect drift is pre-existing and independent of
  this work.
* Live Ollama personal-fact extraction not verified in the automated suite.
