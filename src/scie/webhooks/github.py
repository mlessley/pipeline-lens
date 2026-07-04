import hashlib
import hmac
from datetime import datetime

from scie.models import RepoEvent


class InvalidSignatureError(Exception):
    pass


def verify_github_signature(payload_body: bytes, signature_header: str | None, secret: str) -> None:
    if signature_header is None:
        raise InvalidSignatureError("missing X-Hub-Signature-256 header")
    expected = "sha256=" + hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise InvalidSignatureError("signature mismatch")


def parse_github_push_payload(payload: dict) -> RepoEvent:
    head_commit = payload["head_commit"]
    return RepoEvent(
        commit_sha=head_commit["id"],
        repo=payload["repository"]["full_name"],
        branch=payload["ref"].removeprefix("refs/heads/"),
        author=head_commit["author"]["username"],
        message=head_commit["message"],
        pr_number=None,
        event_type="push",
        workflow_run_id=None,
        workflow_conclusion=None,
        timestamp=datetime.fromisoformat(head_commit["timestamp"]),
    )


def parse_github_workflow_run_payload(payload: dict) -> RepoEvent:
    workflow_run = payload["workflow_run"]
    head_commit = workflow_run["head_commit"]
    return RepoEvent(
        commit_sha=workflow_run["head_sha"],
        repo=payload["repository"]["full_name"],
        branch=workflow_run["head_branch"],
        author=head_commit["author"]["name"],
        message=head_commit["message"],
        pr_number=None,
        event_type="workflow_run",
        workflow_run_id=str(workflow_run["id"]),
        workflow_conclusion=workflow_run["conclusion"],
        timestamp=datetime.fromisoformat(workflow_run["updated_at"]),
    )
