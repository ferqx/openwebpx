from __future__ import annotations

import os
import time
import uuid
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

router = APIRouter()

SCM_OAUTH_STATE_TTL_SECONDS = 10 * 60
SCM_OAUTH_STATES: dict[str, dict[str, Any]] = {}
SCM_TOKENS: dict[str, dict[str, Any]] = {}


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


def _normalize_gitlab_base_url(value: str | None) -> str:
    if not value or not value.strip():
        return "https://gitlab.com"
    normalized = value.strip().rstrip("/")
    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"
    return normalized


def _is_gitlab_enterprise(base_url: str, is_enterprise: bool) -> bool:
    return is_enterprise or base_url.rstrip("/").lower() != "https://gitlab.com"


def _cleanup_expired_scm_oauth_states() -> None:
    now = time.time()
    expired_keys = [
        state
        for state, payload in SCM_OAUTH_STATES.items()
        if now - float(payload.get("created_at", now)) > SCM_OAUTH_STATE_TTL_SECONDS
    ]
    for state in expired_keys:
        SCM_OAUTH_STATES.pop(state, None)


def _scm_token_cache_key(
    *,
    user_id: str,
    provider: str,
    gitlab_base_url: str | None = None,
) -> str:
    if provider == "github":
        return f"{user_id}:github"
    normalized_base_url = _normalize_gitlab_base_url(gitlab_base_url).lower()
    return f"{user_id}:gitlab:{normalized_base_url}"


def _build_scm_authorize_url(
    *,
    provider: str,
    state: str,
    redirect_uri: str,
    gitlab_base_url: str | None,
    is_enterprise: bool,
) -> str:
    if provider == "github":
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
        "scope": "read_api read_user",
        "state": state,
    }
    return f"{resolved_base_url}/oauth/authorize?{urlencode(params)}"


def _resolve_scm_access_token(
    *,
    user_id: str,
    provider: str,
    gitlab_base_url: str | None,
) -> str:
    token_payload = _resolve_scm_token_payload(
        user_id=user_id,
        provider=provider,
        gitlab_base_url=gitlab_base_url,
    )
    token = token_payload.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise HTTPException(401, "授权令牌不存在，请重新授权")
    return token.strip()


def _resolve_scm_token_payload(
    *,
    user_id: str,
    provider: str,
    gitlab_base_url: str | None,
) -> dict[str, Any]:
    token_payload = SCM_TOKENS.get(
        _scm_token_cache_key(
            user_id=user_id, provider=provider, gitlab_base_url=gitlab_base_url
        )
    )
    if not token_payload:
        raise HTTPException(401, "请先完成 OAuth 授权")
    if not isinstance(token_payload, dict):
        raise HTTPException(401, "授权令牌不存在，请重新授权")
    return token_payload


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


async def _exchange_github_oauth_token(
    *,
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
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
    if not isinstance(payload, dict):
        return {  # nosec B105
            "access_token": token.strip(),
            "github_token_source": "github_app",
        }
    return {
        "access_token": token.strip(),
        "refresh_token": payload.get("refresh_token"),
        "expires_in": payload.get("expires_in"),
        "refresh_token_expires_in": payload.get("refresh_token_expires_in"),
        "scope": payload.get("scope"),
        "token_type": payload.get("token_type"),
        "github_token_source": "github_app",  # nosec B105
    }


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
) -> str:
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
        raise HTTPException(400, f"GitLab 授权失败: {payload.get('error')}")

    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise HTTPException(502, "GitLab 未返回 access_token")
    return token.strip()


@router.get("/integrations/scm/oauth/authorize")
async def scm_oauth_authorize(
    provider: str = Query(..., description="github or gitlab"),
    redirect_uri: str = Query(..., description="Frontend callback URL"),
    origin: str | None = Query(None),
    gitlab_base_url: str | None = Query(None),
    is_enterprise: bool = Query(False),
    request: Request = None,
) -> RedirectResponse:
    normalized_provider = _normalize_scm_provider(provider)
    if not redirect_uri.strip():
        raise HTTPException(400, "redirect_uri 不能为空")

    _cleanup_expired_scm_oauth_states()
    state = uuid.uuid4().hex
    resolved_base_url = (
        _normalize_gitlab_base_url(gitlab_base_url)
        if normalized_provider == "gitlab"
        else None
    )

    user_id = _resolve_request_user_identity(request)
    SCM_OAUTH_STATES[state] = {
        "provider": normalized_provider,
        "user_id": user_id,
        "created_at": time.time(),
        "redirect_uri": redirect_uri,
        "gitlab_base_url": resolved_base_url,
        "is_enterprise": bool(is_enterprise),
        "origin": origin,
    }

    authorize_url = _build_scm_authorize_url(
        provider=normalized_provider,
        state=state,
        redirect_uri=redirect_uri,
        gitlab_base_url=resolved_base_url,
        is_enterprise=is_enterprise,
    )
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
    state_payload = SCM_OAUTH_STATES.pop(state, None)
    if not state_payload:
        return {"ok": False, "error": "OAuth state 无效或已过期"}
    if state_payload.get("user_id") != user_id:
        return {"ok": False, "error": "OAuth state 与当前用户不匹配"}

    provider = str(state_payload.get("provider", "")).strip().lower()
    redirect_uri = (
        params.get("redirect_uri")
        or payload_dict.get("redirect_uri")
        or state_payload.get("redirect_uri")
    )
    if not isinstance(redirect_uri, str) or not redirect_uri.strip():
        return {"ok": False, "error": "缺少 redirect_uri"}

    try:
        if provider == "github":
            github_token_payload = await _exchange_github_oauth_token(
                code=code,
                redirect_uri=redirect_uri,
            )
            access_token = github_token_payload["access_token"]
            cache_key = _scm_token_cache_key(
                user_id=user_id,
                provider="github",
            )
            SCM_TOKENS[cache_key] = {
                "provider": "github",
                "access_token": access_token,
                "updated_at": time.time(),
                "github_token_source": github_token_payload.get(
                    "github_token_source", "github_app"
                ),
                "refresh_token": github_token_payload.get("refresh_token"),
                "expires_in": github_token_payload.get("expires_in"),
                "refresh_token_expires_in": github_token_payload.get(
                    "refresh_token_expires_in"
                ),
                "scope": github_token_payload.get("scope"),
                "token_type": github_token_payload.get("token_type"),
            }
        elif provider == "gitlab":
            gitlab_base_url = state_payload.get("gitlab_base_url")
            resolved_base_url = _normalize_gitlab_base_url(
                gitlab_base_url if isinstance(gitlab_base_url, str) else None
            )
            enterprise = _is_gitlab_enterprise(
                resolved_base_url, bool(state_payload.get("is_enterprise"))
            )
            access_token = await _exchange_gitlab_oauth_token(
                code=code,
                redirect_uri=redirect_uri,
                gitlab_base_url=resolved_base_url,
                is_enterprise=enterprise,
            )
            cache_key = _scm_token_cache_key(
                user_id=user_id,
                provider="gitlab",
                gitlab_base_url=resolved_base_url,
            )
            SCM_TOKENS[cache_key] = {
                "provider": "gitlab",
                "gitlab_base_url": resolved_base_url,
                "access_token": access_token,
                "updated_at": time.time(),
            }
        else:
            return {"ok": False, "error": "不支持的 provider"}
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail)}
    except Exception as exc:  # pragma: no cover - defensive path
        return {"ok": False, "error": f"OAuth 回调处理失败: {exc}"}

    return {"ok": True}


@router.get("/integrations/scm/repositories")
async def list_scm_repositories(
    provider: str = Query(..., description="github or gitlab"),
    gitlab_base_url: str | None = Query(None),
    request: Request = None,
) -> dict[str, Any]:
    normalized_provider = _normalize_scm_provider(provider)
    user_id = _resolve_request_user_identity(request)
    token_payload = _resolve_scm_token_payload(
        user_id=user_id,
        provider=normalized_provider,
        gitlab_base_url=gitlab_base_url,
    )
    token = _resolve_scm_access_token(
        user_id=user_id,
        provider=normalized_provider,
        gitlab_base_url=gitlab_base_url,
    )

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


@router.get("/integrations/scm/branches")
async def list_scm_branches(
    provider: str = Query(..., description="github or gitlab"),
    repository: str = Query(..., description="owner/repo"),
    gitlab_base_url: str | None = Query(None),
    request: Request = None,
) -> dict[str, Any]:
    normalized_provider = _normalize_scm_provider(provider)
    user_id = _resolve_request_user_identity(request)
    token = _resolve_scm_access_token(
        user_id=user_id,
        provider=normalized_provider,
        gitlab_base_url=gitlab_base_url,
    )
    repo_full_name = repository.strip()
    if not repo_full_name:
        raise HTTPException(400, "repository 不能为空")

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
