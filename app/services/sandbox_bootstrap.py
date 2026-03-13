from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from aegra_api.core.orm import Thread as ThreadORM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.sandbox_git import (
    DEFAULT_TASK_GRAPH_ID,
    extract_graph_id_from_metadata,
    resolve_thread_graph_id,
)

if TYPE_CHECKING:
    from aegra_api.models.auth import User

BOOTSTRAP_METADATA_KEY = "sandbox_bootstrap"
BOOTSTRAP_LOG_LIMIT = 80
BOOTSTRAP_EVENT_LIMIT = 400
BOOTSTRAP_DEFAULT_STREAM_MODE: list[str] = ["messages-tuple"]


def utc_now_iso_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def default_bootstrap_steps() -> list[dict[str, Any]]:
    return [
        {"key": "container", "title": "容器创建", "status": "pending"},
        {"key": "repo", "title": "拉取代码", "status": "pending"},
        {"key": "bootstrap", "title": "下载依赖并启动", "status": "pending"},
    ]


def normalize_bootstrap_steps(raw_steps: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_steps, list):
        return default_bootstrap_steps()

    normalized: list[dict[str, Any]] = []
    allowed_status = {"pending", "running", "success", "error", "skipped"}
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            continue
        key = raw_step.get("key")
        title = raw_step.get("title")
        status = raw_step.get("status")
        detail = raw_step.get("detail")
        if not isinstance(key, str) or not key.strip():
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(status, str) or status not in allowed_status:
            continue
        step: dict[str, Any] = {
            "key": key.strip(),
            "title": title.strip(),
            "status": status,
        }
        if isinstance(detail, str) and detail.strip():
            step["detail"] = detail.strip()
        normalized.append(step)

    return normalized or default_bootstrap_steps()


def normalize_stream_mode(stream_mode: str | list[str] | None) -> list[str]:
    if isinstance(stream_mode, str):
        value = stream_mode.strip()
        return [value] if value else BOOTSTRAP_DEFAULT_STREAM_MODE.copy()
    if isinstance(stream_mode, list):
        normalized = [
            item.strip()
            for item in stream_mode
            if isinstance(item, str) and item.strip()
        ]
        return normalized or BOOTSTRAP_DEFAULT_STREAM_MODE.copy()
    return BOOTSTRAP_DEFAULT_STREAM_MODE.copy()


def can_destroy_container_for_bootstrap_reset(state: dict[str, Any]) -> bool:
    steps = state.get("steps")
    if not isinstance(steps, list):
        return False

    for step in steps:
        if not isinstance(step, dict):
            continue
        key = step.get("key")
        status = step.get("status")
        if key in {"container", "repo"} and status == "error":
            return True
    return False


def append_bootstrap_log(
    state: dict[str, Any],
    *,
    level: str,
    message: str,
    step: str | None = None,
) -> None:
    logs = state.get("logs")
    if not isinstance(logs, list):
        logs = []
    timestamp = utc_now_iso_z()
    log_entry: dict[str, Any] = {
        "timestamp": timestamp,
        "level": level,
        "message": message,
    }
    if isinstance(step, str) and step.strip():
        log_entry["step"] = step.strip()
    logs.append(log_entry)
    if len(logs) > BOOTSTRAP_LOG_LIMIT:
        logs = logs[-BOOTSTRAP_LOG_LIMIT:]
    state["logs"] = logs
    state["updated_at"] = timestamp

    current_seq = state.get("event_seq")
    event_seq = int(current_seq) + 1 if isinstance(current_seq, int) else 1
    state["event_seq"] = event_seq
    events = state.get("events")
    if not isinstance(events, list):
        events = []
    event_payload = {
        "seq": event_seq,
        "type": "log",
        "timestamp": timestamp,
        "level": level,
        "message": message,
    }
    if isinstance(step, str) and step.strip():
        event_payload["step"] = step.strip()
    events.append(event_payload)
    if len(events) > BOOTSTRAP_EVENT_LIMIT:
        events = events[-BOOTSTRAP_EVENT_LIMIT:]
    state["events"] = events


def normalize_bootstrap_state(raw_state: Any) -> dict[str, Any]:
    if not isinstance(raw_state, dict):
        return {
            "status": "idle",
            "steps": default_bootstrap_steps(),
            "logs": [],
            "events": [],
            "event_seq": 0,
        }

    status = raw_state.get("status")
    if not isinstance(status, str) or not status.strip():
        status = "idle"

    normalized: dict[str, Any] = {
        "status": status,
        "steps": normalize_bootstrap_steps(raw_state.get("steps")),
    }

    for key in (
        "request_id",
        "error",
        "run_id",
        "run_status",
        "started_at",
        "updated_at",
        "finished_at",
    ):
        value = raw_state.get(key)
        if isinstance(value, str) and value.strip():
            normalized[key] = value.strip()

    event_seq = raw_state.get("event_seq")
    normalized["event_seq"] = (
        event_seq if isinstance(event_seq, int) and event_seq >= 0 else 0
    )

    logs = raw_state.get("logs")
    if isinstance(logs, list):
        normalized_logs: list[dict[str, Any]] = []
        for item in logs[-BOOTSTRAP_LOG_LIMIT:]:
            if not isinstance(item, dict):
                continue
            timestamp = item.get("timestamp")
            level = item.get("level")
            message = item.get("message")
            if not isinstance(message, str) or not message.strip():
                continue
            normalized_logs.append(
                {
                    "timestamp": timestamp if isinstance(timestamp, str) else None,
                    "level": level if isinstance(level, str) else "info",
                    "message": message.strip(),
                }
            )
        normalized["logs"] = normalized_logs
    else:
        normalized["logs"] = []

    events = raw_state.get("events")
    if isinstance(events, list):
        normalized_events: list[dict[str, Any]] = []
        for item in events[-BOOTSTRAP_EVENT_LIMIT:]:
            if not isinstance(item, dict):
                continue
            seq = item.get("seq")
            message = item.get("message")
            level = item.get("level")
            if not isinstance(seq, int) or seq <= 0:
                continue
            if not isinstance(message, str) or not message.strip():
                continue
            event_payload: dict[str, Any] = {
                "seq": seq,
                "type": "log",
                "timestamp": (
                    item.get("timestamp")
                    if isinstance(item.get("timestamp"), str)
                    else None
                ),
                "level": level if isinstance(level, str) else "info",
                "message": message.strip(),
            }
            step = item.get("step")
            if isinstance(step, str) and step.strip():
                event_payload["step"] = step.strip()
            normalized_events.append(event_payload)
        normalized["events"] = normalized_events
        if normalized_events:
            max_seq = max(
                (event.get("seq", 0) for event in normalized_events), default=0
            )
            if normalized["event_seq"] < max_seq:
                normalized["event_seq"] = max_seq
    else:
        normalized["events"] = []

    return normalized


def build_bootstrap_response(
    *,
    thread_id: str,
    graph_id: str,
    state: dict[str, Any],
    accepted: bool | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "thread_id": thread_id,
        "graph_id": graph_id,
        "status": state.get("status", "idle"),
        "steps": state.get("steps") or default_bootstrap_steps(),
        "logs": state.get("logs") or [],
        "event_seq": (
            state.get("event_seq") if isinstance(state.get("event_seq"), int) else 0
        ),
        "error": state.get("error"),
        "request_id": state.get("request_id"),
        "run_id": state.get("run_id"),
        "run_status": state.get("run_status"),
        "started_at": state.get("started_at"),
        "updated_at": state.get("updated_at"),
        "finished_at": state.get("finished_at"),
    }
    if accepted is not None:
        response["accepted"] = accepted
    return response


def snapshot_user_payload(user: User) -> dict[str, Any]:
    as_dict: Any = None
    try:
        as_dict = user.to_dict()
    except Exception:
        as_dict = None
    if isinstance(as_dict, dict):
        return as_dict

    payload = {
        "identity": user.identity,
        "display_name": getattr(user, "display_name", None),
        "permissions": getattr(user, "permissions", []),
        "is_authenticated": getattr(user, "is_authenticated", True),
    }
    if hasattr(user, "role"):
        payload["role"] = user.role
    if hasattr(user, "team_id"):
        payload["team_id"] = user.team_id
    if hasattr(user, "email"):
        payload["email"] = user.email
    return payload


async def persist_bootstrap_state(
    session: AsyncSession,
    *,
    thread: ThreadORM,
    graph_id: str,
    state: dict[str, Any],
) -> None:
    metadata = thread.metadata_json if isinstance(thread.metadata_json, dict) else {}
    metadata = dict(metadata)
    if extract_graph_id_from_metadata(metadata) is None:
        metadata["graph_id"] = graph_id
    metadata[BOOTSTRAP_METADATA_KEY] = state
    thread.metadata_json = metadata
    await session.commit()


async def read_thread_and_bootstrap_state(
    session: AsyncSession,
    *,
    thread_id: str,
    user_id: str,
) -> tuple[ThreadORM | None, str, dict[str, Any], dict[str, Any]]:
    stmt = select(ThreadORM).where(
        ThreadORM.thread_id == thread_id,
        ThreadORM.user_id == user_id,
    )
    thread = await session.scalar(stmt)
    if not thread:
        return None, DEFAULT_TASK_GRAPH_ID, {}, normalize_bootstrap_state(None)

    graph_id = await resolve_thread_graph_id(session, thread=thread)
    metadata = thread.metadata_json if isinstance(thread.metadata_json, dict) else {}
    metadata = dict(metadata)
    if extract_graph_id_from_metadata(metadata) is None:
        metadata["graph_id"] = graph_id
        thread.metadata_json = metadata
        await session.commit()

    bootstrap_state = normalize_bootstrap_state(metadata.get(BOOTSTRAP_METADATA_KEY))
    return thread, graph_id, metadata, bootstrap_state
