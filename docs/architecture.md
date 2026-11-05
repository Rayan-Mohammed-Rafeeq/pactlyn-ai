# Pactlyn architecture

Pactlyn is a single-user, local-first desktop process. SQLite is the source of
truth for commitments, reminders, email history, approvals and memories.
Qdrant local persistent mode is a dedicated semantic index and never replaces
relational records. The Qdrant client is owned by the application container so
only one application process writes local mode.

The dependency direction is UI → application services → domain/storage and
provider interfaces. LLM, email, credentials, notifications and vector store
adapters are replaceable boundaries. Model output is parsed through Pydantic,
then confirmation and policy checks occur before effects.

The capture graph is a typed LangGraph workflow:

`normalise → extract → validate → approval (when uncertain) → persist`

External effects are passed into the graph as explicit callbacks. The email
service hashes the complete payload when approved and sends only if that exact
hash still matches. The hash includes From, To, CC/BCC, Reply-To, subject, both
body formats, custom headers and attachments; editing any field invalidates the
approval. Retries reuse a stable idempotency key, and uncertain outcomes are not
auto-retried.

## Email configuration and delivery

Email configuration has two stores with different trust levels:

* `EmailSettingsRepository` persists non-secret identity, sender, receiving,
  signature, tone, reply and polling preferences in SQLite
  (`UserProfile`, `UserPreference`, `EmailAccount`).
* `CredentialStore` persists the Resend API key only in the OS keyring.

`EmailPreferences.resolved()` applies `PACTLYN_RESEND_*` environment fallbacks
only until the user first saves Settings → Email. The `email.initialized`
preference then makes SQLite authoritative. `AppContainer` builds the Resend
provider from the keyring key, falling back to the environment key only before
the first save and when no keyring value exists. `refresh_email_provider()`
rebuilds it after settings changes.

`EmailComposer` combines saved preferences with drafts and replies. New drafts
use the configured `Name <verified-address>` sender, default reply-to and
signature. Replies use the actual sender of the inbound message and preserve its
`In-Reply-To` and `References` headers. Personal mailbox domains are rejected as
senders.

`ResendProvider.check_connection()` performs read-only domain and receiving
checks; it never sends. Outbound mail is created as an `EmailSendAction` draft,
approved with an exact-payload hash, and sent only by `process_queue`. Inbound
mail is polled by `InboundEmailSync`, which stores provider IDs and threading
metadata, upserts contacts, matches threads and requires review for uncertain
associations. Incoming replies can mark a waiting commitment as response
received but never complete it automatically.

The production desktop capture worker calls the selected local Ollama gateway
asynchronously, validates structured Pydantic candidates, presents the editable
review dialog, and persists confirmed candidates plus provenance-aware episodic
memory. The assistant page uses the same Ollama embedding provider through
SQLite FTS5/Qdrant reciprocal-rank-fusion retrieval; answers cite the retrieved
local source identifiers and are not generated when local evidence is absent.

Embedding model name and discovered dimension are persisted in
`model_configurations`. Changing the active local embedding model invalidates
derived Qdrant points and marks canonical SQLite memory records for reindexing;
source records are preserved.

Qdrant collections are `commitment_memories`, `email_context` and
`personal_knowledge`. Memory records retain source type and source ID, and
deletion removes the corresponding point.

## Local-mode limitation

Qdrant's embedded local mode is appropriate for this single-user desktop but
is not a multi-process server. A future bundled Qdrant server can sit behind
the same `VectorStore` protocol if concurrent access becomes necessary.
