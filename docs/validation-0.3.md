# Pactlyn 0.3 local-AI validation

This report records the environment and experiments run for the 0.3 sprint.
Unavailable services are not counted as successful tests.

## Environment

* Ollama server: `0.40.7` at `http://127.0.0.1:11434`
* `ollama --version`: CLI is not installed in the application shell, although
  the local HTTP server is reachable
* Configured LLM: `llama3.2:3b` — **not installed**
* Configured embedding model: `nomic-embed-text` — **not installed**
* Installed Ollama model: `qwen2.5:7b`, Q4_K_M, 7.6B parameters, embedding length reported by Ollama as 3584 but not exposed as an embedding capability
* OpenRouter: not used
* Resend: remains opt-in and was not used in this sprint

The configured-model result is in `evaluation/reports/ollama-extraction.json`.

## Real local LLM extraction

An explicit `PACTLYN_OLLAMA_MODEL=qwen2.5:7b` override ran the existing 150
examples against the real local Ollama server. This is a real model result, but
it is not a result for the configured `llama3.2:3b` model:

* Type accuracy: 38.67%
* Confirmation accuracy: 50.00%
* Deadline presence accuracy: 80.00%
* Deadline precision/recall/F1: 60.27% / 97.78% / 74.58%
* Contact presence accuracy: 51.33%
* Contact precision/recall/F1: 100.00% / 2.67% / 5.19%
* Empty results: 28/150
* Mean / median / P95 latency: 2253.64 / 2366.62 / 3023.47 ms

Evidence: `evaluation/reports/ollama-extraction-qwen2.5-7b.json` and
`evaluation/reports/extraction-errors-qwen2.5-7b.json`. The first direct UI
workflow probe also executed real Ollama structured extraction in a Qt worker;
it took 2052.88 ms and returned a reviewable candidate, but the sample
misclassified the commitment type and omitted the deadline. Evidence:
`evaluation/reports/capture-ui.json`.

## Embeddings and RAG

Real Ollama embeddings and semantic RAG were **not available** because
`nomic-embed-text` is missing. `evaluation/reports/rag-real.json` includes a
deterministic harness result only: Recall@5 1.0, Recall@10 1.0, MRR 0.8833 and
precision@5 0.2. Those numbers are not semantic embedding evidence.

The application now batches Ollama `/api/embed` requests, validates dimensions,
persists model/dimension metadata, prevents incompatible vector mixing, and
marks canonical memories for reindexing after a model change.

## Local application changes verified without external services

* Capture inference and grounded assistant work run in Qt worker threads.
* Confirmed captures create provenance-aware memory records and Qdrant points.
* Hybrid retrieval supports metadata filters and source citations.
* Negated model captures are rejected by post-validation rather than saved.
* Duplicate memory sources are not indexed twice.
* Qdrant dimension changes and model changes are detected.

The explicit qwen performance probe measured mean/median/P95 model latency of
2190.77/2307.60/2307.60 ms and process maximum RSS of 65,660 KiB. GPU
utilisation, real embedding latency, and vector/database growth were not
claimed because the configured embedding model is unavailable.

## Checks

The default suite remains offline-safe: `36 passed, 2 live tests skipped`, with
44% measured source coverage in the current run.
Ruff and the existing migration checks must be run before release. Physical
network isolation can verify the local database/UI harness, but it is not an
offline-AI result unless Ollama is placed in the same contained namespace.

## Setup to complete target validation

Install Ollama, start it, and download the configured models:

```bash
ollama serve
ollama pull llama3.2:3b
ollama pull nomic-embed-text
uv run python evaluation/run_ollama.py
uv run python evaluation/run_rag_real.py
```

Then perform the contained offline run described in `docs/offline-mode.md`.
