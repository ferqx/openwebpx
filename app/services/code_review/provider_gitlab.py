from __future__ import annotations

import hmac
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.services.scm import _normalize_gitlab_base_url


def canonicalize_gitlab_instance_url(value: str | None) -> str:
    normalized = _normalize_gitlab_base_url(value)
    parsed = urlsplit(normalized)
    path = parsed.path.rstrip("/")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            "",
        )
    )


def _canonicalize_gitlab_project_url(
    *,
    project_url: str | None,
    path_with_namespace: str | None,
) -> str | None:
    if not project_url or not project_url.strip():
        return None

    normalized = _normalize_gitlab_base_url(project_url)
    parsed = urlsplit(normalized)
    path = parsed.path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]

    namespace = (path_with_namespace or "").strip().strip("/")
    if namespace:
        suffix = f"/{namespace}"
        if path.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")

    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            "",
        )
    )


def verify_gitlab_webhook_token(
    *, secret: str | None, token_header: str | None
) -> bool:
    if not secret or not secret.strip() or not token_header:
        return False
    return hmac.compare_digest(secret.strip(), token_header.strip())


def normalize_gitlab_webhook_payload(
    payload: dict[str, Any],
    *,
    gitlab_base_url: str | None,
) -> dict[str, Any] | None:
    normalized_event_type = (
        str(payload.get("object_kind") or "webhook").strip().lower() or "webhook"
    )
    if normalized_event_type != "merge_request":
        return None

    project = payload.get("project")
    if not isinstance(project, dict):
        project = {}
    attributes = payload.get("object_attributes")
    if not isinstance(attributes, dict):
        raise ValueError("GitLab webhook payload missing object_attributes")
    diff_refs = payload.get("diff_refs")
    if not isinstance(diff_refs, dict):
        diff_refs = {}
    last_commit = attributes.get("last_commit")
    if not isinstance(last_commit, dict):
        last_commit = {}

    repository_id = project.get("id") or payload.get("project_id")
    if repository_id is None:
        raise ValueError("GitLab webhook payload missing project.id")

    external_pr_or_mr_id = attributes.get("iid") or attributes.get("id")
    head_commit_id = (
        last_commit.get("id")
        or attributes.get("last_commit_sha")
        or payload.get("checkout_sha")
    )
    base_commit_id = diff_refs.get("base_sha") or attributes.get("oldrev")

    instance_url = gitlab_base_url
    if not instance_url:
        instance_url = _canonicalize_gitlab_project_url(
            project_url=project.get("web_url") or project.get("git_http_url"),
            path_with_namespace=str(project.get("path_with_namespace") or "").strip()
            or None,
        )
    if not isinstance(instance_url, str) or not instance_url.strip():
        raise ValueError("GitLab webhook payload missing instance base URL")

    return {
        "provider": "gitlab",
        "repository_external_id": str(repository_id).strip(),
        "repository_identity_key": canonicalize_gitlab_instance_url(instance_url),
        "provider_event_type": normalized_event_type,
        "external_event_id": str(attributes.get("id") or "").strip() or None,
        "external_pr_or_mr_id": (
            str(external_pr_or_mr_id).strip()
            if external_pr_or_mr_id is not None
            else None
        ),
        "base_branch": str(attributes.get("target_branch") or "").strip() or None,
        "head_branch": str(attributes.get("source_branch") or "").strip() or None,
        "base_commit_id": str(base_commit_id).strip()
        if base_commit_id is not None
        else None,
        "head_commit_id": str(head_commit_id).strip()
        if head_commit_id is not None
        else None,
        "repository_full_name": str(project.get("path_with_namespace") or "").strip()
        or None,
        "raw_payload": payload,
    }
