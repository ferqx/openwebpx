from __future__ import annotations

import json
import os
import time
import uuid
from base64 import urlsafe_b64encode
from binascii import Error as BinasciiError
from hashlib import sha256
from hmac import compare_digest
from hmac import new as hmac_new
from threading import RLock
from typing import Any, Literal
from urllib.parse import quote, urlencode, urlparse

import httpx
from aegra_api.core.orm import _get_session_maker
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter()

SCM_OAUTH_STATE_TTL_SECONDS = 10 * 60
SCM_TOKENS: dict[str, dict[str, Any]] = {}
SCM_TOKEN_STORE_LOCK = RLock()

SCM_ROW_UPDATE_SQL = """
UPDATE scm_tokens
SET
  user_id = :user_id,
  provider = :provider,
  gitlab_base_url = :gitlab_base_url,
  github_auth_mode = :github_auth_mode,
  token_encrypted = :token_encrypted,
  updated_at = :updated_at
WHERE cache_key = :cache_key
"""

SCM_ROW_INSERT_SQL = """
INSERT INTO scm_tokens
(
  cache_key,
  user_id,
  provider,
  gitlab_base_url,
  github_auth_mode,
  token_encrypted,
  updated_at
)
VALUES
(
  :cache_key,
  :user_id,
  :provider,
  :gitlab_base_url,
  :github_auth_mode,
  :token_encrypted,
  :updated_at
)
"""

SCM_ROW_DELETE_SQL = "DELETE FROM scm_tokens WHERE cache_key = :cache_key"
SCM_ROW_SELECT_SQL = """
SELECT token_encrypted
FROM scm_tokens
WHERE cache_key = :cache_key
LIMIT 1
"""

SCM_ROW_LIST_SQL = """
SELECT
  cache_key,
  provider,
  gitlab_base_url,
  github_auth_mode,
  token_encrypted,
  updated_at
FROM scm_tokens
WHERE user_id = :user_id
ORDER BY updated_at DESC
"""

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

ScmGithubAuthMode = Literal["github_app"]


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


def _is_token_payload_expired(payload: dict[str, Any]) -> bool:
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


def _cleanup_expired_scm_oauth_states() -> None:
    return


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


def _build_scm_token_cipher() -> Fernet:
    jwt_secret = (
        os.getenv("AUTH_JWT_SECRET", "").strip()
        or "openwebpx-dev-secret-change-me-please-use-env-in-production"
    )
    derived = sha256(f"openwebpx-scm-token::{jwt_secret}".encode()).digest()
    return Fernet(urlsafe_b64encode(derived))


SCM_TOKEN_CIPHER = _build_scm_token_cipher()


def _build_scm_state_signing_key() -> bytes:
    jwt_secret = (
        os.getenv("AUTH_JWT_SECRET", "").strip()
        or "openwebpx-dev-secret-change-me-please-use-env-in-production"
    )
    return sha256(f"openwebpx-scm-state::{jwt_secret}".encode()).digest()


SCM_STATE_SIGNING_KEY = _build_scm_state_signing_key()


def _b64url_encode(data: bytes) -> str:
    return urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    from base64 import urlsafe_b64decode

    return urlsafe_b64decode(f"{data}{padding}".encode())


def _encode_scm_oauth_state_token(payload: dict[str, Any]) -> str:
    raw_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    payload_part = _b64url_encode(raw_payload)
    signature = hmac_new(
        SCM_STATE_SIGNING_KEY,
        payload_part.encode("utf-8"),
        sha256,
    ).digest()
    signature_part = _b64url_encode(signature)
    return f"{payload_part}.{signature_part}"


def _decode_scm_oauth_state_token(state: str) -> dict[str, Any] | None:
    payload_part, sep, signature_part = state.partition(".")
    if not sep or not payload_part or not signature_part:
        return None
    expected_signature = hmac_new(
        SCM_STATE_SIGNING_KEY,
        payload_part.encode("utf-8"),
        sha256,
    ).digest()
    try:
        signature = _b64url_decode(signature_part)
    except (ValueError, BinasciiError):
        return None
    if not compare_digest(signature, expected_signature):
        return None
    try:
        raw_payload = _b64url_decode(payload_part)
        parsed = json.loads(raw_payload.decode("utf-8"))
    except (ValueError, BinasciiError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _encrypt_scm_token_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return SCM_TOKEN_CIPHER.encrypt(raw).decode("utf-8")


def _decrypt_scm_token_payload(token_encrypted: str) -> dict[str, Any] | None:
    try:
        raw = SCM_TOKEN_CIPHER.decrypt(token_encrypted.encode("utf-8"))
    except InvalidToken:
        return None
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _parse_scm_cache_key(cache_key: str) -> tuple[str, str]:
    head, sep, tail = cache_key.partition(":")
    if not sep:
        raise HTTPException(400, "无效的 SCM 缓存键")
    return head, tail


async def _set_scm_token_payload(
    cache_key: str,
    payload: dict[str, Any],
) -> None:
    user_id, provider_scope = _parse_scm_cache_key(cache_key)
    provider = "github" if provider_scope.startswith("github:") else "gitlab"
    github_auth_mode: str | None = None
    gitlab_base_url: str | None = None

    if provider == "github":
        github_auth_mode = (
            payload.get("github_auth_mode")
            if isinstance(payload.get("github_auth_mode"), str)
            else (
                provider_scope.split(":", 1)[1]
                if ":" in provider_scope
                else "github_app"
            )
        )
        github_auth_mode = _normalize_github_auth_mode(github_auth_mode)
    else:
        gitlab_base_url = (
            payload.get("gitlab_base_url")
            if isinstance(payload.get("gitlab_base_url"), str)
            else provider_scope.split(":", 1)[1]
            if ":" in provider_scope
            else None
        )
        gitlab_base_url = _normalize_gitlab_base_url(gitlab_base_url)

    encrypted = _encrypt_scm_token_payload(payload)
    session_maker = _get_session_maker()
    async with session_maker() as session:
        try:
            updated_at = time.time()
            result = await session.execute(
                text(SCM_ROW_UPDATE_SQL),
                {
                    "cache_key": cache_key,
                    "user_id": user_id,
                    "provider": provider,
                    "gitlab_base_url": gitlab_base_url,
                    "github_auth_mode": github_auth_mode,
                    "token_encrypted": encrypted,
                    "updated_at": updated_at,
                },
            )
            if result.rowcount == 0:
                await session.execute(
                    text(SCM_ROW_INSERT_SQL),
                    {
                        "cache_key": cache_key,
                        "user_id": user_id,
                        "provider": provider,
                        "gitlab_base_url": gitlab_base_url,
                        "github_auth_mode": github_auth_mode,
                        "token_encrypted": encrypted,
                        "updated_at": updated_at,
                    },
                )
            await session.commit()
        except SQLAlchemyError as exc:
            await session.rollback()
            raise HTTPException(500, f"保存 SCM token 失败: {exc}") from exc

    with SCM_TOKEN_STORE_LOCK:
        SCM_TOKENS[cache_key] = payload


async def _delete_scm_token_payload(cache_key: str) -> None:
    with SCM_TOKEN_STORE_LOCK:
        SCM_TOKENS.pop(cache_key, None)

    session_maker = _get_session_maker()
    async with session_maker() as session:
        try:
            await session.execute(
                text(SCM_ROW_DELETE_SQL),
                {"cache_key": cache_key},
            )
            await session.commit()
        except SQLAlchemyError as exc:
            await session.rollback()
            raise HTTPException(500, f"删除 SCM token 失败: {exc}") from exc


async def _list_scm_token_rows_for_user(user_id: str) -> list[dict[str, Any]]:
    session_maker = _get_session_maker()
    async with session_maker() as session:
        try:
            result = await session.execute(
                text(SCM_ROW_LIST_SQL),
                {"user_id": user_id},
            )
        except SQLAlchemyError as exc:
            raise HTTPException(500, f"查询 SCM 授权列表失败: {exc}") from exc
    return [dict(row) for row in result.mappings().all()]


def _build_scm_connection_item(row: dict[str, Any]) -> dict[str, Any] | None:
    provider_raw = str(row.get("provider") or "").strip().lower()
    if provider_raw not in {"github", "gitlab"}:
        return None

    gitlab_base_url = (
        _normalize_gitlab_base_url(str(row.get("gitlab_base_url") or "").strip())
        if provider_raw == "gitlab"
        else None
    )
    github_auth_mode = (
        _coerce_github_auth_mode(str(row.get("github_auth_mode") or "github_app"))
        if provider_raw == "github"
        else None
    )

    token_encrypted = row.get("token_encrypted")
    token_payload: dict[str, Any] | None = None
    if isinstance(token_encrypted, str) and token_encrypted.strip():
        token_payload = _decrypt_scm_token_payload(token_encrypted.strip())

    expires_at = (
        _coerce_float(token_payload.get("expires_at")) if token_payload else None
    )
    return {
        "cache_key": str(row.get("cache_key") or "").strip(),
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
        "updated_at": _coerce_float(row.get("updated_at")),
        "expires_at": expires_at,
        "expired": bool(expires_at is not None and expires_at <= time.time() + 30),
        "has_refresh_token": bool(
            token_payload
            and isinstance(token_payload.get("refresh_token"), str)
            and token_payload.get("refresh_token", "").strip()
        ),
    }


async def _resolve_scm_token_payload(
    *,
    user_id: str,
    provider: str,
    gitlab_base_url: str | None,
    github_auth_mode: str | None = None,
) -> dict[str, Any]:
    cache_key = _scm_token_cache_key(
        user_id=user_id,
        provider=provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )

    token_payload = SCM_TOKENS.get(cache_key)
    if isinstance(token_payload, dict):
        return token_payload

    session_maker = _get_session_maker()
    async with session_maker() as session:
        try:
            result = await session.execute(
                text(SCM_ROW_SELECT_SQL),
                {"cache_key": cache_key},
            )
        except SQLAlchemyError as exc:
            raise HTTPException(401, "请先完成 OAuth 授权") from exc
        row = result.mappings().first()

    if not row:
        raise HTTPException(401, "请先完成 OAuth 授权")

    token_encrypted = row.get("token_encrypted")
    if not isinstance(token_encrypted, str) or not token_encrypted.strip():
        await _delete_scm_token_payload(cache_key)
        raise HTTPException(401, "授权令牌不存在，请重新授权")

    payload = _decrypt_scm_token_payload(token_encrypted.strip())
    if not isinstance(payload, dict):
        await _delete_scm_token_payload(cache_key)
        raise HTTPException(401, "授权令牌已损坏，请重新授权")

    with SCM_TOKEN_STORE_LOCK:
        SCM_TOKENS[cache_key] = payload
    return payload


async def _resolve_scm_access_token(
    *,
    user_id: str,
    provider: str,
    gitlab_base_url: str | None,
    github_auth_mode: str | None = None,
) -> str:
    cache_key = _scm_token_cache_key(
        user_id=user_id,
        provider=provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )
    token_payload = await _resolve_scm_token_payload(
        user_id=user_id,
        provider=provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )

    if _is_token_payload_expired(token_payload):
        try:
            token_payload = await _refresh_scm_token_payload_if_needed(
                user_id=user_id,
                provider=provider,
                gitlab_base_url=gitlab_base_url,
                github_auth_mode=github_auth_mode,
                token_payload=token_payload,
            )
        except HTTPException as exc:
            if exc.status_code == 401:
                await _delete_scm_token_payload(cache_key)
            raise

    token = token_payload.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise HTTPException(401, "授权令牌不存在，请重新授权")
    return token.strip()


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


def _build_scm_authorize_url(
    *,
    provider: str,
    state: str,
    redirect_uri: str,
    gitlab_base_url: str | None,
    is_enterprise: bool,
    github_auth_mode: str | None = None,
) -> str:
    if provider == "github":
        _normalize_github_auth_mode(github_auth_mode)
        client_id = _env_first(
            "GITHUB_APP_CLIENT_ID",
            "GITHUB_OAUTH_CLIENT_ID",
            "GITHUB_CLIENT_ID",
        )

        if not client_id:
            raise HTTPException(500, "缺少 GitHub App Client ID 环境变量")

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }

        return f"https://github.com/login/oauth/authorize?{urlencode(params)}"

    resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
    enterprise = _is_gitlab_enterprise(resolved_base_url, is_enterprise)
    if enterprise:
        client_id = _env_first(
            "GITLAB_ENTERPRISE_OAUTH_CLIENT_ID",
            "GITLAB_OAUTH_CLIENT_ID",
            "GITLAB_CLIENT_ID",
        )
    else:
        client_id = _env_first("GITLAB_OAUTH_CLIENT_ID", "GITLAB_CLIENT_ID")
    if not client_id:
        raise HTTPException(500, "缺少 GitLab OAuth Client ID 环境变量")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    scope = _resolve_gitlab_oauth_scope(enterprise=enterprise)
    if scope:
        params["scope"] = scope
    return f"{resolved_base_url}/oauth/authorize?{urlencode(params)}"


def _resolve_request_user_identity(request: Request | None) -> str:
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
            return header_value.strip()

    return "local-dev"


def _resolve_github_oauth_client_credentials() -> tuple[str, str]:
    client_id = _env_first(
        "GITHUB_APP_CLIENT_ID",
        "GITHUB_OAUTH_CLIENT_ID",
        "GITHUB_CLIENT_ID",
    )
    client_secret = _env_first(
        "GITHUB_APP_CLIENT_SECRET",
        "GITHUB_OAUTH_CLIENT_SECRET",
        "GITHUB_CLIENT_SECRET",
    )
    if not client_id or not client_secret:
        raise HTTPException(500, "缺少 GitHub App Client ID/Secret 环境变量")
    return client_id, client_secret


def _resolve_gitlab_oauth_client_credentials(*, is_enterprise: bool) -> tuple[str, str]:
    if is_enterprise:
        client_id = _env_first(
            "GITLAB_ENTERPRISE_OAUTH_CLIENT_ID",
            "GITLAB_OAUTH_CLIENT_ID",
            "GITLAB_CLIENT_ID",
        )
        client_secret = _env_first(
            "GITLAB_ENTERPRISE_OAUTH_CLIENT_SECRET",
            "GITLAB_OAUTH_CLIENT_SECRET",
            "GITLAB_CLIENT_SECRET",
        )
    else:
        client_id = _env_first("GITLAB_OAUTH_CLIENT_ID", "GITLAB_CLIENT_ID")
        client_secret = _env_first("GITLAB_OAUTH_CLIENT_SECRET", "GITLAB_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise HTTPException(500, "缺少 GitLab OAuth Client ID/Secret 环境变量")
    return client_id, client_secret


async def _exchange_github_oauth_token(
    *,
    code: str,
    redirect_uri: str,
    github_auth_mode: str | None = None,
) -> dict[str, Any]:
    normalized_mode = _normalize_github_auth_mode(github_auth_mode)
    client_id, client_secret = _resolve_github_oauth_client_credentials()

    async with httpx.AsyncClient(timeout=20) as http_client:
        response = await http_client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )

    if response.status_code >= 400:
        raise HTTPException(
            502,
            f"GitHub token 交换失败: {response.text[:200]}",
        )

    payload = response.json() if response.content else {}
    if isinstance(payload, dict) and payload.get("error"):
        message = payload.get("error_description") or payload.get("error")
        raise HTTPException(400, f"GitHub 授权失败: {message}")

    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise HTTPException(502, "GitHub 未返回 access_token")

    source_kind = "github_app"
    result: dict[str, Any] = {
        "access_token": token.strip(),
        "github_token_source": source_kind,
        "github_auth_mode": normalized_mode,
    }
    if isinstance(payload, dict):
        result.update(
            {
                "refresh_token": payload.get("refresh_token"),
                "expires_in": payload.get("expires_in"),
                "refresh_token_expires_in": payload.get("refresh_token_expires_in"),
                "scope": payload.get("scope"),
                "token_type": payload.get("token_type"),
            }
        )
    expires_at = _compute_expires_at(result.get("expires_in"))
    if expires_at is not None:
        result["expires_at"] = expires_at
    return result


async def _refresh_github_oauth_token(
    *,
    refresh_token: str,
    github_auth_mode: str | None = None,
) -> dict[str, Any]:
    normalized_mode = _normalize_github_auth_mode(github_auth_mode)
    client_id, client_secret = _resolve_github_oauth_client_credentials()

    async with httpx.AsyncClient(timeout=20) as http_client:
        response = await http_client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Accept": "application/json"},
        )

    if response.status_code >= 400:
        raise HTTPException(
            401,
            f"GitHub token 刷新失败: {response.text[:200]}",
        )

    payload = response.json() if response.content else {}
    if isinstance(payload, dict) and payload.get("error"):
        message = payload.get("error_description") or payload.get("error")
        raise HTTPException(401, f"GitHub token 刷新失败: {message}")

    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise HTTPException(401, "GitHub token 刷新未返回 access_token")

    source_kind = normalized_mode
    result: dict[str, Any] = {
        "access_token": token.strip(),
        "github_token_source": source_kind,
        "github_auth_mode": normalized_mode,
    }
    if isinstance(payload, dict):
        result.update(
            {
                "refresh_token": payload.get("refresh_token") or refresh_token,
                "expires_in": payload.get("expires_in"),
                "refresh_token_expires_in": payload.get("refresh_token_expires_in"),
                "scope": payload.get("scope"),
                "token_type": payload.get("token_type"),
            }
        )
    expires_at = _compute_expires_at(result.get("expires_in"))
    if expires_at is not None:
        result["expires_at"] = expires_at
    return result


async def _fetch_github_installation_repositories(
    *,
    http_client: httpx.AsyncClient,
    access_token: str,
) -> list[dict[str, Any]]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    installations_response = await http_client.get(
        "https://api.github.com/user/installations",
        params={"per_page": 100},
        headers=headers,
    )
    if installations_response.status_code in {403, 404}:
        return []
    if installations_response.status_code >= 400:
        raise HTTPException(
            installations_response.status_code,
            f"GitHub 安装列表查询失败: {installations_response.text[:200]}",
        )

    installations_payload = (
        installations_response.json() if installations_response.content else {}
    )
    installation_items = (
        installations_payload.get("installations", [])
        if isinstance(installations_payload, dict)
        else []
    )
    if not isinstance(installation_items, list) or not installation_items:
        return []

    repositories: dict[str, dict[str, Any]] = {}
    for installation in installation_items:
        if not isinstance(installation, dict):
            continue
        installation_id = installation.get("id")
        if not isinstance(installation_id, int):
            continue
        repos_response = await http_client.get(
            f"https://api.github.com/user/installations/{installation_id}/repositories",
            params={"per_page": 100},
            headers=headers,
        )
        if repos_response.status_code in {403, 404}:
            continue
        if repos_response.status_code >= 400:
            continue
        repos_payload = repos_response.json() if repos_response.content else {}
        repo_items = (
            repos_payload.get("repositories", [])
            if isinstance(repos_payload, dict)
            else []
        )
        if not isinstance(repo_items, list):
            continue
        for item in repo_items:
            if not isinstance(item, dict):
                continue
            full_name = item.get("full_name")
            if not isinstance(full_name, str) or not full_name.strip():
                continue
            repositories[full_name] = {
                "id": item.get("id"),
                "name": item.get("name"),
                "full_name": full_name,
                "default_branch": item.get("default_branch"),
            }
    return list(repositories.values())


async def _fetch_github_user_repositories(
    *,
    http_client: httpx.AsyncClient,
    access_token: str,
) -> list[dict[str, Any]]:
    response = await http_client.get(
        "https://api.github.com/user/repos",
        params={"sort": "updated", "per_page": 100},
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if response.status_code >= 400:
        raise HTTPException(
            response.status_code,
            f"GitHub 仓库查询失败: {response.text[:200]}",
        )
    payload = response.json() if response.content else []
    if not isinstance(payload, list):
        payload = []
    return [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "full_name": item.get("full_name"),
            "default_branch": item.get("default_branch"),
        }
        for item in payload
        if isinstance(item, dict)
    ]


async def _exchange_gitlab_oauth_token(
    *,
    code: str,
    redirect_uri: str,
    gitlab_base_url: str,
    is_enterprise: bool,
) -> dict[str, Any]:
    client_id, client_secret = _resolve_gitlab_oauth_client_credentials(
        is_enterprise=is_enterprise
    )

    async with httpx.AsyncClient(timeout=20) as http_client:
        response = await http_client.post(
            f"{gitlab_base_url}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )

    if response.status_code >= 400:
        raise HTTPException(
            502,
            f"GitLab token 交换失败: {response.text[:200]}",
        )

    payload = response.json() if response.content else {}
    if isinstance(payload, dict) and payload.get("error"):
        message = payload.get("error_description") or payload.get("error")
        raise HTTPException(400, f"GitLab 授权失败: {message}")

    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise HTTPException(502, "GitLab 未返回 access_token")

    result: dict[str, Any] = {"access_token": token.strip()}
    if isinstance(payload, dict):
        result.update(
            {
                "refresh_token": payload.get("refresh_token"),
                "expires_in": payload.get("expires_in"),
                "scope": payload.get("scope"),
                "token_type": payload.get("token_type"),
            }
        )
    expires_at = _compute_expires_at(result.get("expires_in"))
    if expires_at is not None:
        result["expires_at"] = expires_at
    return result


async def _refresh_gitlab_oauth_token(
    *,
    refresh_token: str,
    gitlab_base_url: str,
    is_enterprise: bool,
) -> dict[str, Any]:
    client_id, client_secret = _resolve_gitlab_oauth_client_credentials(
        is_enterprise=is_enterprise
    )

    async with httpx.AsyncClient(timeout=20) as http_client:
        response = await http_client.post(
            f"{gitlab_base_url}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Accept": "application/json"},
        )

    if response.status_code >= 400:
        raise HTTPException(
            401,
            f"GitLab token 刷新失败: {response.text[:200]}",
        )

    payload = response.json() if response.content else {}
    if isinstance(payload, dict) and payload.get("error"):
        message = payload.get("error_description") or payload.get("error")
        raise HTTPException(401, f"GitLab token 刷新失败: {message}")

    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise HTTPException(401, "GitLab token 刷新未返回 access_token")

    result: dict[str, Any] = {"access_token": token.strip()}
    if isinstance(payload, dict):
        result.update(
            {
                "refresh_token": payload.get("refresh_token") or refresh_token,
                "expires_in": payload.get("expires_in"),
                "scope": payload.get("scope"),
                "token_type": payload.get("token_type"),
            }
        )
    expires_at = _compute_expires_at(result.get("expires_in"))
    if expires_at is not None:
        result["expires_at"] = expires_at
    return result


async def _refresh_scm_token_payload_if_needed(
    *,
    user_id: str,
    provider: str,
    gitlab_base_url: str | None,
    github_auth_mode: str | None,
    token_payload: dict[str, Any],
) -> dict[str, Any]:
    if not _is_token_payload_expired(token_payload):
        return token_payload

    refresh_token = token_payload.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise HTTPException(401, "SCM 授权已过期，请重新授权")

    refreshed_payload: dict[str, Any]
    if provider == "github":
        refreshed_payload = await _refresh_github_oauth_token(
            refresh_token=refresh_token.strip(),
            github_auth_mode=github_auth_mode,
        )
    else:
        resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
        enterprise = _is_gitlab_enterprise(resolved_base_url, False)
        refreshed_payload = await _refresh_gitlab_oauth_token(
            refresh_token=refresh_token.strip(),
            gitlab_base_url=resolved_base_url,
            is_enterprise=enterprise,
        )
        refreshed_payload["provider"] = "gitlab"
        refreshed_payload["gitlab_base_url"] = resolved_base_url

    next_payload = {**token_payload, **refreshed_payload, "updated_at": time.time()}
    if provider == "github":
        next_payload["provider"] = "github"
        if github_auth_mode:
            next_payload["github_auth_mode"] = github_auth_mode
    expires_at = _compute_expires_at(next_payload.get("expires_in"))
    if expires_at is not None:
        next_payload["expires_at"] = expires_at

    cache_key = _scm_token_cache_key(
        user_id=user_id,
        provider=provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )
    await _set_scm_token_payload(cache_key, next_payload)
    return next_payload


@router.get("/integrations/scm/oauth/authorize")
async def scm_oauth_authorize(
    provider: str = Query(..., description="github or gitlab"),
    redirect_uri: str = Query(..., description="Frontend callback URL"),
    origin: str | None = Query(None),
    gitlab_base_url: str | None = Query(None),
    is_enterprise: bool = Query(False),
    auth_mode: str | None = Query(None, description="github_app"),
    response_mode: str = Query("redirect", description="redirect or json"),
    request: Request = None,
) -> Any:
    normalized_provider = _normalize_scm_provider(provider)
    normalized_redirect_uri = _normalize_redirect_uri(redirect_uri)
    if not normalized_redirect_uri:
        raise HTTPException(400, "redirect_uri 不能为空")

    normalized_response_mode = response_mode.strip().lower()
    if normalized_response_mode not in {"redirect", "json"}:
        raise HTTPException(400, "response_mode 仅支持 redirect 或 json")

    _cleanup_expired_scm_oauth_states()
    resolved_base_url = (
        _normalize_gitlab_base_url(gitlab_base_url)
        if normalized_provider == "gitlab"
        else None
    )
    github_auth_mode = (
        _normalize_github_auth_mode(auth_mode)
        if normalized_provider == "github"
        else None
    )

    user_id = _resolve_request_user_identity(request)
    normalized_origin = _normalize_origin(origin) or _normalize_origin(
        normalized_redirect_uri
    )
    state_payload = {
        "provider": normalized_provider,
        "user_id": user_id,
        "created_at": time.time(),
        "gitlab_base_url": resolved_base_url,
        "is_enterprise": bool(is_enterprise),
        "origin": normalized_origin,
        "redirect_uri": normalized_redirect_uri,
        "github_auth_mode": github_auth_mode,
        "nonce": uuid.uuid4().hex,
    }
    state = _encode_scm_oauth_state_token(state_payload)

    authorize_url = _build_scm_authorize_url(
        provider=normalized_provider,
        state=state,
        redirect_uri=normalized_redirect_uri,
        gitlab_base_url=resolved_base_url,
        is_enterprise=is_enterprise,
        github_auth_mode=github_auth_mode,
    )

    if normalized_response_mode == "json":
        return {"ok": True, "authorize_url": authorize_url}
    return RedirectResponse(authorize_url, status_code=302)


@router.post("/integrations/scm/oauth/callback")
async def scm_oauth_callback(
    payload: dict[str, Any] | None = Body(default=None),
    request: Request = None,
) -> dict[str, Any]:
    payload_dict = payload if isinstance(payload, dict) else {}
    raw_params = payload_dict.get("params")
    params: dict[str, str] = {}
    if isinstance(raw_params, dict):
        params = {
            str(key): str(value)
            for key, value in raw_params.items()
            if value is not None
        }

    oauth_error = params.get("error")
    if oauth_error:
        detail = params.get("error_description") or oauth_error
        return {"ok": False, "error": detail}

    state = params.get("state")
    code = params.get("code")
    if not state or not code:
        return {"ok": False, "error": "OAuth 回调缺少 state 或 code"}

    user_id = _resolve_request_user_identity(request)
    _cleanup_expired_scm_oauth_states()
    state_payload = _decode_scm_oauth_state_token(state)
    if not state_payload:
        return {"ok": False, "error": "OAuth state 无效或已过期"}
    created_at = state_payload.get("created_at")
    if not isinstance(created_at, (int, float)):
        return {"ok": False, "error": "OAuth state 无效或已过期"}
    if time.time() - float(created_at) > SCM_OAUTH_STATE_TTL_SECONDS:
        return {"ok": False, "error": "OAuth state 无效或已过期"}
    if state_payload.get("user_id") != user_id:
        return {"ok": False, "error": "OAuth state 与当前用户不匹配"}

    provider = str(state_payload.get("provider", "")).strip().lower()
    redirect_uri_raw = (
        params.get("redirect_uri")
        or payload_dict.get("redirect_uri")
        or state_payload.get("redirect_uri")
    )
    redirect_uri = _normalize_redirect_uri(
        redirect_uri_raw if isinstance(redirect_uri_raw, str) else None
    )
    if not redirect_uri:
        return {"ok": False, "error": "缺少 redirect_uri"}

    expected_redirect_uri = _normalize_redirect_uri(
        state_payload.get("redirect_uri")
        if isinstance(state_payload.get("redirect_uri"), str)
        else None
    )
    if expected_redirect_uri and redirect_uri != expected_redirect_uri:
        return {"ok": False, "error": "OAuth redirect_uri 与授权请求不匹配"}

    expected_origin = _normalize_origin(
        state_payload.get("origin")
        if isinstance(state_payload.get("origin"), str)
        else None
    )
    actual_origin = _normalize_origin(redirect_uri)
    if expected_origin and actual_origin and expected_origin != actual_origin:
        return {"ok": False, "error": "OAuth origin 与授权请求不匹配"}

    try:
        if provider == "github":
            github_auth_mode = _normalize_github_auth_mode(
                state_payload.get("github_auth_mode")
                if isinstance(state_payload.get("github_auth_mode"), str)
                else None
            )
            github_token_payload = await _exchange_github_oauth_token(
                code=code,
                redirect_uri=redirect_uri,
                github_auth_mode=github_auth_mode,
            )
            access_token = github_token_payload["access_token"]
            cache_key = _scm_token_cache_key(
                user_id=user_id,
                provider="github",
                github_auth_mode=github_auth_mode,
            )
            await _set_scm_token_payload(
                cache_key,
                {
                    "provider": "github",
                    "access_token": access_token,
                    "updated_at": time.time(),
                    "github_token_source": github_token_payload.get(
                        "github_token_source",
                        "github_app",
                    ),
                    "github_auth_mode": github_auth_mode,
                    "refresh_token": github_token_payload.get("refresh_token"),
                    "expires_in": github_token_payload.get("expires_in"),
                    "expires_at": github_token_payload.get("expires_at"),
                    "refresh_token_expires_in": github_token_payload.get(
                        "refresh_token_expires_in"
                    ),
                    "scope": github_token_payload.get("scope"),
                    "token_type": github_token_payload.get("token_type"),
                },
            )
        elif provider == "gitlab":
            gitlab_base_url = state_payload.get("gitlab_base_url")
            resolved_base_url = _normalize_gitlab_base_url(
                gitlab_base_url if isinstance(gitlab_base_url, str) else None
            )
            enterprise = _is_gitlab_enterprise(
                resolved_base_url, bool(state_payload.get("is_enterprise"))
            )
            gitlab_token_payload = await _exchange_gitlab_oauth_token(
                code=code,
                redirect_uri=redirect_uri,
                gitlab_base_url=resolved_base_url,
                is_enterprise=enterprise,
            )
            access_token = gitlab_token_payload["access_token"]
            cache_key = _scm_token_cache_key(
                user_id=user_id,
                provider="gitlab",
                gitlab_base_url=resolved_base_url,
            )
            await _set_scm_token_payload(
                cache_key,
                {
                    "provider": "gitlab",
                    "gitlab_base_url": resolved_base_url,
                    "access_token": access_token,
                    "refresh_token": gitlab_token_payload.get("refresh_token"),
                    "expires_in": gitlab_token_payload.get("expires_in"),
                    "expires_at": gitlab_token_payload.get("expires_at"),
                    "scope": gitlab_token_payload.get("scope"),
                    "token_type": gitlab_token_payload.get("token_type"),
                    "updated_at": time.time(),
                },
            )
        else:
            return {"ok": False, "error": "不支持的 provider"}
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail)}
    except Exception as exc:  # pragma: no cover - defensive path
        return {"ok": False, "error": f"OAuth 回调处理失败: {exc}"}

    return {"ok": True}


@router.get("/integrations/scm/connections")
async def list_scm_connections(request: Request = None) -> dict[str, Any]:
    user_id = _resolve_request_user_identity(request)
    rows = await _list_scm_token_rows_for_user(user_id)

    connections: list[dict[str, Any]] = []
    for row in rows:
        connection = _build_scm_connection_item(row)
        if connection is None:
            continue
        cache_key = connection.get("cache_key")
        if not isinstance(cache_key, str) or not cache_key:
            continue
        if isinstance(row.get("token_encrypted"), str) and not connection.get(
            "expired"
        ):
            connections.append(connection)
            continue

        # token missing/corrupted/expired: keep entry but mark as expired.
        connections.append(connection)

    return {
        "connections": [
            {
                "provider": item.get("provider"),
                "github_auth_mode": item.get("github_auth_mode"),
                "gitlab_base_url": item.get("gitlab_base_url"),
                "is_enterprise": item.get("is_enterprise"),
                "connection_key": item.get("connection_key"),
                "updated_at": item.get("updated_at"),
                "expires_at": item.get("expires_at"),
                "expired": item.get("expired"),
                "has_refresh_token": item.get("has_refresh_token"),
            }
            for item in connections
        ]
    }


@router.delete("/integrations/scm/connections")
async def revoke_scm_connection(
    provider: str = Query(..., description="github or gitlab"),
    gitlab_base_url: str | None = Query(None),
    auth_mode: str | None = Query(None, description="github_app"),
    request: Request = None,
) -> dict[str, Any]:
    normalized_provider = _normalize_scm_provider(provider)
    github_auth_mode = (
        _normalize_github_auth_mode(auth_mode)
        if normalized_provider == "github"
        else None
    )
    user_id = _resolve_request_user_identity(request)
    cache_key = _scm_token_cache_key(
        user_id=user_id,
        provider=normalized_provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )
    await _delete_scm_token_payload(cache_key)
    return {
        "ok": True,
        "connection_key": _resolve_scm_connection_key(
            provider=normalized_provider,
            gitlab_base_url=gitlab_base_url,
        ),
    }


@router.get("/integrations/scm/connections/validate")
async def validate_scm_connection(
    provider: str = Query(..., description="github or gitlab"),
    gitlab_base_url: str | None = Query(None),
    auth_mode: str | None = Query(None, description="github_app"),
    request: Request = None,
) -> dict[str, Any]:
    normalized_provider = _normalize_scm_provider(provider)
    github_auth_mode = (
        _normalize_github_auth_mode(auth_mode)
        if normalized_provider == "github"
        else None
    )
    user_id = _resolve_request_user_identity(request)
    cache_key = _scm_token_cache_key(
        user_id=user_id,
        provider=normalized_provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )

    try:
        token = await _resolve_scm_access_token(
            user_id=user_id,
            provider=normalized_provider,
            gitlab_base_url=gitlab_base_url,
            github_auth_mode=github_auth_mode,
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            await _delete_scm_token_payload(cache_key)
            return {
                "ok": True,
                "valid": False,
                "revoked": True,
                "error": str(exc.detail),
            }
        raise

    try:
        async with httpx.AsyncClient(timeout=20) as http_client:
            if normalized_provider == "github":
                response = await http_client.get(
                    "https://api.github.com/user",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                if response.status_code >= 400:
                    raise HTTPException(
                        response.status_code,
                        f"GitHub 授权验证失败: {response.text[:200]}",
                    )
            else:
                resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
                response = await http_client.get(
                    f"{resolved_base_url}/api/v4/user",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if response.status_code >= 400:
                    raise HTTPException(
                        response.status_code,
                        f"GitLab 授权验证失败: {response.text[:200]}",
                    )
    except HTTPException as exc:
        revoked = _should_revoke_scm_token(normalized_provider, exc)
        if revoked:
            await _delete_scm_token_payload(cache_key)
        return {
            "ok": True,
            "valid": False,
            "revoked": revoked,
            "error": str(exc.detail),
        }

    return {"ok": True, "valid": True, "revoked": False}


@router.get("/integrations/scm/repositories")
async def list_scm_repositories(
    provider: str = Query(..., description="github or gitlab"),
    gitlab_base_url: str | None = Query(None),
    auth_mode: str | None = Query(None, description="github_app"),
    request: Request = None,
) -> dict[str, Any]:
    normalized_provider = _normalize_scm_provider(provider)
    github_auth_mode = (
        _normalize_github_auth_mode(auth_mode)
        if normalized_provider == "github"
        else None
    )
    user_id = _resolve_request_user_identity(request)
    cache_key = _scm_token_cache_key(
        user_id=user_id,
        provider=normalized_provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )
    token = await _resolve_scm_access_token(
        user_id=user_id,
        provider=normalized_provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )
    token_payload = await _resolve_scm_token_payload(
        user_id=user_id,
        provider=normalized_provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )

    try:
        async with httpx.AsyncClient(timeout=20) as http_client:
            if normalized_provider == "github":
                repositories = []
                if token_payload.get("github_token_source") == "github_app":
                    repositories = await _fetch_github_installation_repositories(
                        http_client=http_client,
                        access_token=token,
                    )
                if not repositories:
                    repositories = await _fetch_github_user_repositories(
                        http_client=http_client,
                        access_token=token,
                    )
                return {"repositories": repositories}

            resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
            response = await http_client.get(
                f"{resolved_base_url}/api/v4/projects",
                params={
                    "membership": True,
                    "simple": True,
                    "per_page": 100,
                    "order_by": "last_activity_at",
                    "sort": "desc",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code >= 400:
                raise HTTPException(
                    response.status_code,
                    f"GitLab 仓库查询失败: {response.text[:200]}",
                )
            payload = response.json() if response.content else []
            if not isinstance(payload, list):
                payload = []
            repositories = [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "path_with_namespace": item.get("path_with_namespace"),
                    "default_branch": item.get("default_branch"),
                }
                for item in payload
                if isinstance(item, dict)
            ]
            return {"repositories": repositories}
    except HTTPException as exc:
        if _should_revoke_scm_token(normalized_provider, exc):
            await _delete_scm_token_payload(cache_key)
            raise HTTPException(401, "SCM 授权已失效或已被撤销，请重新授权") from exc
        raise


@router.get("/integrations/scm/branches")
async def list_scm_branches(
    provider: str = Query(..., description="github or gitlab"),
    repository: str = Query(..., description="owner/repo"),
    gitlab_base_url: str | None = Query(None),
    auth_mode: str | None = Query(None, description="github_app"),
    request: Request = None,
) -> dict[str, Any]:
    normalized_provider = _normalize_scm_provider(provider)
    github_auth_mode = (
        _normalize_github_auth_mode(auth_mode)
        if normalized_provider == "github"
        else None
    )
    user_id = _resolve_request_user_identity(request)
    cache_key = _scm_token_cache_key(
        user_id=user_id,
        provider=normalized_provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )
    token = await _resolve_scm_access_token(
        user_id=user_id,
        provider=normalized_provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )
    repo_full_name = repository.strip()
    if not repo_full_name:
        raise HTTPException(400, "repository 不能为空")

    try:
        async with httpx.AsyncClient(timeout=20) as http_client:
            if normalized_provider == "github":
                response = await http_client.get(
                    f"https://api.github.com/repos/{repo_full_name}/branches",
                    params={"per_page": 100},
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                if response.status_code >= 400:
                    raise HTTPException(
                        response.status_code,
                        f"GitHub 分支查询失败: {response.text[:200]}",
                    )
                payload = response.json() if response.content else []
                if not isinstance(payload, list):
                    payload = []
                branches = [
                    {"name": item.get("name")}
                    for item in payload
                    if isinstance(item, dict) and isinstance(item.get("name"), str)
                ]
                return {"branches": branches}

            resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
            encoded_repo = quote(repo_full_name, safe="")
            response = await http_client.get(
                f"{resolved_base_url}/api/v4/projects/{encoded_repo}/repository/branches",
                params={"per_page": 100},
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code >= 400:
                raise HTTPException(
                    response.status_code,
                    f"GitLab 分支查询失败: {response.text[:200]}",
                )
            payload = response.json() if response.content else []
            if not isinstance(payload, list):
                payload = []
            branches = [
                {"name": item.get("name")}
                for item in payload
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ]
            return {"branches": branches}
    except HTTPException as exc:
        if _should_revoke_scm_token(normalized_provider, exc):
            await _delete_scm_token_payload(cache_key)
            raise HTTPException(401, "SCM 授权已失效或已被撤销，请重新授权") from exc
        raise
