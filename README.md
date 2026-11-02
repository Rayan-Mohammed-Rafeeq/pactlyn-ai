# Pactlyn

**Remember what matters. Follow through.**

Pactlyn is a local-first Linux desktop assistant for commitments, waiting-for
items and approved follow-up email. You can write “I need to submit my
assignment by Friday” and Pactlyn extracts a reviewable commitment, stores it
in SQLite, indexes provenance in local Qdrant and schedules a persistent
reminder. It is designed to remain useful offline after local model setup.

## Current release

The repository contains a working 0.1 foundation: a PySide6 desktop shell,
SQLite/SQLAlchemy persistence, Qdrant local-mode storage, a deterministic
capture baseline, Ollama and explicit OpenRouter gateways, a LangGraph capture
workflow, reminder recovery, provenance-aware memory, Resend outbound queueing
and inbound polling adapters. Desktop capture runs Ollama asynchronously,
supports editable multi-commitment review, and only offers a clearly labelled
offline fallback after a model failure.

The desktop app does not silently use a cloud model. Resend delivery is only
possible after a user approves an exact payload.

## Install and run on Linux

Python 3.11+ is supported by the current environment; Python 3.12+ is
recommended for new installations.

```bash
sudo apt install python3 python3-venv  # PySide6 wheels normally need no Qt apt packages
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --extra dev
uv run pactlyn
```

Pactlyn stores data under `~/.local/share/pactlyn/` by default:

* `pactlyn.sqlite3` — canonical structured data, FTS5 and audit records
* `qdrant/` — Qdrant local persistent vector collections

Set `PACTLYN_DATA_DIR` to choose another private directory. Do not put it in a
shared or synchronised folder. `.env.example` lists non-secret settings.

## Ollama setup

Install Ollama from <https://ollama.com>, then install a chat model and an
embedding model, for example:

```bash
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

Pactlyn checks the local endpoint at `http://127.0.0.1:11434`. Configure it
with `PACTLYN_OLLAMA_URL`, `PACTLYN_OLLAMA_MODEL` and
`PACTLYN_OLLAMA_EMBEDDING_MODEL`. If Ollama is unavailable, the UI explains the
failure and asks before using the conservative rule-based fallback; model output
is never treated as confirmed fact automatically.

## Resend setup

Resend is optional and online-only. Create an API key, verify a sending domain,
and configure the receiving address/domain in Resend. Store the key in the OS
credential manager instead of `.env` or SQLite:

```python
from pactlyn.security.credentials import CredentialStore
CredentialStore().set("resend_api_key", "re_...")
```

Set `PACTLYN_RESEND_FROM` to the verified sender. Pactlyn processes inbound
messages addressed to the configured Resend receiving address/domain through
polling; this is not unrestricted Gmail or Outlook inbox synchronisation.
Email content necessarily passes through Resend during transmission.

## Offline behavior

SQLite, Qdrant local mode, capture, local embeddings, reminders, memory and
email drafts work without internet. Approved outbound email actions remain in
the local queue until a configured Resend provider is available. There is no
automatic OpenRouter fallback. OpenRouter is an explicit optional provider,
disabled by default, and must be enabled separately with a credential-store key.

## Backup and restore

Use Settings → Create backup or `BackupService`. Password-protected backups
encrypt the SQLite database and local Qdrant files. Restore requires restarting
Pactlyn so local stores are reopened safely.

## Development and checks

```bash
uv run pytest
uv run coverage run --source=src/pactlyn -m pytest
uv run coverage report -m
uv run ruff check src tests
uv run mypy src
```

External services are replaced with test doubles in ordinary tests. Live
Resend and Ollama checks require explicit user credentials/services and are not
run by the default test suite.

## Architecture

See:

* [Architecture](docs/architecture.md)
* [Linux setup](docs/setup-linux.md)
* [Offline mode](docs/offline-mode.md)
* [Resend setup](docs/resend-setup.md)
* [Privacy](docs/privacy.md)
* [Security](docs/security.md)
* [Testing and evaluation](docs/evaluation.md)
* [0.2 validation report](docs/validation-0.2.md)
* [Roadmap](docs/roadmap.md)

## License

MIT. See [LICENSE](LICENSE).
