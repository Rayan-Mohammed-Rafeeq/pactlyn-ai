# Pactlyn 0.7 validation

## Scope

0.7 adds a structured event intermediate representation while preserving the
existing SQLite, Qdrant, Ollama, LangGraph, local-first, and approval-gated
architecture. Candidates now carry stable event IDs, source spans, actor,
action, object, beneficiary, deadline owner, condition, and responsibility.
Relationships retain indexed endpoints and also resolve to event IDs.

Invalid, self-referential, duplicate, unresolved, unsupported, reversed, and
cyclic relationships are retained as review warnings while valid events remain
available for confirmation. Conditional follow-ups stay blocked until their
response/approval condition is satisfied. RAG answers require question-relevant
local evidence and exact citations; otherwise the service abstains.

## Frozen datasets

`evaluation/datasets/commitments-0.7.json`

- 160 examples; train 70, development 30, validation 30, held-out 30
- 110 multi-commitment examples
- 60 dependency/conditional examples
- 30 multiple-contact examples
- SHA-256: `ab043d218995381d1d48629ab8df01952800617c9fca3d3dd1c85554d778ec04`

`evaluation/datasets/rag-0.7.json`

- 28 reviewed local sources and 60 source-linked queries
- includes answerable multi-source questions and explicit no-answer cases
- SHA-256: `51226e02aebf2592c1ba4f6be0758534d0a9cd38f87a15e206ac8e7bb44831cb`

The 0.6 datasets and reports remain unchanged.

## Extraction results

The deterministic held-out baseline is reported in
`evaluation/reports/heldout-0.7.json`:

| Metric | Deterministic | Qwen2.5 7B |
|---|---:|---:|
| Event F1 | 0.8454 | 0.8800 |
| Event count accuracy | 0.6000 | 0.7000 |
| Exact multi-event accuracy | 0.1667 | 0.0556 |
| Relationship F1 | 0.2273 | 0.0444 |
| Responsibility direction | 0.7333 | 0.0000 |
| Conditional accuracy | 0.7667 | 0.9000 |
| Negation accuracy | 1.0000 | 1.0000 |
| Mean latency | local parser | 8650.53 ms |

The results show improved event counting and conditional detection from Qwen,
but directed relationship and responsibility errors remain a release risk for
automatic persistence. Relationship edges therefore remain confirmation-gated.

## RAG grounding and abstention

`evaluation/reports/grounding-0.7.json` records dense, FTS5, and hybrid
retrieval with Qdrant persistence verification. The real Ollama embedding
hybrid run achieved Recall@5 0.7636 and Recall@10 1.0; the deterministic hybrid
baseline achieved 0.5818 and 0.7818.

`evaluation/reports/abstention-0.7.json` evaluates evidence sufficiency,
exact-source citation coverage, unsupported-answer rate, and safe abstention.
The real Ollama hybrid results were:

- evidence sufficiency/citation coverage: 1.0000
- safe no-answer abstention: 1.0000
- unsupported-answer rate: 0.0000
- abstention accuracy: 0.9167

The service also rejects uncited or forged citations at answer time.

## Regression coverage

Added end-to-end coverage for conditional follow-up, multi-person workflow,
correction/supersession, relationship warnings, grounded answers, and no-answer
abstention. The full test suite currently passes **52 tests**, with **2 live
Resend tests skipped** unless explicitly enabled.

Additional checks passed:

- Ruff
- mypy across `src/pactlyn` and 0.7 evaluation runners
- Alembic upgrade through `7b0_event_intermediate_fields`
- package build

The new migration adds the structured commitment columns and event ID index to
existing databases.
