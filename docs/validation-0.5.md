# Pactlyn 0.5 controlled extraction and retrieval validation

Evaluation date: 2026-11-03. All extraction runs use `evaluation_now=2026-11-02T10:00:00Z`, UTC, the same checked-in 150-example dataset, the same Pydantic schema, and the same scoring code.

## Model comparison

Reports: `evaluation/reports/experiments/consolidated-comparison.json`.

| Configuration | Type accuracy | Deadline P/R/F1 | Contact presence P/R/F1 | Mean ms | P95 ms |
|---|---:|---:|---:|---:|---:|
| Existing Qwen2.5 7B prompt | 82.67% | 64.29/100/78.26% | 100/85.33/92.09% | 2261 | 2948 |
| Improved Qwen2.5 7B | 90.00% | 86.54/100/92.78% | 100/100/100% | 3460 | 5314 |
| Improved 7B + existing-contact context, final corrected validator | 90.00% | 100/100/100% | 100/100/100% | 2449 | 3696 |
| Improved Qwen2.5 3B | 70.67% | 100/93.33/96.55% | 100/82.67/90.51% | 11028 | 45074 |
| Deterministic baseline | 90.00% | 60/100/75.00% | 100/100/100% | 0.034 | 0.034 |

The context configuration had no matching existing contact records in the benchmark process. It must therefore be interpreted as an empty-context control, not evidence that retrieved contact context improves extraction. The earlier C report (97.83% deadline precision) was superseded by the final corrected validator run.

Recommended default: **Qwen2.5 7B with the improved prompt and grounded validation**. It is the strongest balanced local model among the measured alternatives. The deterministic parser remains the low-latency fallback, not the general semantic extractor.

## Deadline analysis

The original improved run had 70% precision and 46.67% recall because validation repaired dates inconsistently and waiting/postponement language was treated as a user deadline. The corrected B run reached 86.54% precision and 100% recall. The context control reached 97.83% precision and 100% recall.

The validator now:

- preserves the other party's expected date as relationship evidence rather than a user-owned due date;
- creates a separate conditional `FOLLOW_UP` candidate when the source explicitly says the user will contact someone on a later date;
- treats postponement as a dependency/state transition rather than an immediate deadline;
- copies dates only from the candidate's grounded evidence span;
- retains unresolved values instead of inventing them.

Regression coverage includes the Rahul-Friday/Monday example and postponement handling.

## Independent identity evaluation

`evaluation/datasets/commitments-heldout.json` is manually authored and versioned as `commitments-heldout-v1`; it was not used for prompt tuning. On 30 examples with Qwen2.5 7B:

- Type accuracy: 86.67%
- Contact presence: precision 100%, recall 95.45%
- Exact contact value accuracy: 95.45%
- Person/organisation kind accuracy: 95.45%
- Contact-role accuracy: 77.27%
- Resolved/unresolved accuracy: 86.36%
- Multi-commitment accuracy: 0% on the two multi-commitment examples

The original 150-example set cannot measure identity accuracy because it contains only `has_contact`.

## Retrieval and embeddings

`evaluation/datasets/retrieval-expanded.json` contains 52 manually authored queries spanning commitments, contacts, emails, waiting relationships, completed items, dates, dependencies and distractors.

Real `nomic-embed-text` through Ollama produced 768-dimensional vectors and persisted them in local Qdrant:

- Dense: Recall@5/10 100%/100%, MRR 0.9712, mean 223.07 ms, P95 1687.74 ms
- FTS5: Recall@5/10 86.54%/98.08%, MRR 0.4963, mean 0.32 ms, P95 0.47 ms
- Hybrid: Recall@5/10 100%/100%, MRR 0.9712, mean 43.64 ms, P95 56.52 ms
- Empty-result rate: 0%
- Qdrant dimension and reopen persistence: verified at 768

## Hardware

Ollama runtime counters recorded:

- Qwen2.5 7B Q4_K_M: 4.76 GB VRAM
- Qwen2.5 3B Q4_K_M: 2.16 GB VRAM
- Host RAM: 23.7 GB

`nvidia-smi` is unavailable inside this container, so no independent GPU utilization reading is claimed. The VRAM figures are Ollama's runtime `size_vram` values.

## Verification

- 42 tests passed; 2 live-email tests skipped by their explicit opt-in marker.
- Ruff passed.
- Mypy passed for application and new evaluation utilities.
- Alembic migrations passed against a temporary SQLite database.
- `uv build` passed.

Known limitations: the held-out set is 30 examples, multi-commitment coverage is only two examples, the 52-query retrieval benchmark has manually authored relevance labels but is not a production traffic sample, and the selected Qwen model remains below perfect role and multi-commitment reliability.
