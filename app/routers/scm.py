from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any, cast

import httpx  # noqa: F401  # used by tests for monkeypatching
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.services.scm import (
    _build_scm_connection_item,
    _coerce_float,
    _decode_scm_oauth_state_token,
    _decrypt_scm_token_payload,  # noqa: F401  # used by tests for monkeypatching
    _encode_scm_oauth_state_token,
    _encrypt_scm_token_payload,  # noqa: F401  # used by tests for monkeypatching
    _is_gitlab_enterprise,
    _normalize_github_auth_mode,
    _normalize_gitlab_base_url,
    _normalize_origin,
    _normalize_redirect_uri,
    _normalize_scm_provider,
    _resolve_request_user_identity,
    _resolve_scm_connection_key,
    _scm_token_cache_key,
    _should_revoke_scm_token,
    scm_oauth_service,
    scm_repository_service,
    scm_token_store,
)

if TYPE_CHECKING:
    from app.models.scm_token import ScmToken
    from app.services.scm.types import ScmConnectionInfo, TokenPayload

# Re-export for test mocking
_delete_scm_token_payload = scm_token_store.delete_token_payload
SCM_TOKENS = scm_token_store.SCM_TOKENS


router = APIRouter()

SCM_OAUTH_STATE_TTL_SECONDS = 10 * 60


def _cleanup_expired_scm_oauth_states() -> None:
    return


async def _dedupe_scm_connections(
    connections: list[ScmConnectionInfo],
) -> list[ScmConnectionInfo]:
    """Deduplicate by connection_key and keep the newest record.

    Stale entries are deleted from the database.
    """
    deduped: dict[str, ScmConnectionInfo] = {}
    stale_cache_keys: list[str] = []

    for connection in connections:
        connection_key = connection.get("connection_key")
        cache_key = connection.get("cache_key")
        if not isinstance(connection_key, str) or not connection_key.strip():
            continue
        if not isinstance(cache_key, str) or not cache_key.strip():
            continue

        existing = deduped.get(connection_key)
        if existing is None:
            deduped[connection_key] = connection
            continue

        current_updated_at = _coerce_float(connection.get("updated_at")) or 0.0
        existing_updated_at = _coerce_float(existing.get("updated_at")) or 0.0
        if current_updated_at >= existing_updated_at:
            stale_cache_keys.append(str(existing["cache_key"]))
            deduped[connection_key] = connection
        else:
            stale_cache_keys.append(cache_key)

    for cache_key in stale_cache_keys:
        await _delete_scm_token_payload(cache_key)

    return sorted(
        deduped.values(),
        key=lambda item: _coerce_float(item.get("updated_at")) or 0.0,
        reverse=True,
    )


@router.get("/integrations/scm/oauth/authorize")
async def scm_oauth_authorize(
    request: Request,
    provider: str = Query(..., description="github or gitlab"),
    redirect_uri: str = Query(..., description="Frontend callback URL"),
    origin: str | None = Query(None),
    gitlab_base_url: str | None = Query(None),
    is_enterprise: bool = Query(False),
    auth_mode: str | None = Query(None, description="github_app"),
    response_mode: str = Query("redirect", description="redirect or json"),
) -> Any:
    """开始 SCM OAuth 授权流程."""
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

    authorize_url = scm_oauth_service.build_authorize_url(
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
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
) -> dict[str, Any]:
    """OAuth 回调处理器，处理授权完成后的令牌交换."""
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
            github_token_payload = await scm_oauth_service.exchange_github_oauth_token(
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
            user_profile = await scm_oauth_service.fetch_github_user_profile(
                access_token=access_token
            )
            full_payload: dict[str, Any] = {
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
            }
            full_payload.update(user_profile)
            await scm_token_store.set_token_payload(
                cache_key, cast("TokenPayload", full_payload)
            )
        elif provider == "gitlab":
            gitlab_base_url = state_payload.get("gitlab_base_url")
            resolved_base_url = _normalize_gitlab_base_url(
                gitlab_base_url if isinstance(gitlab_base_url, str) else None
            )
            enterprise = _is_gitlab_enterprise(
                resolved_base_url, bool(state_payload.get("is_enterprise"))
            )
            gitlab_token_payload = await scm_oauth_service.exchange_gitlab_oauth_token(
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
            user_profile = await scm_oauth_service.fetch_gitlab_user_profile(
                access_token=access_token,
                gitlab_base_url=resolved_base_url,
            )
            gitlab_full_payload: dict[str, Any] = {
                "provider": "gitlab",
                "gitlab_base_url": resolved_base_url,
                "access_token": access_token,
                "refresh_token": gitlab_token_payload.get("refresh_token"),
                "expires_in": gitlab_token_payload.get("expires_in"),
                "expires_at": gitlab_token_payload.get("expires_at"),
                "scope": gitlab_token_payload.get("scope"),
                "token_type": gitlab_token_payload.get("token_type"),
                "updated_at": time.time(),
            }
            gitlab_full_payload.update(user_profile)
            await scm_token_store.set_token_payload(
                cache_key, cast("TokenPayload", gitlab_full_payload)
            )
        else:
            return {"ok": False, "error": "不支持的 provider"}
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail)}
    except Exception as exc:  # pragma: no cover - defensive path
        return {"ok": False, "error": f"OAuth 回调处理失败: {exc}"}

    return {"ok": True}


async def _list_scm_token_rows_for_user(user_id: str) -> list[ScmToken]:
    """包装调用供测试 mock 使用."""
    return await scm_token_store.list_tokens_for_user(user_id)


@router.get("/integrations/scm/connections")
async def list_scm_connections(
    request: Request,
) -> dict[str, Any]:
    """列出用户已配置的所有 SCM 连接."""
    user_id = _resolve_request_user_identity(request)
    rows = await _list_scm_token_rows_for_user(user_id)

    connections: list[ScmConnectionInfo] = []
    for row in rows:
        item = _build_scm_connection_item(row)
        if item:
            connections.append(cast("ScmConnectionInfo", item))

    connections = await _dedupe_scm_connections(connections)
    return {"connections": connections}


@router.delete("/integrations/scm/connections")
async def revoke_scm_connection(
    request: Request,
    provider: str = Query(..., description="github or gitlab"),
    gitlab_base_url: str | None = Query(None),
    auth_mode: str | None = Query(None, description="github_app"),
) -> dict[str, Any]:
    """撤销并删除 SCM 连接."""
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
    await scm_token_store.delete_token_payload(cache_key)
    return {
        "ok": True,
        "connection_key": _resolve_scm_connection_key(
            provider=normalized_provider,
            gitlab_base_url=gitlab_base_url,
        ),
    }


@router.get("/integrations/scm/connections/validate")
async def validate_scm_connection(
    request: Request,
    provider: str = Query(..., description="github or gitlab"),
    gitlab_base_url: str | None = Query(None),
    auth_mode: str | None = Query(None, description="github_app"),
) -> dict[str, Any]:
    """验证 SCM 连接是否有效."""
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
        token = await scm_oauth_service.resolve_access_token(
            user_id=user_id,
            provider=normalized_provider,
            gitlab_base_url=gitlab_base_url,
            github_auth_mode=github_auth_mode,
        )
    except HTTPException as exc:
        if exc.status_code == 401:
            await scm_token_store.delete_token_payload(cache_key)
            return {
                "ok": True,
                "valid": False,
                "revoked": True,
                "error": str(exc.detail),
            }
        raise

    try:
        import httpx

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
            await scm_token_store.delete_token_payload(cache_key)
        return {
            "ok": True,
            "valid": False,
            "revoked": revoked,
            "error": str(exc.detail),
        }

    return {"ok": True, "valid": True, "revoked": False}


@router.get("/integrations/scm/repositories")
async def list_scm_repositories(
    request: Request,
    provider: str = Query(..., description="github or gitlab"),
    gitlab_base_url: str | None = Query(None),
    auth_mode: str | None = Query(None, description="github_app"),
) -> dict[str, Any]:
    """列出 SCM 账户中的所有仓库."""
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
    token = await scm_oauth_service.resolve_access_token(
        user_id=user_id,
        provider=normalized_provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )
    token_payload = await scm_token_store.resolve_token_payload(
        user_id=user_id,
        provider=normalized_provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )

    try:
        if normalized_provider == "github":
            repositories = await scm_repository_service.list_github_repositories(
                access_token=token,
                token_payload=token_payload,
            )
            return {"repositories": repositories}

        resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
        repositories = await scm_repository_service.list_gitlab_repositories(
            access_token=token,
            gitlab_base_url=resolved_base_url,
        )
        return {"repositories": repositories}
    except HTTPException as exc:
        if _should_revoke_scm_token(normalized_provider, exc):
            await scm_token_store.delete_token_payload(cache_key)
            raise HTTPException(401, "SCM 授权已失效或已被撤销，请重新授权") from exc
        raise


@router.get("/integrations/scm/branches")
async def list_scm_branches(
    request: Request,
    provider: str = Query(..., description="github or gitlab"),
    repository: str = Query(..., description="owner/repo"),
    gitlab_base_url: str | None = Query(None),
    auth_mode: str | None = Query(None, description="github_app"),
) -> dict[str, Any]:
    """列出指定仓库的所有分支."""
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
    token = await scm_oauth_service.resolve_access_token(
        user_id=user_id,
        provider=normalized_provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )
    repo_full_name = repository.strip()
    if not repo_full_name:
        raise HTTPException(400, "repository 不能为空")

    try:
        if normalized_provider == "github":
            branches = await scm_repository_service.list_github_branches(
                repository=repo_full_name,
                access_token=token,
            )
            return {"branches": branches}

        resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
        branches = await scm_repository_service.list_gitlab_branches(
            repository=repo_full_name,
            access_token=token,
            gitlab_base_url=resolved_base_url,
        )
        return {"branches": branches}
    except HTTPException as exc:
        if _should_revoke_scm_token(normalized_provider, exc):
            await scm_token_store.delete_token_payload(cache_key)
            raise HTTPException(401, "SCM 授权已失效或已被撤销，请重新授权") from exc
        raise


# Backward compatibility: re-export for imports from other modules
async def _resolve_scm_access_token(
    *,
    user_id: str,
    provider: str,
    gitlab_base_url: str | None,
    github_auth_mode: str | None = None,
) -> str:
    """Compatibility wrapper for external imports.

    This function is kept for backward compatibility - other modules in the codebase
    still import it from this module.
    """
    return await scm_oauth_service.resolve_access_token(
        user_id=user_id,
        provider=provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )


async def _resolve_scm_token_payload(
    *,
    user_id: str,
    provider: str,
    gitlab_base_url: str | None,
    github_auth_mode: str | None = None,
) -> TokenPayload:
    """Compatibility wrapper for external imports."""
    return await scm_token_store.resolve_token_payload(
        user_id=user_id,
        provider=provider,
        gitlab_base_url=gitlab_base_url,
        github_auth_mode=github_auth_mode,
    )


async def _set_scm_token_payload(
    cache_key: str,
    payload: TokenPayload,
) -> None:
    """Compatibility wrapper for external imports."""
    await scm_token_store.set_token_payload(cache_key, payload)


# Test mocks compatibility - re-export private functions that tests mock
_fetch_github_installation_repositories = (
    scm_repository_service.fetch_github_installation_repositories
)
_fetch_github_user_repositories = scm_repository_service.fetch_github_user_repositories
_refresh_github_oauth_token = scm_oauth_service.refresh_github_oauth_token
