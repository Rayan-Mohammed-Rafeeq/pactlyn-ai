# Resend setup

Pactlyn uses [Resend](https://resend.com) as its email provider. Configure it in
the desktop app under **Settings → Email**; you do not need to edit `.env`, use a
terminal, or store secrets in a file.

## 1. Prepare the Resend account

1. Create or sign in to a Resend account.
2. Add a domain you own under **Resend → Domains** and complete DNS
   verification. A personal Gmail, Outlook, Yahoo or similar mailbox cannot be
   used as the sender.
3. Create an API key under **Resend → API Keys**. A **full-access** key is
   recommended: Pactlyn needs `GET /domains` to verify the sender and
   `GET /emails/receiving` to test and read incoming mail. A sending-only key
   can still send approved email, but domain and receiving status will be
   reported as unavailable.
4. If you want incoming mail, enable **Receiving** for a custom domain in Resend
   or use the managed `<id>.resend.app` receiving address shown in Resend.
   Entering an arbitrary address in Pactlyn does not activate receiving.

## 2. Configure identity and sender

Open **Settings → Email**.

* **Your identity** — your full name, personal email address, default
  signature and preferred tone. The personal address is used for signatures and
  can be the default reply-to. It is never used implicitly as the sender.
* **Resend configuration** — paste the API key and click **Save API key**. The
  field is masked; **Show** reveals only what you have just typed. A saved key is
  never displayed in full again.
* Enter a **sender name** and a **sender email** at your verified Resend domain.
  Pactlyn formats the From header as `Name <address>`.
* Click **Test connection**.

The API key is stored only in the operating-system keyring under service
`io.pactlyn.desktop` and entry `resend_api_key`. It is never written to SQLite,
JSON settings, logs, `.env`, or a backup created by Pactlyn. If the keyring is
locked or unavailable, Pactlyn reports the problem and refuses to save rather
than falling back to plaintext storage.

### Test connection is read-only

**Test connection** makes safe reads only:

* `GET /domains` to verify the sender domain and sending capability;
* an optional one-item `GET /emails/receiving` when a receiving address is
  configured, to check inbox API access.

It never sends an email, creates a draft, or changes provider state. Possible
results include:

| Result | Meaning |
| --- | --- |
| Connected | Credentials are valid and the sender domain is verified for sending. |
| Sender domain unverified | The key worked but the sender domain is missing, pending, or not enabled for sending. Complete DNS verification in Resend. |
| Invalid API key | The saved key was rejected. Replace it. |
| API key permission denied | The key cannot perform the requested read. Use a full-access key. |
| Connected (restricted) | A sending-only key is valid, but domain and receiving checks need full access. |
| Rate limited / provider error | Resend asked Pactlyn to wait or is temporarily unavailable. Try again later. |
| Network unavailable | The Resend API could not be reached. Check connectivity. |
| Invalid sender | The sender address is malformed or is a personal mailbox address. |

## 3. Configure incoming email

Resend only delivers inbound mail to its managed `<id>.resend.app` address or a
custom domain with receiving enabled. In **Settings → Email → Incoming email**:

1. Enter that exact address as the **receiving address**;
2. tick **Enable inbound email synchronisation** if you want automatic polling;
3. choose an interval between 5 and 1440 minutes, or click **Synchronise now**.

Pactlyn polls the receiving API. No public webhook or port forwarding is needed.
Repeated polls are idempotent: provider message IDs are stored, and the same
message is not imported twice. Pactlyn preserves `Message-ID`, `In-Reply-To` and
`References`, associates known contacts, matches messages to existing threads,
and marks uncertain associations as needing review.

Inbound mail is untrusted. A reply can move a waiting commitment to
**response received**, but Pactlyn never completes a commitment automatically;
the user confirms the outcome. New threads with only a suggested contact match
also require review.

## 4. Choose email behaviour

**Default reply destination** can be:

* your personal email address, or
* Pactlyn's configured receiving address.

This affects new outgoing drafts. When you reply to a message received through
Pactlyn, Pactlyn always addresses the reply to that message's actual sender and
preserves its threading headers, regardless of the default.

**Always require approval before sending** is enabled and cannot be disabled.
Before anything enters the send queue, the exact payload must be confirmed:
From, To, CC/BCC, Reply-To, Subject, body, custom headers and attachments.
Editing any of those fields invalidates the previous approval.

## 5. Send a test email

**Send test email** is separate from **Test connection** and sends one real
message:

1. enter a recipient;
2. review the exact From, To, Reply-To, subject and message;
3. tick the confirmation box and confirm the second prompt.

The message is created as a draft, approved through the normal approval path,
and sent through the queue. Only that explicit action is processed, so other
queued mail is not sent. The result distinguishes **API acceptance** from
**delivery status**: Resend accepting the message means the API call succeeded,
not that it reached the recipient's inbox. Later reconciliation can update
delivery state.

## 6. Settings precedence and environment fallback

Values saved in **Settings → Email** live in local SQLite and take precedence
over stale environment variables. The first successful save marks the settings
as initialized; from then on, changing `.env` does not override the UI.

Environment values are a development, test and CI fallback only, used before the
first save:

```bash
PACTLYN_RESEND_FROM='Pactlyn <pactlyn@your-domain.example>'
PACTLYN_RESEND_INBOUND_ADDRESS='your-id@abc123.resend.app'
PACTLYN_RESEND_API_KEY='re_...'   # isolated development only
```

The keyring is checked first for the API key. `PACTLYN_RESEND_API_KEY` is used
only before the first settings save and only when no key is stored in the
keyring; after that, removing the keyring key cannot silently reactivate a
stale `.env` value. Do not put a production key in a tracked file or `.env`.
`.env` is ignored by git and should have user-only permissions.

## 7. Troubleshooting

* **Keyring unavailable** — unlock GNOME Keyring/KWallet, or install a supported
  secret service. Saving and removing a key fail visibly; Pactlyn does not store
  the key in SQLite.
* **Sender domain unverified** — finish DNS verification in Resend and check
  that the domain has sending enabled. `resend.dev` is a testing sender that
  only delivers to the account owner.
* **Receiving address is a personal mailbox** — use the Resend-managed
  `<id>.resend.app` address or enable receiving on a domain you own.
* **No incoming messages** — confirm receiving is enabled in Resend, the
  address matches, and the API key has full access. Use **Synchronise now** and
  inspect the status shown under Incoming email.
* **Rate limits or provider downtime** — wait and retry; approved messages stay
  queued locally. An uncertain send is not retried automatically, to avoid
  duplicates.

## 8. Validation

Ordinary tests use mocked HTTP transports and local SQLite. They cover
configuration persistence, keyring failure, sender validation, read-only
connection checks, scoped test-email queueing, approval invalidation, inbound
metadata, duplicate suppression and response review.

Live Resend tests are opt-in and require an explicit allowlisted recipient:

```bash
export PACTLYN_LIVE_RESEND=1
export PACTLYN_LIVE_RESEND_FROM='verified@example.com'
export PACTLYN_LIVE_RESEND_RECIPIENT='test-recipient@example.com'
export PACTLYN_LIVE_RESEND_ALLOWLIST='test-recipient@example.com'
uv run pytest -m live tests/live
```

The API key is read from the OS credential store (`resend_api_key`); an explicit
`PACTLYN_LIVE_RESEND_API_KEY` environment variable is supported only for
isolated validation environments. The live tests do not write keys or message
bodies to reports.
