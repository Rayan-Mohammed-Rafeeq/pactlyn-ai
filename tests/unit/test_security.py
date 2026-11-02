from pactlyn.security.approvals import approval_is_valid, payload_hash
from pactlyn.security.redaction import redact_sensitive


def test_email_approval_is_invalidated_by_payload_edit():
    payload = dict(sender="me@example.com", recipients=["them@example.com"], cc=[], bcc=[], reply_to=None, subject="Hello", body_text="Body", body_html=None)
    digest = payload_hash(**payload)
    assert approval_is_valid(digest, **payload)
    assert not approval_is_valid(digest, **{**payload, "subject": "Edited"})


def test_redaction_does_not_leak_secret():
    assert "super-secret" not in redact_sensitive("api_key=super-secret")
