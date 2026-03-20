from __future__ import annotations

import time
from threading import RLock
from typing import TYPE_CHECKING, Any, cast

from aegra_api.core.orm import _get_session_maker
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.models.scm_token import ScmToken

from .crypto import (
    _decrypt_scm_token_payload,
    _encrypt_scm_token_payload,
)
from .utils import (
    _coerce_float,
    _normalize_github_auth_mode,
    _normalize_gitlab_base_url,
    _scm_token_cache_key,
)

if TYPE_CHECKING:
    from .types import TokenPayload


class ScmTokenStore:
    """SCM 令牌存储服务.

    负责加密令牌的持久化存储和内存缓存。
    """

    SCM_TOKENS: dict[str, TokenPayload]
    SCM_TOKEN_STORE_LOCK: RLock

    def __init__(self) -> None:
        self.SCM_TOKENS: dict[str, TokenPayload] = {}
        self.SCM_TOKEN_STORE_LOCK = RLock()

    def _parse_scm_cache_key(self, cache_key: str) -> tuple[str, str]:
        """解析缓存键得到 user_id 和 provider_scope."""
        head, sep, tail = cache_key.partition(":")
        if not sep:
            raise HTTPException(400, "无效的 SCM 缓存键")
        return head, tail

    async def set_token_payload(
        self,
        cache_key: str,
        payload: TokenPayload,
    ) -> None:
        """保存令牌载荷到数据库和缓存."""
        user_id, provider_scope = self._parse_scm_cache_key(cache_key)
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
                existing = await session.get(ScmToken, cache_key)

                if existing:
                    existing.user_id = user_id
                    existing.provider = provider
                    existing.gitlab_base_url = gitlab_base_url
                    existing.github_auth_mode = github_auth_mode
                    existing.token_encrypted = encrypted
                    existing.updated_at = updated_at
                else:
                    new_token = ScmToken(
                        cache_key=cache_key,
                        user_id=user_id,
                        provider=provider,
                        gitlab_base_url=gitlab_base_url,
                        github_auth_mode=github_auth_mode,
                        token_encrypted=encrypted,
                        updated_at=updated_at,
                    )
                    session.add(new_token)

                await session.commit()
            except SQLAlchemyError as exc:
                await session.rollback()
                raise HTTPException(500, f"保存 SCM token 失败: {exc}") from exc

        with self.SCM_TOKEN_STORE_LOCK:
            self.SCM_TOKENS[cache_key] = payload

    async def delete_token_payload(self, cache_key: str) -> None:
        """删除令牌."""
        with self.SCM_TOKEN_STORE_LOCK:
            self.SCM_TOKENS.pop(cache_key, None)

        session_maker = _get_session_maker()
        async with session_maker() as session:
            try:
                token = await session.get(ScmToken, cache_key)
                if token:
                    await session.delete(token)
                    await session.commit()
            except SQLAlchemyError as exc:
                await session.rollback()
                raise HTTPException(500, f"删除 SCM token 失败: {exc}") from exc

    async def list_tokens_for_user(self, user_id: str) -> list[ScmToken]:
        """列出用户的所有令牌."""
        session_maker = _get_session_maker()
        async with session_maker() as session:
            try:
                query = (
                    select(ScmToken)
                    .where(ScmToken.user_id == user_id)
                    .order_by(ScmToken.updated_at.desc())
                )
                result = await session.execute(query)
                return list(result.scalars().all())
            except SQLAlchemyError as exc:
                raise HTTPException(500, f"查询 SCM 授权列表失败: {exc}") from exc

    async def resolve_token_payload(
        self,
        *,
        user_id: str,
        provider: str,
        gitlab_base_url: str | None,
        github_auth_mode: str | None = None,
    ) -> TokenPayload:
        """解析令牌载荷，优先使用内存缓存."""
        cache_key = _scm_token_cache_key(
            user_id=user_id,
            provider=provider,
            gitlab_base_url=gitlab_base_url,
            github_auth_mode=github_auth_mode,
        )

        token_payload = self.SCM_TOKENS.get(cache_key)
        if isinstance(token_payload, dict):
            return token_payload

        session_maker = _get_session_maker()
        async with session_maker() as session:
            try:
                result = await session.execute(
                    select(ScmToken).where(ScmToken.cache_key == cache_key)
                )
            except SQLAlchemyError as exc:
                raise HTTPException(401, "请先完成 OAuth 授权") from exc
            row = result.scalar_one_or_none()

        if not row:
            raise HTTPException(401, "请先完成 OAuth 授权")

        token_encrypted = row.token_encrypted
        if not token_encrypted or not token_encrypted.strip():
            await self.delete_token_payload(cache_key)
            raise HTTPException(401, "授权令牌不存在，请重新授权")

        payload = _decrypt_scm_token_payload(token_encrypted.strip())
        if not isinstance(payload, dict):
            await self.delete_token_payload(cache_key)
            raise HTTPException(401, "授权令牌已损坏，请重新授权")

        token_payload = cast("TokenPayload", payload)
        with self.SCM_TOKEN_STORE_LOCK:
            self.SCM_TOKENS[cache_key] = token_payload
        return token_payload

    async def dedupe_connections(
        self,
        connections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """按 connection_key 去重，保留最新记录."""
        deduped: dict[str, dict[str, Any]] = {}
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
            await self.delete_token_payload(cache_key)

        return sorted(
            deduped.values(),
            key=lambda item: _coerce_float(item.get("updated_at")) or 0.0,
            reverse=True,
        )


def _parse_scm_cache_key(cache_key: str) -> tuple[str, str]:
    """保持向后兼容的独立实现."""
    head, sep, tail = cache_key.partition(":")
    if not sep:
        raise HTTPException(400, "无效的 SCM 缓存键")
    return head, tail


# Global singleton instance
scm_token_store = ScmTokenStore()
