from __future__ import annotations

from http.cookies import SimpleCookie
from typing import Any

from langgraph_sdk import Auth

from app.auth.core import decode_access_token

auth = Auth()


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
