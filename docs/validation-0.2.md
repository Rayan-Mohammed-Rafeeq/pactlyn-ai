# Pactlyn 0.2 validation report

Validation was executed from the repository on 2026-11-02.

## Results

| Area | Result | Evidence |
|---|---|---|
| Default tests | 29 passed, 2 live tests skipped | `uv run pytest -q` |
| Static checks | Ruff and mypy passed | `uv run ruff ...`, `uv run mypy ...` |
| Migrations | No pending operations | `uv run alembic check` |
| Coverage | 43% overall | `coverage report -m` |
| Physical offline | SQLite, Qdrant local storage, UI shell, commitments, reminders and email queue passed | `evaluation/reports/offline.json` |
| Ollama | Not available; no live model result claimed | `evaluation/reports/ollama.json` |
| Resend | Not configured; live suite skipped | `tests/live/test_resend_live.py` |
| Retrieval | Recall@5 1.0, MRR 0.8833, precision@5 1.0 | `evaluation/reports/rag.json` |
| Rahul scenario | Local persistence, memory, retrieval, approval and restart passed; external reply steps not run | `evaluation/reports/scenario.json` |

## Physical offline result

The offline harness ran inside `unshare -n`, which prevented DNS/network
access. It verified the PySide6 shell, SQLite writes, Qdrant local upsert and
search, reminder evaluation, local draft creation, approval queueing and no
cloud fallback. Ollama and production embeddings were unavailable because no
Ollama service was installed or running before isolation.

## External validation status

No Resend API key or allowlisted test recipient was configured. The opt-in live
suite is present but was not executed, so sender verification, real delivery,
inbound receiving, provider threading and live status reconciliation remain
unverified.

## Security review

Verified locally:

* Provider secrets use keyring and are absent from application configuration.
* Data directories are created with mode `0700`.
* Password backups use PBKDF2-HMAC-SHA256 and Fernet encryption.
* Exact email payload edits invalidate approval hashes.
* Uncertain provider outcomes become `UNKNOWN` and are not automatically retried.
* Incoming content is placed in an untrusted user-data channel and associations
  require review; replies move waiting commitments to `RESPONSE_RECEIVED`.
* SQLite deletion and Qdrant point deletion are tested together.

Known limitation: a provider timeout may not return a provider ID, so the
application conservatively holds the action in `UNKNOWN`; live provider-side
idempotency reconciliation still requires a configured Resend account.
