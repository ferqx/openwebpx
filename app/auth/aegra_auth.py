from __future__ import annotations

import asyncio
import logging
from http.cookies import SimpleCookie
from typing import Any

from docker.errors import DockerException, NotFound
from langgraph_sdk import Auth

from app.auth.core import decode_access_token

auth = Auth()
logger = logging.getLogger(__name__)


def _get_user_attr(user: Any, key: str) -> Any:
    if isinstance(user, dict):
        return user.get(key)
    return getattr(user, key, None)


def _extract_bearer_token(headers: dict[str, str]) -> str | None:
    auth_header = headers.get("authorization", "") or headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        return token or None

    cookie_header = headers.get("cookie", "") or headers.get("Cookie", "")
    if not cookie_header:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:  # pragma: no cover - malformed cookie fallback
        return None

    morsel = cookie.get("aegra_access_token")
    if morsel is None:
        return None
    value = morsel.value.strip()
    return value or None


@auth.authenticate
async def authenticate(headers: dict) -> dict:
    token = _extract_bearer_token(headers)
    if not token:
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header/cookie",
        )

    try:
        return decode_access_token(token)
    except ValueError as exc:
        raise Auth.exceptions.HTTPException(status_code=401, detail=str(exc)) from exc


@auth.on
async def authorize(ctx, value):
    _ = (ctx, value)
    return True


@auth.on.threads.create
async def allow_thread_create(ctx, value):
    if value.get("metadata") is None:
        value["metadata"] = {}

    value["metadata"]["owner_id"] = _get_user_attr(ctx.user, "identity")
    team_id = _get_user_attr(ctx.user, "team_id")
    if isinstance(team_id, str) and team_id.strip():
        value["metadata"]["team_id"] = team_id.strip()
    return True


@auth.on.threads.search
async def filter_threads_by_user(ctx, value):
    _ = value
    return {"user_id": _get_user_attr(ctx.user, "identity")}


@auth.on.assistants.delete
async def restrict_assistant_deletion(ctx, value):
    _ = value
    role = _get_user_attr(ctx.user, "role")
    return role == "admin"


@auth.on.assistants.create
async def allow_assistant_create(ctx, value):
    if value.get("metadata") is None:
        value["metadata"] = {}
    value["metadata"]["created_by"] = _get_user_attr(ctx.user, "identity")
    return True


async def _resolve_thread_container_id_for_delete(
    *,
    thread_id: str,
    user: Any,
) -> str | None:
    """Best-effort 解析线程绑定容器 ID（用于线程删除时清理容器）。"""
    user_id = str(_get_user_attr(user, "identity") or "").strip()
    if not user_id:
        return None

    try:
        from aegra_api.core.orm import Thread as ThreadORM
        from aegra_api.core.orm import _get_session_maker
        from aegra_api.services.langgraph_service import (
            create_thread_config,
            get_langgraph_service,
        )
        from sqlalchemy import select
    except Exception:  # pragma: no cover - 容错路径
        return None

    session_maker = _get_session_maker()
    async with session_maker() as session:
        thread = await session.scalar(
            select(ThreadORM).where(
                ThreadORM.thread_id == thread_id,
                ThreadORM.user_id == user_id,
            )
        )
    if thread is None:
        return None

    metadata = thread.metadata_json if isinstance(thread.metadata_json, dict) else {}
    graph_id = str(metadata.get("graph_id") or "").strip()
    if not graph_id:
        return None

    try:
        config = create_thread_config(thread_id, user, {})
        langgraph_service = get_langgraph_service()
        async with langgraph_service.get_graph(
            graph_id,
            config=config,
            access_context="threads.delete",
            user=user,
        ) as agent:
            agent = agent.with_config(config)
            snapshot = await agent.aget_state(config, subgraphs=False)
    except Exception:  # pragma: no cover - 容错路径
        return None

    values = getattr(snapshot, "values", None)
    if not isinstance(values, dict):
        return None

    container_id = values.get("container_id")
    if isinstance(container_id, str) and container_id.strip():
        return container_id.strip()
    return None


def _destroy_container_for_thread_delete(container_id: str) -> tuple[bool, str | None]:
    """线程删除时销毁容器；失败不抛异常，交给调用方降级处理。"""
    try:
        import docker

        client = docker.from_env()
        container = client.containers.get(container_id)
        container.remove(force=True)
        return True, None
    except NotFound:
        return True, None
    except DockerException as exc:
        return False, str(exc)


@auth.on.threads.delete
async def cleanup_thread_container_on_delete(ctx, value):
    thread_id = str((value or {}).get("thread_id") or "").strip()
    if not thread_id:
        return True

    container_id = await _resolve_thread_container_id_for_delete(
        thread_id=thread_id,
        user=ctx.user,
    )
    if not container_id:
        return True

    destroyed, destroy_error = await asyncio.to_thread(
        _destroy_container_for_thread_delete,
        container_id,
    )
    if not destroyed:
        logger.warning(
            "Failed to destroy container %s while deleting thread %s: %s",
            container_id,
            thread_id,
            destroy_error,
        )
    return True
