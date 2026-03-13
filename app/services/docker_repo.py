from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlparse


def normalize_repo_provider(provider_raw: str) -> str | None:
    normalized = provider_raw.strip().lower()
    if normalized == "github":
        return "github"
    if normalized in {"gitlab", "gitlab_enterprise"}:
        return "gitlab"
    return None


def build_repo_binding(
    *,
    thread_id: str,
    user_id: str,
    metadata: dict[str, Any],
    scm_user_login: str,
    scm_user_name: str,
    scm_user_email: str,
) -> dict[str, str] | None:
    repo = str(metadata.get("repo") or "").strip()
    if not repo or repo in {"未绑定仓库", "none", "null"}:
        return None

    provider = normalize_repo_provider(str(metadata.get("provider") or ""))
    if provider is None:
        return None

    branch = str(metadata.get("branch") or "main").strip() or "main"
    gitlab_base_url = str(metadata.get("gitlab_base_url") or "").strip()
    github_auth_mode = str(metadata.get("github_auth_mode") or "").strip().lower()

    git_name = scm_user_name or scm_user_login
    git_email = scm_user_email
    if not git_email and scm_user_login:
        if provider == "github":
            git_email = f"{scm_user_login}@users.noreply.github.com"
        else:
            git_email = f"{scm_user_login}@users.noreply.gitlab.com"

    return {
        "thread_id": thread_id,
        "user_id": user_id,
        "provider": provider,
        "repo": repo,
        "branch": branch,
        "gitlab_base_url": gitlab_base_url,
        "github_auth_mode": github_auth_mode,
        "git_name": git_name,
        "git_email": git_email,
    }


def build_repo_sync_signature(*, container_id: str, binding: dict[str, str]) -> str:
    return "|".join(
        [
            container_id,
            binding["provider"],
            binding["repo"],
            binding["branch"],
            binding.get("gitlab_base_url", ""),
            binding.get("github_auth_mode", ""),
        ]
    )


def normalize_repo_auth_mode(binding: dict[str, str]) -> tuple[str | None, str | None]:
    provider = binding["provider"]
    gitlab_base_url = binding.get("gitlab_base_url") or None
    github_auth_mode = binding.get("github_auth_mode") if provider == "github" else None
    if github_auth_mode == "":
        github_auth_mode = None
    return gitlab_base_url, github_auth_mode


def build_repo_auth_context(binding: dict[str, str]) -> dict[str, str]:
    return {
        "user_id": binding["user_id"],
        "provider": binding["provider"],
        "repo": binding["repo"],
        "gitlab_base_url": binding.get("gitlab_base_url", ""),
        "github_auth_mode": binding.get("github_auth_mode", ""),
    }


def build_repo_git_identity(binding: dict[str, str]) -> dict[str, str]:
    return {
        "name": str(binding.get("git_name") or "").strip(),
        "email": str(binding.get("git_email") or "").strip().lower(),
    }


def sanitize_repo_sync_error(output: str, token: str) -> str:
    cleaned = output or ""
    if token:
        cleaned = cleaned.replace(token, "***")
        escaped = quote(token, safe="")
        if escaped:
            cleaned = cleaned.replace(escaped, "***")
    return cleaned[-4000:]


def extract_error_message(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    return str(exc).strip() or "unknown error"


def build_repo_remote_urls(
    *,
    provider: str,
    repo: str,
    token: str,
    gitlab_base_url: str | None,
) -> tuple[str, str]:
    if provider == "github":
        public_url = f"https://github.com/{repo}.git"
        username = "x-access-token"
    else:
        from app.routers.scm import _normalize_gitlab_base_url

        normalized_base = _normalize_gitlab_base_url(gitlab_base_url)
        public_url = f"{normalized_base.rstrip('/')}/{repo}.git"
        username = "oauth2"

    parsed = urlparse(public_url)
    token_escaped = quote(token, safe="")
    auth_netloc = f"{username}:{token_escaped}@{parsed.netloc}"
    auth_url = f"{parsed.scheme}://{auth_netloc}{parsed.path}"
    if parsed.query:
        auth_url = f"{auth_url}?{parsed.query}"
    return public_url, auth_url
