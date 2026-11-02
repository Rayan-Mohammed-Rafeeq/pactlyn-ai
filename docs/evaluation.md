# Testing and evaluation

The default suite uses SQLite temporary databases, deterministic embeddings,
fake email providers and HTTP mocks. It never sends a real email or requires
Ollama. Run it with `uv run pytest`.

Coverage can be measured with `uv run coverage run --source=src/pactlyn -m
pytest && uv run coverage report -m`; the current suite reports 44% overall,
with the Qt UI and live provider adapters intentionally requiring separate
integration checks.

The evaluation framework should score a versioned synthetic dataset on
extraction precision/recall/F1, deadline and contact accuracy, ambiguity
escalation, RAG Recall@5/MRR, duplicate reminders, duplicate emails and
offline operation. Live model comparisons must record model, prompt, dataset,
latency and environment; no benchmark result is claimed until generated from
an actual run.

The checked-in deterministic baseline can be reproduced with:

```bash
uv run python evaluation/run_baseline.py
```

Its generated report is `evaluation/reports/baseline.json`.

The labelled local retrieval benchmark can be run with:

```bash
uv run python evaluation/run_rag.py
```

It records Recall@5, MRR, precision, deletion consistency and reindexing in
`evaluation/reports/rag.json`. The current report uses the deterministic local
evaluation embedder because Ollama is unavailable.

The real embedding benchmark is separate and never treats deterministic vectors
as semantic-model evidence:

```bash
uv run python evaluation/run_rag_real.py
```

It writes `evaluation/reports/rag-real.json`. It records both the deterministic
harness result and the real Ollama result only when the configured embedding
model is installed.

When Ollama is installed and running, compare the actual configured local model
with:

```bash
uv run python evaluation/run_ollama.py
```

If Ollama is unavailable, the report records `status: unavailable` and does not
invent model results.

The 150-example comparison and scoring definitions are generated with:

```bash
uv run python evaluation/run_extraction_comparison.py
```

The configured-model report is `evaluation/reports/ollama-extraction.json`.
An explicitly overridden model run is stored separately, for example
`ollama-extraction-qwen2.5-7b.json`; it must not be read as a result for the
configured model.

The local portion of the Rahul waiting-for end-to-end scenario can be run with:

```bash
uv run python evaluation/run_scenario.py
```

It verifies extraction, persistence, memory, retrieval, approval-bound email
queueing and restart persistence. Live reply synchronisation and external send
are explicitly marked unavailable when the providers are not configured.
