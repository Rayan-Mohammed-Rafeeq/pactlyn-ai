# Pactlyn 0.6 validation

Evaluation date: 2026-11-03. Existing 0.5 datasets remain unchanged. The new extraction corpus is `commitments-0.6-v1`, SHA-256 `867d6234fb36820fcf9a189a25a3fcc6ab736a95a47a9c6bae35dfd5d63a90e2`, with 220 manually authored examples, 88 multi-commitment examples, and stratified splits: 120 train, 40 development, 30 validation, 30 held-out. The held-out split contains ten scenario families with three examples each and was frozen before the model ablation.

## Multi-commitment and relationship implementation

Extraction now returns candidates plus indexed relationship edges. Supported edge types are `BLOCKED_BY`, `DEPENDS_ON`, `FOLLOWED_BY`, `RESPONSE_REQUIRED_FROM`, `RELATED_TO`, and `SUPERSEDES`.

Edges are persisted in the existing local `commitment_relationships` table, deduplicated, included in commitment FTS content, searchable through `CommitmentService`, and displayed in the desktop review and related-commitment panel. The recommendation engine explains blocked tasks, newly unblocked tasks, due waiting responses, and repeated postponements with source commitment IDs.

Deterministic 220-example result:

- Extraction F1: 96.43%
- Type accuracy: 75.00%
- Multi-commitment accuracy: 37.50%
- Dependency-edge accuracy: 50.00%
- Contact presence F1: 93.75%
- Deadline F1: 88.00%
- Negation accuracy: 100% on 11 no-active-commitment cases

The deterministic score is a parser result and is not attributed to Qwen.

## Ablation

Report: `evaluation/reports/ablation-0.6.json`. All configurations use the same 30-example frozen held-out split, UTC, `2026-11-02T10:00:00Z`, the same schema and scoring code.

| Configuration | Type | Extraction F1 | Deadline P/R/F1 | Contact P/R/F1 | Identity | Role | Multi | Dependencies |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Raw Qwen2.5 7B | 46.67% | 88.89% | 85.71/50.00/63.16% | 0/0/0% | 0% | 0% | 8.33% | 0% |
| Grounded validation | 60.00% | 88.00% | 100/41.67/58.82% | 100/77.78/87.50% | 44.44% | 25.93% | 8.33% | 0% |
| Validation + date normalization | 60.00% | 88.00% | 100/75.00/85.71% | 100/77.78/87.50% | 44.44% | 22.22% | 0% | 0% |
| Validation + dates + populated context | 60.00% | 88.00% | 100/75.00/85.71% | 100/77.78/87.50% | 44.44% | 33.33% | 0% | 0% |

The ablation shows that date normalization improves deadline recall, while structured validation improves contact presence and negation handling. The current Qwen held-out result remains weak on relationship generation and multi-commitment exactness; the deterministic parser handles some simple conjunctions but is not sufficient for general semantic extraction.

## Retrieval and grounded context

The populated RAG corpus is `rag-0.6-v1`: 28 local sources and 12 multi-source queries, including one no-answer query. It contains commitments, contacts, emails, completed/postponed records, dependencies, and user preferences. The context-assisted extraction ablation receives matching records from `context-fixture-0.6.json`; it is not an empty contact lookup.

Report: `evaluation/reports/rag-expanded-0.6.json`.

Real `nomic-embed-text` results were: dense Recall@5/10 100%/100%, Precision@5 91.67%, MRR 0.9091, mean/P95 44.36/54.77 ms; FTS5 Recall@5/10 36.36%/54.55%, Precision@5 33.33%, MRR 0.2569, mean/P95 0.11/0.13 ms; hybrid Recall@5/10 90.91%/100%, Precision@5 83.33%, MRR 0.5387, mean/P95 48.72/54.63 ms. Qdrant reopen persistence passed. No-answer retrieval currently returns evidence, so the generation layer must continue to say evidence is insufficient rather than infer an answer; this is a remaining limitation.

## End-to-end and privacy verification

- Multi-candidate capture, review, SQLite persistence, relationship persistence, Qdrant indexing, reminder delivery, local retrieval, email draft, approval, and mocked queue sending are covered by `tests/integration/test_end_to_end.py`.
- Email sending does not mark commitments complete.
- Recommendation output is local and cites commitment IDs in its data model.
- Ollama and `nomic-embed-text` remain local defaults; cloud use remains explicit opt-in.
- Existing Qdrant deletion, restart, email approval, inbound review, and persistence tests remain enabled.

## Known limitations

The new independent held-out set has 30 examples and three examples per included scenario family, so confidence intervals are wide. Multi-commitment and relationship quality is not yet at production reliability. Contact role accuracy is materially below contact identity accuracy. The RAG no-answer policy needs a retrieval threshold or calibrated abstention layer. GPU utilization telemetry is unavailable in the container, though Ollama runtime model memory was measured in 0.5.
