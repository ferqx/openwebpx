from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from aegra_api.core.orm import Run as RunORM
from aegra_api.core.orm import Thread as ThreadORM
from aegra_api.services.langgraph_service import (
    create_thread_config,
    get_langgraph_service,
)
from fastapi import HTTPException
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backends.docker import DockerBackend

if TYPE_CHECKING:
    from aegra_api.models.auth import User

DEFAULT_TASK_GRAPH_ID = os.getenv(
    "OPENWEBPX_DEFAULT_TASK_GRAPH_ID", "build_app_agent_v3"
)
COMMIT_MESSAGE_MODEL_PROVIDER = os.getenv(
    "OPENWEBPX_COMMIT_MESSAGE_MODEL_PROVIDER", "openai"
)
COMMIT_MESSAGE_MODEL_NAME = os.getenv(
    "OPENWEBPX_COMMIT_MESSAGE_MODEL_NAME", "deepseek-chat"
)
_raw_git_diff_default_max_chars = os.getenv(
    "OPENWEBPX_GIT_DIFF_DEFAULT_MAX_CHARS", "0"
).strip()
try:
    GIT_DIFF_DEFAULT_MAX_CHARS = int(_raw_git_diff_default_max_chars)
except ValueError:
    GIT_DIFF_DEFAULT_MAX_CHARS = 0
GIT_DIFF_MAX_CHARS_LIMIT = 2_000_000
GIT_DIFF_MODEL_MAX_CHARS = 12_000


def utc_now_iso_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def truncate_text(value: str, *, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0:
        return value, False
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


def coerce_model_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
                continue
            if isinstance(item, dict):
                text_value = item.get("text")
                if isinstance(text_value, str) and text_value.strip():
                    parts.append(text_value.strip())
        return "\n".join(parts).strip()

    return ""


def sanitize_commit_message(value: str) -> str:
    # git commit subject 保持单行，避免把多段内容误注入 shell。
    line = value.replace("\r", "\n").split("\n", 1)[0].strip()
    line = line.strip("`").strip("\"'").strip()
    return line[:200].strip()


def parse_git_porcelain_line(line: str) -> dict[str, Any] | None:
    if len(line) < 3:
        return None
    index_status = line[0]
    worktree_status = line[1]
    path_raw = line[3:].strip()
    if not path_raw:
        return None

    old_path: str | None = None
    path = path_raw
    if " -> " in path_raw:
        old_path, path = path_raw.split(" -> ", 1)
        old_path = old_path.strip() or None
        path = path.strip()

    status = f"{index_status}{worktree_status}"
    is_staged = index_status not in {" ", "?"}
    is_unstaged = worktree_status != " " or status == "??"
    return {
        "status": status,
        "index_status": index_status,
        "worktree_status": worktree_status,
        "path": path,
        "old_path": old_path,
        "is_staged": is_staged,
        "is_unstaged": is_unstaged,
    }


def parse_git_porcelain(output: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip("\n")
        if not line:
            continue
        parsed = parse_git_porcelain_line(line)
        if parsed is not None:
            entries.append(parsed)
    return entries


def extract_graph_id_from_metadata(metadata: dict[str, Any] | None) -> str | None:
    if not isinstance(metadata, dict):
        return None

    candidates = [
        metadata.get("graph_id"),
        metadata.get("graphId"),
        metadata.get("assistant_id"),
        metadata.get("assistantId"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


async def resolve_thread_graph_id(
    session: AsyncSession,
    *,
    thread: ThreadORM,
) -> str:
    metadata = thread.metadata_json if isinstance(thread.metadata_json, dict) else {}
    graph_id = extract_graph_id_from_metadata(metadata)
    if graph_id:
        return graph_id

    latest_assistant_id_stmt = (
        select(RunORM.assistant_id)
        .where(RunORM.thread_id == thread.thread_id)
        .order_by(RunORM.created_at.desc())
        .limit(1)
    )
    latest_assistant_id = await session.scalar(latest_assistant_id_stmt)
    if isinstance(latest_assistant_id, str) and latest_assistant_id.strip():
        return latest_assistant_id.strip()

    return DEFAULT_TASK_GRAPH_ID


async def ensure_backend_container_running(backend: DockerBackend) -> None:
    def _ensure_running() -> str:
        container = backend.container
        container.reload()
        current_status = str(getattr(container, "status", "")).strip().lower()
        if current_status != "running":
            # git 路径也需要兼容复用中的 paused 容器，避免把 unpause 场景误判成 start。
            if current_status == "paused":
                container.unpause()
            else:
                container.start()
            container.reload()
            current_status = str(getattr(container, "status", "")).strip().lower()
        return current_status

    try:
        status = await asyncio.to_thread(_ensure_running)
    except Exception as exc:
        raise HTTPException(
            409,
            f"Sandbox container is unavailable for git operations: {exc}",
        ) from exc

    if status != "running":
        raise HTTPException(
            409,
            "Sandbox container is not running and could not be started.",
        )


async def resolve_thread_git_backend(
    *,
    session: AsyncSession,
    thread_id: str,
    user: User,
) -> tuple[DockerBackend, str]:
    stmt = select(ThreadORM).where(
        ThreadORM.thread_id == thread_id,
        ThreadORM.user_id == user.identity,
    )
    thread = await session.scalar(stmt)
    if not thread:
        raise HTTPException(404, f"Thread '{thread_id}' not found")

    graph_id = await resolve_thread_graph_id(session, thread=thread)
    config_dict = create_thread_config(thread_id, user, {})
    configurable = config_dict.get("configurable", {})
    if not isinstance(configurable, dict):
        configurable = {}

    config = RunnableConfig(configurable=configurable)
    langgraph_service = get_langgraph_service()
    try:
        async with langgraph_service.get_graph(graph_id) as agent:
            snapshot = await agent.aget_state(config, subgraphs=False)
    except Exception as exc:
        raise HTTPException(
            500, f"Failed to load sandbox state for thread '{thread_id}': {exc}"
        ) from exc

    values = snapshot.values if snapshot and isinstance(snapshot.values, dict) else {}
    if not isinstance(values, dict):
        values = {}
    if not values:
        raise HTTPException(
            409,
            "Sandbox runtime state is empty. Please initialize the thread environment first.",
        )

    runtime_proxy = SimpleNamespace(
        state=values,
        config={"configurable": configurable},
        store=None,
    )
    backend = DockerBackend(runtime=runtime_proxy, workdir="/workspace")
    await ensure_backend_container_running(backend)
    return backend, graph_id


async def run_git_command(
    backend: DockerBackend,
    command: str,
    *,
    detail: str,
    allow_nonzero_exit: bool = False,
) -> tuple[int, str]:
    result = await backend.aexecute(command)
    exit_code = int(getattr(result, "exit_code", 1))
    output = str(getattr(result, "output", "") or "")
    if exit_code != 0 and not allow_nonzero_exit:
        excerpt, _ = truncate_text(output.strip(), max_chars=800)
        raise HTTPException(
            409,
            f"{detail} failed (exit_code={exit_code}). {excerpt or 'no output'}",
        )
    return exit_code, output


async def generate_commit_message_from_diff(staged_diff: str) -> str:
    diff_excerpt, _ = truncate_text(staged_diff, max_chars=GIT_DIFF_MODEL_MAX_CHARS)
    if not diff_excerpt.strip():
        raise HTTPException(
            409, "Cannot generate commit message from empty staged diff."
        )

    model = init_chat_model(
        model_provider=COMMIT_MESSAGE_MODEL_PROVIDER,
        model=COMMIT_MESSAGE_MODEL_NAME,
        temperature=0.1,
    )
    response = await model.ainvoke(
        [
            SystemMessage(
                content=(
                    "You generate concise git commit subjects. "
                    "Return exactly one line, plain text, no quotes, no markdown."
                )
            ),
            HumanMessage(
                content=(
                    "Based on this staged git diff, generate a commit message subject "
                    "in Conventional Commits style (max 72 chars preferred):\n\n"
                    f"{diff_excerpt}"
                )
            ),
        ]
    )
    raw_text = coerce_model_text(getattr(response, "content", ""))
    message = sanitize_commit_message(raw_text)
    if not message:
        raise HTTPException(500, "Model returned empty commit message.")
    return message


def build_pending_git_changes_response(
    *,
    thread_id: str,
    graph_id: str,
    include_diff: bool,
) -> dict[str, Any]:
    return {
        "thread_id": thread_id,
        "graph_id": graph_id,
        "files": [],
        "count": 0,
        "untracked_files": [],
        "diff": "" if include_diff else None,
        "diff_truncated": False,
        "pending_initialization": True,
        "timestamp": utc_now_iso_z(),
    }
