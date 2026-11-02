# Privacy

There is no mandatory telemetry or cloud analytics. SQLite, Qdrant and local
memory remain on the user's computer. API keys are stored using the Linux OS
credential store through Python keyring and never in the database.

Email content necessarily passes through Resend when sending or receiving.
OpenRouter is disabled unless explicitly configured and selected; only the
context sent for that request leaves the machine. Local model inference and
local embeddings do not send personal content to a hosted embedding service.
