# Resend setup

Pactlyn's primary email adapter is Resend. Verify a sender domain in Resend,
create an API key, store it through `CredentialStore` under
`resend_api_key`, and set `PACTLYN_RESEND_FROM` to the verified address.

Configure Resend receiving for the inbound address or domain used by Pactlyn.
The inbound synchroniser polls the receiving listing and retrieves message
content when needed. It stores provider IDs and threading headers locally, so
repeated polls are idempotent.

Resend receiving is intentionally narrower than Gmail/Outlook synchronisation:
Pactlyn only sees messages delivered through the configured Resend receiving
route. No public local webhook is required.

## Opt-in live validation

The live suite is skipped by default and can send one test email only to an
explicit allowlisted recipient:

```bash
export PACTLYN_LIVE_RESEND=1
export PACTLYN_LIVE_RESEND_FROM='verified@example.com'
export PACTLYN_LIVE_RESEND_RECIPIENT='test-recipient@example.com'
export PACTLYN_LIVE_RESEND_ALLOWLIST='test-recipient@example.com'
uv run pytest -m live tests/live
```

The API key is read from the OS credential store (`resend_api_key`); an
explicit `PACTLYN_LIVE_RESEND_API_KEY` environment variable is supported only
for isolated validation environments. The live test records no key or message
body in reports. Sender verification is validated by the provider accepting the
send; inbound listing and delivery reconciliation are exercised when the
configured Resend account exposes them.
