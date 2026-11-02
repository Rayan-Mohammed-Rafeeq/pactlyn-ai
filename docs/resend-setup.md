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
