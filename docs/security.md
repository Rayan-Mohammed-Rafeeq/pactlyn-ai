# Security model

Incoming emails, attachments, imported documents and retrieved memories are
untrusted data. They are never inserted into system instructions. Model output
has no unrestricted filesystem, database or provider access; actions must be
registered and validated.

Email approval is bound to a SHA-256 canonical hash of sender, recipients,
headers, subject and complete body. Any edit invalidates approval. A stable
action-specific idempotency key is reused for retries. Audit records retain
the operation ID and provider result.

The local data directory should have normal user-only permissions. Users should
use encrypted operating-system backups where available and can remove the
directory to delete local data. Future releases will expose export and backup
controls in the Settings page.
