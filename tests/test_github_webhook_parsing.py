import hashlib
import hmac

import pytest

from scie.webhooks.github import (
    InvalidSignatureError,
    parse_github_push_payload,
    verify_github_signature,
)

SECRET = "test-secret"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature_accepts_valid_signature():
    body = b'{"hello": "world"}'
    verify_github_signature(body, _sign(body), SECRET)  # should not raise


def test_verify_signature_rejects_missing_header():
    with pytest.raises(InvalidSignatureError):
        verify_github_signature(b"{}", None, SECRET)


def test_verify_signature_rejects_wrong_signature():
    with pytest.raises(InvalidSignatureError):
        verify_github_signature(b"{}", "sha256=deadbeef", SECRET)


def test_parse_github_push_payload_extracts_repo_event():
    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "mlessley/scie"},
        "head_commit": {
            "id": "abc123",
            "author": {"username": "mlessley"},
            "message": "add feature",
            "timestamp": "2026-07-04T12:00:00+00:00",
        },
    }
    event = parse_github_push_payload(payload)
    assert event.commit_sha == "abc123"
    assert event.repo == "mlessley/scie"
    assert event.branch == "main"
    assert event.author == "mlessley"
    assert event.event_type == "push"
