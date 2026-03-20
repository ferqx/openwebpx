from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from fastapi import HTTPException

if TYPE_CHECKING:
    from .types import ScmConnectionInfo, ScmGithubAuthMode, TokenPayload

SCM_TOKEN_REVOKED_HINTS = (
    "bad credentials",
    "invalid token",
    "token expired",
    "token is expired",
    "token has expired",
    "token revoked",
    "revoked",
    "requires authentication",
    "authorization failed",
    "invalid_grant",
    "unauthorized",
)


def _env_first(*keys: str) -> str | None:
    for key in keys:
        value = os.getenv(key)
        if value and value.strip():
            return value.strip()
    return None


def _normalize_scm_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized not in {"github", "gitlab"}:
        raise HTTPException(400, "provider 仅支持 github 或 gitlab")
    return normalized


def _normalize_github_auth_mode(auth_mode: str | None) -> ScmGithubAuthMode:
    normalized = (auth_mode or "github_app").strip().lower()
    if normalized != "github_app":
        raise HTTPException(400, "GitHub auth_mode 仅支持 github_app")
    return normalized  # type: ignore[return-value]


def _coerce_github_auth_mode(auth_mode: str | None) -> ScmGithubAuthMode:
    """Tolerate legacy persisted values and fall back to github_app."""
    normalized = (auth_mode or "").strip().lower()
    if normalized == "github_app":
        return "github_app"
    return "github_app"


def _normalize_gitlab_base_url(value: str | None) -> str:
    if not value or not value.strip():
        return "https://gitlab.com"
    normalized = value.strip().rstrip("/")
    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"
    return normalized


def _is_gitlab_enterprise(base_url: str, is_enterprise: bool) -> bool:
    return is_enterprise or base_url.rstrip("/").lower() != "https://gitlab.com"


def _normalize_origin(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _normalize_redirect_uri(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    path = parsed.path or "/"
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def _compute_expires_at(expires_in: Any) -> float | None:
    expires = _coerce_float(expires_in)
    if expires is None or expires <= 0:
        return None
    return time.time() + expires


def _is_token_payload_expired(payload: TokenPayload) -> bool:
    expires_at = _coerce_float(payload.get("expires_at"))
    if expires_at is None:
        return False
    return expires_at <= time.time() + 30


def _resolve_scm_connection_key(*, provider: str, gitlab_base_url: str | None) -> str:
    if provider == "github":
        return "github"
    resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
    if _is_gitlab_enterprise(resolved_base_url, False):
        return f"gitlab_enterprise:{resolved_base_url.lower()}"
    return "gitlab"


def _scm_token_cache_key(
    *,
    user_id: str,
    provider: str,
    gitlab_base_url: str | None = None,
    github_auth_mode: str | None = None,
) -> str:
    if provider == "github":
        normalized_mode = _normalize_github_auth_mode(github_auth_mode)
        return f"{user_id}:github:{normalized_mode}"
    normalized_base_url = _normalize_gitlab_base_url(gitlab_base_url).lower()
    return f"{user_id}:gitlab:{normalized_base_url}"


def _resolve_request_user_identity(request: Any) -> str:
    if request is None:
        return "local-dev"

    scope_user = request.scope.get("user")
    if scope_user is not None:
        identity = getattr(scope_user, "identity", None) or getattr(
            scope_user, "id", None
        )
        if isinstance(identity, str) and identity.strip():
            return identity.strip()

    for header_name in ("x-user-id", "x-auth-user", "x-user"):
        header_value = request.headers.get(header_name)
        if header_value and header_value.strip():
            return cast("str", header_value.strip())

    return "local-dev"


def _should_revoke_scm_token(provider: str, exc: HTTPException) -> bool:
    detail = str(exc.detail).strip().lower()
    if exc.status_code == 401:
        return True
    if exc.status_code != 403:
        return False
    if "rate limit" in detail:
        return False
    if provider == "github" and "resource not accessible by integration" in detail:
        return False
    return any(hint in detail for hint in SCM_TOKEN_REVOKED_HINTS)


def _normalize_scope_value(scope: str | None) -> str | None:
    if not scope or not scope.strip():
        return None
    normalized = " ".join(
        part.strip() for part in scope.replace(",", " ").split() if part.strip()
    )
    return normalized or None


def _resolve_gitlab_oauth_scope(*, enterprise: bool) -> str | None:
    configured_scope = (
        _env_first(
            "GITLAB_ENTERPRISE_OAUTH_SCOPE",
            "GITLAB_OAUTH_SCOPE",
            "GITLAB_SCOPE",
        )
        if enterprise
        else _env_first("GITLAB_OAUTH_SCOPE", "GITLAB_SCOPE")
    )
    return _normalize_scope_value(configured_scope)


def _raise_upstream_connect_error(service: str, exc: Exception) -> None:
    detail = str(exc).strip()
    suffix = f": {detail}" if detail else ""
    raise HTTPException(
        502,
        f"{service} 网络连接失败，请检查服务容器的外网访问和 TLS 配置{suffix}",
    ) from exc


def _build_scm_connection_item(row: Any) -> ScmConnectionInfo | None:
    """从 ORM 模型构建连接信息项.

    Supports both ORM model instances and dicts (for testing).
    """
    from app.services.scm.crypto import _decrypt_scm_token_payload

    # Get attribute values supporting both ORM and dict
    def get_attr(obj: Any, name: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    provider_raw = str(get_attr(row, "provider", "")).strip().lower()
    if provider_raw not in {"github", "gitlab"}:
        return None

    gitlab_base_url = (
        _normalize_gitlab_base_url(
            str(get_attr(row, "gitlab_base_url", "") or "").strip()
        )
        if provider_raw == "gitlab"
        else None
    )
    github_auth_mode = (
        _coerce_github_auth_mode(
            str(get_attr(row, "github_auth_mode", "github_app") or "github_app")
        )
        if provider_raw == "github"
        else None
    )

    token_encrypted = get_attr(row, "token_encrypted")
    token_payload: dict[str, Any] | None = None
    if isinstance(token_encrypted, str) and token_encrypted.strip():
        token_payload = _decrypt_scm_token_payload(token_encrypted.strip())

    expires_at = (
        _coerce_float(token_payload.get("expires_at")) if token_payload else None
    )
    return {
        "cache_key": str(get_attr(row, "cache_key", "")).strip(),
        "provider": provider_raw,
        "github_auth_mode": github_auth_mode,
        "gitlab_base_url": gitlab_base_url,
        "is_enterprise": bool(
            gitlab_base_url and _is_gitlab_enterprise(gitlab_base_url, False)
        ),
        "connection_key": _resolve_scm_connection_key(
            provider=provider_raw,
            gitlab_base_url=gitlab_base_url,
        ),
        "updated_at": _coerce_float(get_attr(row, "updated_at")),
        "expires_at": expires_at,
        "expired": bool(expires_at is not None and expires_at <= time.time() + 30),
        "has_refresh_token": bool(
            token_payload
            and isinstance(token_payload.get("refresh_token"), str)
            and token_payload.get("refresh_token", "").strip()
        ),
    }
