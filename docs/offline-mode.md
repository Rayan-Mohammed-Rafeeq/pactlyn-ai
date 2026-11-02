# Offline mode

Connectivity is represented by `ONLINE`, `OFFLINE`, `RESUMING` and `LIMITED`.
The core application does not need a network connection. Ollama is a local
HTTP service and must have its models installed before disconnecting. Resend
send/sync and OpenRouter inference are online-only.

Approved email actions are durable SQLite queue records. A timeout is not
interpreted as a safe-to-resend result: Resend idempotency keys and later
status reconciliation protect against duplicate delivery.

On launch, the reminder evaluator checks all persisted due reminders. It can
recover a missed reminder after downtime, but does not claim a notification was
delivered while the computer was off.
