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
hash still matches. Retries reuse a stable idempotency key.

Qdrant collections are `commitment_memories`, `email_context` and
`personal_knowledge`. Memory records retain source type and source ID, and
deletion removes the corresponding point.

## Local-mode limitation

Qdrant's embedded local mode is appropriate for this single-user desktop but
is not a multi-process server. A future bundled Qdrant server can sit behind
the same `VectorStore` protocol if concurrent access becomes necessary.
