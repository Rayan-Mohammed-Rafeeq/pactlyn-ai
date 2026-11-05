# Pactlyn 0.8 validation

## Audit and scope

The 0.7 artifacts remain preserved. The 0.7 commitment dataset hash is
`ab043d218995381d1d48629ab8df01952800617c9fca3d3dd1c85554d778ec04` with 160
examples split 70 train, 30 development, 30 validation, and 30 held-out. The
recorded 0.7 Qwen run used `qwen2.5:7b`, the `improved` prompt, and 30 held-out
examples. Its relationship precision/recall/F1 were 0.0714/0.0323/0.0444.
Those 30 examples are not conclusive generalisation evidence.

0.8 keeps the existing SQLite, Qdrant, Ollama, LangGraph, local-first, and
approval-gated architecture. It separates event extraction from relationship
classification and validation, preserves rejected-edge audit records, and
adds retrieval modes and evidence assessment without adding cloud requirements.

## Frozen 0.8 datasets

`evaluation/datasets/relationships-0.8.json`

- 120 relationship-focused scenarios: 84 development and 36 held-out
- 12 balanced categories, including dependencies, conditional fallbacks,
  waiting-for, multiple contacts, historical events, supersession, negation,
  ambiguity, multiple targets, circular-looking dependencies, unrelated
  chronology, and non-causal related events
- SHA-256: `e9340d14af4da4a68a74248c9b50689e4fa1baadea04f1d38f1b2ba278c42927`

`evaluation/datasets/rag-0.8.json`

- 18 source records and 60 mixed queries
- 48 answerable and 12 unanswerable queries
- multi-source/multi-hop questions require at least two labelled records
- SHA-256: `05ffb673a4d8c2c7f2481b23dec733fbd5505fad3bbc41825cd6c2c1a2bd0aea`

The labels are independently authored in the dataset generators and do not
use model predictions.

## Relationship reasoning

The full deterministic 0.8 held-out baseline has edge precision/recall/F1 of
0.2000/0.0833/0.1176, with 15 predicted edges and 36 expected edges. Its
direction accuracy is 0.0909 over 33 expected directed endpoint pairs, exact
graph accuracy is 0.2500 over 36 graphs, and invalid-edge rate is 0.1667 over
18 predicted-or-rejected edges. These metrics expose the main remaining issue:
chronology is still easier to identify than causal direction.

The live Qwen comparison uses the same `qwen2.5:7b` model and one held-out
example per category (12 examples). It is explicitly a latency-bounded pilot,
not generalisation evidence:

| Configuration | Calls/example | Edge F1 | Direction | Exact graph | Mean ms | P95 ms |
|---|---:|---:|---:|---:|---:|---:|
| A single-pass | 1 | 0.1053 | 0.2727 | 0.3333 | 10879.13 | 11974.15 |
| B events → relationships | 2 | 0.4000 | 0.3636 | 0.3333 | 11296.95 | 15609.61 |
| C candidate edges → validation | 2 | 0.0952 | 0.0909 | 0.1667 | 15740.54 | 45874.01 |
| D staged with context | 2 | 0.2500 | 0.2727 | 0.2500 | 19979.54 | 25186.65 |

The exact denominators, P95 values, failure examples, and all rows are in
`evaluation/reports/relationship-reasoning-0.8.json`. Configuration B is the
best pilot result, but its 12-example sample is too small to claim a release-
wide improvement over 0.7.

## Graph integrity and recommendations

`evaluation/reports/graph-integrity-0.8.json` passes 6/6 checks: events survive
rejected edges, rejection reasons are retained, dependency cycles are detected,
edge evidence/confidence persist, rejected edges are audited, and deletion does
not leave dangling graph references.

Relationships now store evidence, confidence, and validation status. Rejected
edges are written to `commitment_relationship_reviews`. Stable event IDs remain
the bridge between extraction and persistence. Recommendations include evidence,
triggering condition, commitment IDs, and confirmation state. The recommendation
report passes 7/7 transition and safety checks.

## Retrieval ranking

The real Ollama `nomic-embed-text` / Qdrant run is recorded in
`evaluation/reports/retrieval-ranking-0.8.json` with 768-dimensional vectors.
All configurations use the same 60 queries and 48-answerable denominator:

| Mode | Recall@5 | Recall@10 | Precision@5 | MRR | NDCG@5 |
|---|---:|---:|---:|---:|---:|
| Dense | 1.0000 | 1.0000 | 0.3367 | 0.7151 | 0.6708 |
| FTS5 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| Hybrid | 0.9524 | 1.0000 | 0.3133 | 0.6939 | 0.6182 |
| RRF | 0.9524 | 1.0000 | 0.3133 | 0.6939 | 0.6182 |
| Hybrid + lightweight rerank | 1.0000 | 1.0000 | 0.3367 | 0.9167 | 0.7399 |

The reranker improves MRR and NDCG without increasing duplicate-context rate,
but Precision@5 remains limited because the benchmark intentionally contains
similar distractors. FTS5's zero result is a reporting signal for the current
source-indexed corpus path, not evidence that lexical retrieval is generally
useless; it should remain under investigation.

## Answerability and multi-hop RAG

The 0.8 multi-hop benchmark uses the same real 768-dimensional local embeddings
and Qdrant store. The Qwen2.5 7B run achieved evidence completeness 0.7708 and
multi-source retrieval recall 0.9115 over 48 multi-hop answerable queries.
Generated-answer accuracy was 1.0 on 48 evaluated answers, groundedness was
0.875, and citation correctness was 0.875. Mean latency was 5917.16 ms and P95
latency was 13447.36 ms.

`evaluation/reports/answerability-0.8.json` separates 48 answerable and 12
unanswerable questions. It reports answer accuracy 1.0, groundedness 0.875,
citation precision 0.9556, citation recall 0.875, abstention precision 0.5217,
abstention recall 1.0, false-abstention rate 0.2292, unsupported-answer rate
0.0, and answer coverage on answerable questions 0.7708. The false-abstention
rate is retained as a limitation rather than optimized by refusing all queries.

## Verification

- 56 tests passed; 2 explicitly enabled live Resend tests skipped
- Ruff passed
- mypy passed across `src/pactlyn` and `evaluation`
- Alembic upgrade through `8c0_relationship_review_audit` passed
- package build passed
- Qdrant persistence and deletion consistency remain covered

Known limitations are the small live relationship pilot, weak deterministic
causal-direction baseline, and unavailable chat completion in the first
multi-hop run. No external action or cloud fallback is introduced.
