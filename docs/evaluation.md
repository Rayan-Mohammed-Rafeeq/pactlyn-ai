# Testing and evaluation

The default suite uses SQLite temporary databases, deterministic embeddings,
fake email providers and HTTP mocks. It never sends a real email or requires
Ollama. Run it with `uv run pytest`.

Coverage can be measured with `uv run coverage run --source=src/pactlyn -m
pytest && uv run coverage report -m`; the current suite reports 42% overall,
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

When Ollama is installed and running, compare the actual configured local model
with:

```bash
uv run python evaluation/run_ollama.py
```

If Ollama is unavailable, the report records `status: unavailable` and does not
invent model results.
