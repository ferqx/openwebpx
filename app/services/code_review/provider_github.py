from __future__ import annotations

import hashlib
import hmac
from typing import Any


def verify_github_webhook_signature(
    *,
    secret: str | None,
    body: bytes,
    signature_header: str | None,
) -> bool:
    if not secret or not secret.strip() or not signature_header:
        return False
    expected = (
        f"sha256={hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()}"
    )
    return hmac.compare_digest(expected, signature_header.strip())


def normalize_github_webhook_payload(
    payload: dict[str, Any],
    *,
    event_type: str | None = None,
) -> dict[str, Any] | None:
    normalized_event_type = (
        event_type or "pull_request"
    ).strip().lower() or "pull_request"
    if normalized_event_type != "pull_request":
        return None

    repository = payload.get("repository")
    if not isinstance(repository, dict):
        raise ValueError("GitHub webhook payload missing repository")
    pull_request = payload.get("pull_request")
    if not isinstance(pull_request, dict):
        raise ValueError("GitHub webhook payload missing pull_request")

    repository_id = repository.get("id")
    if repository_id is None:
        raise ValueError("GitHub webhook payload missing repository.id")

    head = pull_request.get("head")
    if not isinstance(head, dict):
        head = {}
    base = pull_request.get("base")
    if not isinstance(base, dict):
        base = {}

    external_pr_or_mr_id = pull_request.get("number", pull_request.get("id"))
    head_commit_id = head.get("sha")
    base_commit_id = base.get("sha")
    return {
        "provider": "github",
        "repository_external_id": str(repository_id).strip(),
        "repository_identity_key": "",
        "provider_event_type": normalized_event_type,
        "external_event_id": str(pull_request.get("id") or "").strip() or None,
        "external_pr_or_mr_id": (
            str(external_pr_or_mr_id).strip()
            if external_pr_or_mr_id is not None
            else None
        ),
        "base_branch": str(base.get("ref") or "").strip() or None,
        "head_branch": str(head.get("ref") or "").strip() or None,
        "base_commit_id": str(base_commit_id).strip()
        if base_commit_id is not None
        else None,
        "head_commit_id": str(head_commit_id).strip()
        if head_commit_id is not None
        else None,
        "repository_full_name": str(repository.get("full_name") or "").strip() or None,
        "raw_payload": payload,
    }
