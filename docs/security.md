# Security model

Incoming emails, attachments, imported documents and retrieved memories are
untrusted data. They are never inserted into system instructions. Model output
has no unrestricted filesystem, database or provider access; actions must be
registered and validated.

## Credentials

The Resend API key is a secret and is stored only in the operating-system
keyring through `CredentialStore`:

* service: `io.pactlyn.desktop`
* entry: `resend_api_key`

The key is never written to SQLite, JSON settings, logs, backups created by
Pactlyn, or `.env`. The Settings → Email field is masked, and a saved key is
never displayed in full again. If the keyring is locked, missing or otherwise
unavailable, saving or removing a key fails visibly with an explanation.
Pactlyn does not fall back to plaintext storage.

`PACTLYN_RESEND_API_KEY` and the other `PACTLYN_RESEND_*` values are
development, test and CI fallbacks only. They are used before the user first
saves Settings → Email; after that, SQLite values take precedence. The keyring
is always preferred over an environment API key, and the environment key
fallback stops after the first settings save. Production users should not put
secrets in `.env`.

Non-secret email configuration (personal identity, sender, receiving address,
signature, tone, reply destination and polling interval) is stored in local
SQLite. It never includes the API key.

## Outbound approval

Email approval is bound to a SHA-256 canonical hash of every sending-relevant
field:

* sender, To, CC and BCC;
* Reply-To;
* subject, plain-text body and optional HTML body;
* custom headers such as `Message-ID`, `In-Reply-To` and `References`;
* attachment filenames, content types and base64 content.

Any edit invalidates the approval. `process_queue` recomputes the hash and
refuses to send when the current payload differs from the approved one. Approved
actions reuse a stable action-specific idempotency key. An uncertain provider
outcome (for example a timeout after the request) moves the action to an unknown
state and is not retried automatically, to avoid duplicate delivery. Audit
records retain the operation ID and provider result.

Sending approval cannot be disabled. The checkbox in Settings → Email is
immutable, and the persistence layer always writes the requirement as enabled.

## Connection tests and test email

**Test connection** is read-only. It calls `GET /domains` and, when configured,
a one-item `GET /emails/receiving`. It never sends mail or changes provider
state.

**Send test email** is a separate action. It requires a recipient, shows the
exact payload, requires explicit confirmation, creates a normal draft, records
approval, and processes only that action from the queue. API acceptance is
reported separately from delivery status.

## Inbound email

Inbound messages are untrusted and may contain prompt-injection attempts.
Pactlyn stores and displays their content but does not treat instructions in
them as system or developer instructions. Provider message IDs are unique
locally, so repeated polling is idempotent. Thread matching uses preserved
`Message-ID`, `In-Reply-To` and `References` metadata plus provider thread IDs.

A reply can move a waiting commitment to **response received** for review.
Pactlyn never completes a commitment automatically. New threads with only a
suggested contact match require user review before association.

## Local data protection

The local data directory should have normal user-only permissions (Pactlyn
creates it with mode `0700`). Users should use encrypted operating-system
backups where available and can remove the directory to delete local data.
Backups contain SQLite and local Qdrant data but never the keyring secret.
