# Offline mode

Connectivity is represented by `ONLINE`, `OFFLINE`, `RESUMING` and `LIMITED`.
The core application does not need a network connection. Ollama is a local
HTTP service and must have its models installed before disconnecting. Resend
send/sync and OpenRouter inference are online-only.

Approved email actions are durable SQLite queue records. A timeout becomes
`UNKNOWN`, not an automatic retry. The user must reconcile or explicitly retry;
Resend idempotency keys and later status reconciliation protect against
duplicate delivery.

On launch, the reminder evaluator checks all persisted due reminders. It can
recover a missed reminder after downtime, but does not claim a notification was
delivered while the computer was off.

The physical network-isolation harness is:

```bash
unshare -n env QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  .venv/bin/python evaluation/run_offline.py
```

The current result is in `evaluation/reports/offline.json`: SQLite, Qdrant
local storage, the desktop shell, commitment persistence, reminder evaluation
and local email queueing passed. Ollama and local embedding/RAG validation are
recorded as unavailable because no Ollama service was installed or running.
