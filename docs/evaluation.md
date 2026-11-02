# Testing and evaluation

The default suite uses SQLite temporary databases, deterministic embeddings,
fake email providers and HTTP mocks. It never sends a real email or requires
Ollama. Run it with `uv run pytest`.

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
