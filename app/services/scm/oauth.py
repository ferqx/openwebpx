from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from .token_store import ScmTokenStore, scm_token_store
from .utils import (
    _compute_expires_at,
    _env_first,
    _is_gitlab_enterprise,
    _is_token_payload_expired,
    _normalize_github_auth_mode,
    _normalize_gitlab_base_url,
    _raise_upstream_connect_error,
    _resolve_gitlab_oauth_scope,
    _scm_token_cache_key,
)

if TYPE_CHECKING:
    from .types import TokenPayload


class ScmOAuthService:
    """SCM OAuth 认证服务.

    负责 GitHub/GitLab 的 OAuth 授权流程，包括：
    - 构建授权 URL
    - 交换 code 获得 access token
    - 刷新令牌
    - 获取用户信息
    """

    def __init__(self, token_store: ScmTokenStore = scm_token_store):
        self.token_store = token_store

    def build_authorize_url(
        self,
        *,
        provider: str,
        state: str,
        redirect_uri: str,
        gitlab_base_url: str | None,
        is_enterprise: bool,
        github_auth_mode: str | None = None,
    ) -> str:
        """构建 SCM 授权 URL."""
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

    def resolve_github_client_credentials(self) -> tuple[str, str]:
        """获取 GitHub OAuth 客户端凭证."""
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

    def resolve_gitlab_client_credentials(
        self, *, is_enterprise: bool
    ) -> tuple[str, str]:
        """获取 GitLab OAuth 客户端凭证."""
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
            client_secret = _env_first(
                "GITLAB_OAUTH_CLIENT_SECRET", "GITLAB_CLIENT_SECRET"
            )

        if not client_id or not client_secret:
            raise HTTPException(500, "缺少 GitLab OAuth Client ID/Secret 环境变量")
        return client_id, client_secret

    async def exchange_github_oauth_token(
        self,
        *,
        code: str,
        redirect_uri: str,
        github_auth_mode: str | None = None,
    ) -> dict[str, Any]:
        """用 code 交换 GitHub OAuth 令牌."""
        normalized_mode = _normalize_github_auth_mode(github_auth_mode)
        client_id, client_secret = self.resolve_github_client_credentials()

        async with httpx.AsyncClient(timeout=20) as http_client:
            try:
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
            except httpx.HTTPError as exc:
                _raise_upstream_connect_error("GitHub token 交换", exc)

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

    async def refresh_github_oauth_token(
        self,
        *,
        refresh_token: str,
        github_auth_mode: str | None = None,
    ) -> dict[str, Any]:
        """刷新 GitHub OAuth 令牌."""
        normalized_mode = _normalize_github_auth_mode(github_auth_mode)
        client_id, client_secret = self.resolve_github_client_credentials()

        async with httpx.AsyncClient(timeout=20) as http_client:
            try:
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
            except httpx.HTTPError as exc:
                _raise_upstream_connect_error("GitHub token 刷新", exc)

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
            raise HTTPException(401, "GitHub 刷新未返回 access_token")

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

    async def exchange_gitlab_oauth_token(
        self,
        *,
        code: str,
        redirect_uri: str,
        gitlab_base_url: str,
        is_enterprise: bool,
    ) -> dict[str, Any]:
        """用 code 交换 GitLab OAuth 令牌."""
        client_id, client_secret = self.resolve_gitlab_client_credentials(
            is_enterprise=is_enterprise
        )

        async with httpx.AsyncClient(timeout=20) as http_client:
            try:
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
            except httpx.HTTPError as exc:
                _raise_upstream_connect_error("GitLab token 交换", exc)

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

    async def refresh_gitlab_oauth_token(
        self,
        *,
        refresh_token: str,
        gitlab_base_url: str,
        is_enterprise: bool,
    ) -> dict[str, Any]:
        """刷新 GitLab OAuth 令牌."""
        client_id, client_secret = self.resolve_gitlab_client_credentials(
            is_enterprise=is_enterprise
        )

        async with httpx.AsyncClient(timeout=20) as http_client:
            try:
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
            except httpx.HTTPError as exc:
                _raise_upstream_connect_error("GitLab token 刷新", exc)

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
            raise HTTPException(401, "GitLab 刷新未返回 access_token")

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

    async def fetch_github_user_profile(
        self,
        *,
        access_token: str,
    ) -> dict[str, str]:
        """获取 GitHub 认证用户信息."""
        async with httpx.AsyncClient(timeout=20) as http_client:
            try:
                response = await http_client.get(
                    "https://api.github.com/user",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {access_token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
            except httpx.HTTPError:
                return {}
        if response.status_code >= 400:
            return {}
        payload = response.json() if response.content else {}
        if not isinstance(payload, dict):
            return {}
        login = payload.get("login")
        name = payload.get("name")
        email = payload.get("email")
        return {
            "scm_user_login": login.strip() if isinstance(login, str) else "",
            "scm_user_name": name.strip() if isinstance(name, str) else "",
            "scm_user_email": email.strip().lower() if isinstance(email, str) else "",
        }

    async def fetch_gitlab_user_profile(
        self,
        *,
        access_token: str,
        gitlab_base_url: str,
    ) -> dict[str, str]:
        """获取 GitLab 认证用户信息."""
        async with httpx.AsyncClient(timeout=20) as http_client:
            response = await http_client.get(
                f"{gitlab_base_url}/api/v4/user",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if response.status_code >= 400:
            return {}
        payload = response.json() if response.content else {}
        if not isinstance(payload, dict):
            return {}
        username = payload.get("username")
        name = payload.get("name")
        email = payload.get("email")
        return {
            "scm_user_login": username.strip() if isinstance(username, str) else "",
            "scm_user_name": name.strip() if isinstance(name, str) else "",
            "scm_user_email": email.strip().lower() if isinstance(email, str) else "",
        }

    async def refresh_token_if_needed(
        self,
        *,
        user_id: str,
        provider: str,
        gitlab_base_url: str | None,
        github_auth_mode: str | None,
        token_payload: TokenPayload,
    ) -> TokenPayload:
        """如果令牌过期，刷新令牌并保存."""
        if not _is_token_payload_expired(token_payload):
            return token_payload

        refresh_token = token_payload.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token.strip():
            raise HTTPException(401, "SCM 授权已过期，请重新授权")

        refreshed_payload: dict[str, Any]
        if provider == "github":
            refreshed_payload = await self.refresh_github_oauth_token(
                refresh_token=refresh_token.strip(),
                github_auth_mode=github_auth_mode,
            )
        else:
            resolved_base_url = _normalize_gitlab_base_url(gitlab_base_url)
            enterprise = _is_gitlab_enterprise(resolved_base_url, False)
            refreshed_payload = await self.refresh_gitlab_oauth_token(
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
        typed_next_payload = cast("TokenPayload", next_payload)
        await self.token_store.set_token_payload(cache_key, typed_next_payload)
        return typed_next_payload

    async def resolve_access_token(
        self,
        *,
        user_id: str,
        provider: str,
        gitlab_base_url: str | None,
        github_auth_mode: str | None = None,
    ) -> str:
        """解析并返回有效的 access token，自动刷新过期令牌."""
        cache_key = _scm_token_cache_key(
            user_id=user_id,
            provider=provider,
            gitlab_base_url=gitlab_base_url,
            github_auth_mode=github_auth_mode,
        )
        token_payload = await self.token_store.resolve_token_payload(
            user_id=user_id,
            provider=provider,
            gitlab_base_url=gitlab_base_url,
            github_auth_mode=github_auth_mode,
        )

        if _is_token_payload_expired(token_payload):
            try:
                token_payload = await self.refresh_token_if_needed(
                    user_id=user_id,
                    provider=provider,
                    gitlab_base_url=gitlab_base_url,
                    github_auth_mode=github_auth_mode,
                    token_payload=token_payload,
                )
            except HTTPException as exc:
                if exc.status_code == 401:
                    await self.token_store.delete_token_payload(cache_key)
                raise

        token = token_payload.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise HTTPException(401, "授权令牌不存在，请重新授权")
        return token.strip()


# Global singleton instance
scm_oauth_service = ScmOAuthService()
