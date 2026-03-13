from __future__ import annotations

import asyncio
import json
import shlex
from collections.abc import AsyncGenerator
from contextlib import suppress
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

import docker
from aegra_api.api.runs import (
    _merge_jsonb,
    active_runs,
    execute_run_async,
    make_run_trace_context,
    resolve_assistant_id,
    set_thread_status,
    update_thread_metadata,
)
from aegra_api.core.auth_deps import get_current_user
from aegra_api.core.orm import Assistant as AssistantORM
from aegra_api.core.orm import Run as RunORM
from aegra_api.core.orm import RunEvent as RunEventORM
from aegra_api.core.orm import Thread as ThreadORM
from aegra_api.core.orm import _get_session_maker, get_session
from aegra_api.models.auth import User as AuthUser
from aegra_api.services.langgraph_service import (
    create_thread_config,
    get_langgraph_service,
)
from docker.errors import DockerException, NotFound
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.sandbox_bootstrap import (
    append_bootstrap_log,
    build_bootstrap_response,
    can_destroy_container_for_bootstrap_reset,
    default_bootstrap_steps,
    normalize_bootstrap_steps,
    normalize_stream_mode,
    persist_bootstrap_state,
    read_thread_and_bootstrap_state,
    snapshot_user_payload,
    utc_now_iso_z,
)
from app.services.sandbox_git import (
    GIT_DIFF_DEFAULT_MAX_CHARS,
    GIT_DIFF_MAX_CHARS_LIMIT,
    build_pending_git_changes_response,
    extract_graph_id_from_metadata,
    generate_commit_message_from_diff,
    parse_git_porcelain,
    resolve_thread_git_backend,
    resolve_thread_graph_id,
    run_git_command,
    sanitize_commit_message,
    truncate_text,
)
from middleware.docker import build_web_sandbox_docker_middleware

if TYPE_CHECKING:
    from aegra_api.models.auth import User

router = APIRouter()
BOOTSTRAP_TASKS: dict[str, asyncio.Task[None]] = {}


def _cancel_async_task_safely(task: asyncio.Task[Any] | Any) -> bool:
    """Best-effort cancel that tolerates cross-event-loop task ownership."""
    try:
        if task.done():
            return False
    except Exception:
        return False

    task_loop: asyncio.AbstractEventLoop | None = None
    with suppress(Exception):
        task_loop = task.get_loop()

    with suppress(RuntimeError):
        running_loop = asyncio.get_running_loop()
        if task_loop is None or task_loop is running_loop:
            task.cancel()
            return True

    if task_loop is None or task_loop.is_closed():
        return False

    with suppress(Exception):
        task_loop.call_soon_threadsafe(task.cancel)
        return True
    return False


class SandboxBootstrapRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    force: bool = Field(
        default=False,
        description="Retry even if there is an existing failed/running bootstrap state.",
    )
    stream_mode: str | list[str] | None = Field(
        default=None,
        description="Run stream mode to use for the first auto-submitted message.",
    )


class SandboxBootstrapResetRequest(BaseModel):
    destroy_container: bool = Field(
        default=True,
        description="Whether to destroy current sandbox container when resetting initialization state.",
    )


class SandboxThreadCommitRequest(BaseModel):
    message: str | None = Field(
        default=None,
        description="提交说明。为空时可启用 generate_message 由模型生成。",
        max_length=500,
    )
    generate_message: bool = Field(
        default=False,
        description="当 message 为空时，是否根据 staged diff 生成 commit message。",
    )


def _build_log_excerpt(
    service_status: dict[str, Any] | None,
    *,
    log_lines: int,
    errors_only: bool,
) -> dict[str, Any] | None:
    """从 service_status 里提取可直接展示的日志摘要。"""
    if not isinstance(service_status, dict):
        return None

    # 统一提取中间件写入的日志与错误行，避免前端自行解析大字段。
    error_lines = service_status.get("error_lines")
    log_tail = service_status.get("log_tail")

    excerpt: dict[str, Any] = {}
    if isinstance(error_lines, list):
        excerpt["error_lines"] = error_lines[:log_lines]

    if errors_only:
        return excerpt

    if isinstance(log_tail, str):
        lines = log_tail.splitlines()
        excerpt["log_tail_lines"] = lines[-log_lines:]
    return excerpt


def _get_safe_container_details(container_id: str) -> dict[str, Any] | None:
    """读取容器安全子集信息，避免暴露过多底层配置细节。"""
    try:
        client = docker.from_env()
        container = client.containers.get(container_id)
        # 主动刷新一次，避免读取到过期状态。
        container.reload()
    except (DockerException, NotFound):
        return None

    attrs = container.attrs if isinstance(container.attrs, dict) else {}
    state = attrs.get("State", {}) if isinstance(attrs.get("State"), dict) else {}
    config = attrs.get("Config", {}) if isinstance(attrs.get("Config"), dict) else {}
    network = (
        attrs.get("NetworkSettings", {})
        if isinstance(attrs.get("NetworkSettings"), dict)
        else {}
    )

    # 只返回调试最常用字段：生命周期、镜像、端口映射与重启次数。
    return {
        "id": container.id,
        "name": container.name,
        "image": config.get("Image"),
        "status": container.status,
        "created_at": attrs.get("Created"),
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
        "restart_count": attrs.get("RestartCount"),
        "running": state.get("Running"),
        "exit_code": state.get("ExitCode"),
        "ports": network.get("Ports", {}),
    }


def _extract_event_error_excerpt(event: str, data: dict[str, Any] | None) -> str | None:
    """从 run_event 中抽取可读错误摘要，优先返回最关键的错误信息。"""
    event_lower = event.lower()
    data_dict = data if isinstance(data, dict) else {}

    # 常见错误字段优先级：message > error > detail > exception
    for key in ("message", "error", "detail", "exception"):
        value = data_dict.get(key)
        if isinstance(value, str) and value.strip():
            return f"{event}: {value[:600]}"

    # 如果事件类型本身包含 error/fail 字样，也保留事件名用于定位。
    if "error" in event_lower or "fail" in event_lower:
        return f"{event}: {str(data_dict)[:600]}"

    return None


def _pick_preview_url(service_status: dict[str, Any] | None) -> str | None:
    """从运行态中选择最优预览 URL。

    选择策略：
    1. 优先返回 HTTP 探测为 2xx/3xx 的 URL
    2. 否则回退到首个可用 preview URL
    """
    if not isinstance(service_status, dict):
        return None

    preview_urls = service_status.get("preview_urls")
    probes = service_status.get("preview_probes")
    if not isinstance(preview_urls, list) or not preview_urls:
        return None

    if isinstance(probes, dict):
        for url in preview_urls:
            code = probes.get(url)
            if isinstance(code, str) and code.isdigit() and 200 <= int(code) < 400:
                return url
    return preview_urls[0]


def _is_runtime_state_initializing_error(exc: HTTPException) -> bool:
    detail = exc.detail
    if exc.status_code != 409 or not isinstance(detail, str):
        return False
    return detail.startswith("Sandbox runtime state is empty.")


async def _run_bootstrap_task(
    *,
    thread_id: str,
    graph_id: str,
    request_id: str,
    message: str,
    stream_mode: list[str],
    user_payload: dict[str, Any],
) -> None:
    session_maker = _get_session_maker()
    user = AuthUser.model_validate(user_payload)
    middleware = build_web_sandbox_docker_middleware()

    try:
        async with session_maker() as session:
            thread, _, _, state = await read_thread_and_bootstrap_state(
                session, thread_id=thread_id, user_id=user.identity
            )
            if not thread:
                return
            if state.get("request_id") != request_id:
                return

            append_bootstrap_log(state, level="info", message="开始初始化执行环境。")
            await persist_bootstrap_state(
                session, thread=thread, graph_id=graph_id, state=state
            )

            loop = asyncio.get_running_loop()
            progress_queue: asyncio.Queue[tuple[str | None, str, str]] = asyncio.Queue()
            progress_flush_stop = asyncio.Event()

            async def _persist_progress_batch(
                batch: list[tuple[str | None, str, str]],
            ) -> None:
                if not batch:
                    return
                async with session_maker() as progress_session:
                    (
                        progress_thread,
                        _,
                        _,
                        progress_state,
                    ) = await read_thread_and_bootstrap_state(
                        progress_session,
                        thread_id=thread_id,
                        user_id=user.identity,
                    )
                    if not progress_thread:
                        return
                    if progress_state.get("request_id") != request_id:
                        return

                    for step_key, log_level, log_message in batch:
                        append_bootstrap_log(
                            progress_state,
                            level=log_level,
                            message=log_message,
                            step=step_key,
                        )

                    await persist_bootstrap_state(
                        progress_session,
                        thread=progress_thread,
                        graph_id=graph_id,
                        state=progress_state,
                    )

            async def _flush_progress_logs() -> None:
                pending_batch: list[tuple[str | None, str, str]] = []
                while True:
                    item: tuple[str | None, str, str] | None = None
                    with suppress(TimeoutError):
                        item = await asyncio.wait_for(progress_queue.get(), timeout=0.4)

                    if item is not None:
                        pending_batch.append(item)
                        with suppress(asyncio.QueueEmpty):
                            while True:
                                pending_batch.append(progress_queue.get_nowait())

                    if pending_batch:
                        batch = pending_batch
                        pending_batch = []
                        with suppress(Exception):
                            await _persist_progress_batch(batch)

                    if progress_flush_stop.is_set() and progress_queue.empty():
                        break

            def _report_progress(step: str, level: str, message_text: str) -> None:
                normalized_message = str(message_text).strip()
                if not normalized_message:
                    return

                normalized_level = (
                    level.strip().lower() if isinstance(level, str) else "info"
                )
                if normalized_level not in {"info", "warning", "error", "debug"}:
                    normalized_level = "info"

                normalized_step = (
                    step.strip() if isinstance(step, str) and step.strip() else None
                )
                with suppress(RuntimeError):
                    loop.call_soon_threadsafe(
                        progress_queue.put_nowait,
                        (normalized_step, normalized_level, normalized_message[:2000]),
                    )

            progress_flusher = asyncio.create_task(_flush_progress_logs())

            config_dict = create_thread_config(thread_id, user, {})
            configurable = config_dict.get("configurable", {})
            if not isinstance(configurable, dict):
                configurable = {}
            config = RunnableConfig(configurable=configurable)
            runtime_proxy = SimpleNamespace(
                config={"configurable": configurable},
                store=None,
            )

            init_result: dict[str, Any]
            try:
                langgraph_service = get_langgraph_service()
                async with langgraph_service.get_graph(graph_id) as agent:
                    snapshot = await agent.aget_state(config, subgraphs=False)
                    values = (
                        snapshot.values
                        if snapshot and isinstance(snapshot.values, dict)
                        else {}
                    )
                    if not isinstance(values, dict):
                        values = {}

                    init_result = await middleware.ainitialize_environment(
                        state=values,
                        runtime=runtime_proxy,
                        progress_reporter=_report_progress,
                    )

                    updates = init_result.get("updates")
                    if isinstance(updates, dict) and updates:
                        await agent.aupdate_state(config, updates)
            finally:
                progress_flush_stop.set()
                await progress_flusher

            thread, _, _, state = await read_thread_and_bootstrap_state(
                session, thread_id=thread_id, user_id=user.identity
            )
            if not thread or state.get("request_id") != request_id:
                return

            state["steps"] = normalize_bootstrap_steps(init_result.get("steps"))
            init_success = bool(init_result.get("success"))
            init_error = init_result.get("error")

            if not init_success:
                message_text = (
                    init_error.strip()
                    if isinstance(init_error, str) and init_error.strip()
                    else "环境初始化失败"
                )
                state["status"] = "error"
                state["error"] = message_text
                state["finished_at"] = utc_now_iso_z()
                append_bootstrap_log(state, level="error", message=message_text)
                await persist_bootstrap_state(
                    session, thread=thread, graph_id=graph_id, state=state
                )
                return

            append_bootstrap_log(
                state, level="info", message="环境初始化完成，准备提交首条消息。"
            )
            state["error"] = None
            await persist_bootstrap_state(
                session, thread=thread, graph_id=graph_id, state=state
            )

            run = await _create_bootstrap_run(
                thread_id=thread_id,
                user=user,
                session=session,
                graph_id=graph_id,
                message=message,
                stream_mode=stream_mode,
            )

            thread, _, _, state = await read_thread_and_bootstrap_state(
                session, thread_id=thread_id, user_id=user.identity
            )
            if not thread or state.get("request_id") != request_id:
                return

            state["status"] = "success"
            state["run_id"] = run.run_id
            state["run_status"] = run.status
            state["finished_at"] = utc_now_iso_z()
            append_bootstrap_log(
                state,
                level="info",
                message=f"首条消息已提交（run_id={run.run_id}）。",
            )
            await persist_bootstrap_state(
                session, thread=thread, graph_id=graph_id, state=state
            )
    except Exception as exc:
        async with session_maker() as session:
            thread, _, _, state = await read_thread_and_bootstrap_state(
                session, thread_id=thread_id, user_id=user.identity
            )
            if thread and state.get("request_id") == request_id:
                state["status"] = "error"
                state["error"] = f"环境初始化任务异常：{exc}"
                state["finished_at"] = utc_now_iso_z()
                append_bootstrap_log(
                    state,
                    level="error",
                    message=f"环境初始化任务异常：{exc}",
                )
                await persist_bootstrap_state(
                    session,
                    thread=thread,
                    graph_id=graph_id,
                    state=state,
                )
    finally:
        task = BOOTSTRAP_TASKS.get(thread_id)
        if task is not None and task.done():
            BOOTSTRAP_TASKS.pop(thread_id, None)


async def _run_bootstrap_execute_task(
    *,
    run_id: str,
    thread_id: str,
    graph_id: str,
    user: User,
    config: dict[str, Any],
    context: dict[str, Any],
    input_data: dict[str, Any],
    stream_mode: list[str],
) -> None:
    """Run bootstrap-created execution with a task-scoped session bound on this loop."""

    session_maker = _get_session_maker()
    run_session = session_maker()
    try:
        # Pre-bind a connection on the current event loop to avoid reusing a
        # pooled asyncpg connection that was created on a different loop.
        await run_session.connection()
        await execute_run_async(
            run_id=run_id,
            thread_id=thread_id,
            graph_id=graph_id,
            input_data=input_data,
            user=user,
            config=config,
            context=context,
            stream_mode=stream_mode,
            session=run_session,
            checkpoint=None,
            command=None,
            interrupt_before=None,
            interrupt_after=None,
            _multitask_strategy=None,
            subgraphs=False,
        )
    finally:
        await run_session.close()


async def _create_bootstrap_run(
    *,
    thread_id: str,
    user: User,
    session: AsyncSession,
    graph_id: str,
    message: str,
    stream_mode: list[str],
) -> RunORM:
    """Create the first bootstrap run without routing through create_run()."""

    langgraph_service = get_langgraph_service()
    available_graphs = langgraph_service.list_graphs()
    resolved_assistant_id = resolve_assistant_id(graph_id, available_graphs)

    assistant_stmt = select(AssistantORM).where(
        AssistantORM.assistant_id == resolved_assistant_id
    )
    assistant = await session.scalar(assistant_stmt)
    if not assistant:
        raise HTTPException(404, f"Assistant '{graph_id}' not found")

    config = _merge_jsonb(assistant.config, {})
    context = _merge_jsonb(assistant.context, {})
    input_data = {"messages": [{"type": "human", "content": message}]}

    await update_thread_metadata(
        session,
        thread_id,
        assistant.assistant_id,
        assistant.graph_id,
        user.identity,
    )
    await set_thread_status(session, thread_id, "busy")

    run_id = str(uuid4())
    now = datetime.now(UTC)
    run = RunORM(
        run_id=run_id,
        thread_id=thread_id,
        assistant_id=resolved_assistant_id,
        status="pending",
        input=input_data,
        config=config,
        context=context,
        user_id=user.identity,
        created_at=now,
        updated_at=now,
        output=None,
        error_message=None,
    )
    session.add(run)
    await session.commit()

    task = asyncio.create_task(
        _run_bootstrap_execute_task(
            run_id=run_id,
            thread_id=thread_id,
            graph_id=assistant.graph_id,
            user=user,
            config=config,
            context=context,
            input_data=input_data,
            stream_mode=stream_mode,
        ),
        context=make_run_trace_context(
            run_id,
            thread_id,
            assistant.graph_id,
            user.identity,
        ),
    )
    active_runs[run_id] = task
    return run


async def _fetch_recent_run_events(
    session: AsyncSession,
    *,
    run_id: str,
    events_limit: int,
) -> list[dict[str, Any]]:
    """查询单个 run 最近事件并提炼错误信息。"""
    stmt = (
        select(RunEventORM)
        .where(RunEventORM.run_id == run_id)
        .order_by(RunEventORM.seq.desc())
        .limit(events_limit)
    )
    rows = (await session.scalars(stmt)).all()

    # 先按倒序查，再翻转成时间正序，方便前端按时间阅读。
    events = list(reversed(rows))
    result: list[dict[str, Any]] = []
    for row in events:
        excerpt = _extract_event_error_excerpt(row.event, row.data)
        result.append(
            {
                "id": row.id,
                "seq": row.seq,
                "event": row.event,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "error_excerpt": excerpt,
            }
        )
    return result


def _format_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {body}\n\n"


@router.get("/sandbox/threads/{thread_id}/git/unstaged")
async def get_sandbox_thread_git_unstaged_changes(
    thread_id: str,
    include_diff: bool = Query(
        True,
        description="Whether to include unstaged unified diff.",
    ),
    diff_max_chars: int = Query(
        GIT_DIFF_DEFAULT_MAX_CHARS,
        ge=0,
        le=GIT_DIFF_MAX_CHARS_LIMIT,
        description=(
            "Max chars for diff payload before truncation. "
            "Set to 0 to disable truncation."
        ),
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        backend, graph_id = await resolve_thread_git_backend(
            session=session,
            thread_id=thread_id,
            user=user,
        )
    except HTTPException as exc:
        if _is_runtime_state_initializing_error(exc):
            thread = await session.scalar(
                select(ThreadORM).where(
                    ThreadORM.thread_id == thread_id,
                    ThreadORM.user_id == user.identity,
                )
            )
            if thread is None:
                raise exc
            graph_id = await resolve_thread_graph_id(
                session,
                thread=thread,
            )
            return build_pending_git_changes_response(
                thread_id=thread_id,
                graph_id=graph_id,
                include_diff=include_diff,
            )
        raise
    _, status_output = await run_git_command(
        backend,
        "git -C /workspace status --porcelain=1 --untracked-files=all",
        detail="read git status",
    )
    entries = parse_git_porcelain(status_output)
    unstaged_entries = [item for item in entries if item.get("is_unstaged")]
    untracked_files = [
        item.get("path")
        for item in unstaged_entries
        if item.get("status") == "??" and isinstance(item.get("path"), str)
    ]

    diff_text = ""
    diff_truncated = False
    if include_diff:
        _, raw_diff = await run_git_command(
            backend,
            "git -C /workspace diff --no-ext-diff",
            detail="read unstaged diff",
        )
        merged_diff = raw_diff
        for file_path in untracked_files:
            quoted_file = shlex.quote(file_path)
            _, untracked_diff = await run_git_command(
                backend,
                (
                    "git -C /workspace diff --no-index --no-ext-diff -- /dev/null "
                    f"{quoted_file}"
                ),
                detail=f"read untracked file diff: {file_path}",
                allow_nonzero_exit=True,
            )
            if untracked_diff.strip():
                merged_diff = f"{merged_diff.rstrip()}\n{untracked_diff.lstrip()}\n"

        diff_text, diff_truncated = truncate_text(
            merged_diff,
            max_chars=diff_max_chars,
        )

    return {
        "thread_id": thread_id,
        "graph_id": graph_id,
        "files": unstaged_entries,
        "count": len(unstaged_entries),
        "untracked_files": untracked_files,
        "diff": diff_text if include_diff else None,
        "diff_truncated": diff_truncated if include_diff else False,
        "timestamp": utc_now_iso_z(),
    }


@router.get("/sandbox/threads/{thread_id}/git/staged")
async def get_sandbox_thread_git_staged_changes(
    thread_id: str,
    include_diff: bool = Query(
        True,
        description="Whether to include staged unified diff.",
    ),
    diff_max_chars: int = Query(
        GIT_DIFF_DEFAULT_MAX_CHARS,
        ge=0,
        le=GIT_DIFF_MAX_CHARS_LIMIT,
        description=(
            "Max chars for diff payload before truncation. "
            "Set to 0 to disable truncation."
        ),
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        backend, graph_id = await resolve_thread_git_backend(
            session=session,
            thread_id=thread_id,
            user=user,
        )
    except HTTPException as exc:
        if _is_runtime_state_initializing_error(exc):
            thread = await session.scalar(
                select(ThreadORM).where(
                    ThreadORM.thread_id == thread_id,
                    ThreadORM.user_id == user.identity,
                )
            )
            if thread is None:
                raise exc
            graph_id = await resolve_thread_graph_id(
                session,
                thread=thread,
            )
            return build_pending_git_changes_response(
                thread_id=thread_id,
                graph_id=graph_id,
                include_diff=include_diff,
            )
        raise
    _, status_output = await run_git_command(
        backend,
        "git -C /workspace status --porcelain=1 --untracked-files=all",
        detail="read git status",
    )
    entries = parse_git_porcelain(status_output)
    staged_entries = [item for item in entries if item.get("is_staged")]

    diff_text = ""
    diff_truncated = False
    if include_diff:
        _, raw_diff = await run_git_command(
            backend,
            "git -C /workspace diff --cached --no-ext-diff",
            detail="read staged diff",
        )
        diff_text, diff_truncated = truncate_text(raw_diff, max_chars=diff_max_chars)

    return {
        "thread_id": thread_id,
        "graph_id": graph_id,
        "files": staged_entries,
        "count": len(staged_entries),
        "diff": diff_text if include_diff else None,
        "diff_truncated": diff_truncated if include_diff else False,
        "timestamp": utc_now_iso_z(),
    }


@router.post("/sandbox/threads/{thread_id}/git/commit")
async def commit_sandbox_thread_git_changes(
    thread_id: str,
    payload: SandboxThreadCommitRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    backend, graph_id = await resolve_thread_git_backend(
        session=session,
        thread_id=thread_id,
        user=user,
    )

    _, status_output = await run_git_command(
        backend,
        "git -C /workspace status --porcelain=1 --untracked-files=all",
        detail="read git status",
    )
    entries = parse_git_porcelain(status_output)
    staged_entries = [item for item in entries if item.get("is_staged")]
    if not staged_entries:
        raise HTTPException(409, "No staged changes to commit.")

    _, staged_diff = await run_git_command(
        backend,
        "git -C /workspace diff --cached --no-ext-diff",
        detail="read staged diff",
    )

    message_source = "user"
    resolved_message = (
        payload.message.strip() if isinstance(payload.message, str) else ""
    )
    if not resolved_message:
        if not payload.generate_message:
            raise HTTPException(
                400,
                "Commit message is required when generate_message is false.",
            )
        resolved_message = await generate_commit_message_from_diff(staged_diff)
        message_source = "model"

    commit_message = sanitize_commit_message(resolved_message)
    if not commit_message:
        raise HTTPException(400, "Commit message cannot be empty.")

    _, commit_output = await run_git_command(
        backend,
        f"git -C /workspace commit -m {shlex.quote(commit_message)}",
        detail="git commit",
    )
    _, commit_id_output = await run_git_command(
        backend,
        "git -C /workspace rev-parse HEAD",
        detail="read commit id",
    )

    commit_id = commit_id_output.strip().splitlines()[0] if commit_id_output else ""
    if not commit_id:
        raise HTTPException(500, "Commit succeeded but failed to read commit id.")

    _, head_subject_output = await run_git_command(
        backend,
        "git -C /workspace show -s --format=%s HEAD",
        detail="read commit subject",
    )
    head_subject = (
        head_subject_output.strip().splitlines()[0] if head_subject_output else ""
    )

    _, latest_status_output = await run_git_command(
        backend,
        "git -C /workspace status --porcelain=1 --untracked-files=all",
        detail="read git status",
    )
    latest_entries = parse_git_porcelain(latest_status_output)
    staged_remaining = len([item for item in latest_entries if item.get("is_staged")])
    unstaged_remaining = len(
        [item for item in latest_entries if item.get("is_unstaged")]
    )

    commit_output_excerpt, commit_output_truncated = truncate_text(
        commit_output,
        max_chars=4_000,
    )
    return {
        "thread_id": thread_id,
        "graph_id": graph_id,
        "commit_id": commit_id,
        "commit_message": head_subject or commit_message,
        "message_source": message_source,
        "staged_count_before_commit": len(staged_entries),
        "staged_count_after_commit": staged_remaining,
        "unstaged_count_after_commit": unstaged_remaining,
        "commit_output": commit_output_excerpt,
        "commit_output_truncated": commit_output_truncated,
        "timestamp": utc_now_iso_z(),
    }


@router.get("/sandbox/threads/{thread_id}/runtime")
async def get_sandbox_runtime(
    thread_id: str,
    include_state_values: bool = Query(
        False, description="Whether to include raw LangGraph state values"
    ),
    log_lines: int = Query(
        80,
        ge=20,
        le=500,
        description="Number of log lines to include in runtime excerpt",
    ),
    errors_only: bool = Query(
        False,
        description="Only return error lines in runtime excerpt",
    ),
    include_container_details: bool = Query(
        False,
        description="Include a safe subset of docker container inspect details",
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    # 先确认线程归属，防止跨用户读取运行状态。
    stmt = select(ThreadORM).where(
        ThreadORM.thread_id == thread_id,
        ThreadORM.user_id == user.identity,
    )
    thread = await session.scalar(stmt)
    if not thread:
        raise HTTPException(404, f"Thread '{thread_id}' not found")

    graph_id = await resolve_thread_graph_id(session, thread=thread)
    metadata = thread.metadata_json if isinstance(thread.metadata_json, dict) else {}
    if extract_graph_id_from_metadata(metadata) is None:
        metadata = {**metadata, "graph_id": graph_id}
        thread.metadata_json = metadata
        await session.commit()

    config_dict = create_thread_config(thread_id, user, {})
    langgraph_service = get_langgraph_service()

    try:
        # 从 LangGraph 最新 checkpoint 读取中间件写入的 service_status。
        async with langgraph_service.get_graph(graph_id) as agent:
            config = RunnableConfig(configurable=config_dict.get("configurable", {}))
            agent = agent.with_config(config)
            snapshot = await agent.aget_state(config, subgraphs=False)
    except Exception as exc:
        raise HTTPException(
            500, f"Failed to read runtime state for thread '{thread_id}': {exc}"
        ) from exc

    if not snapshot:
        return {
            "thread_id": thread_id,
            "graph_id": graph_id,
            "status": "no_state",
            "service_status": None,
            "container_id": None,
        }

    values = snapshot.values if isinstance(snapshot.values, dict) else {}
    if not isinstance(values, dict):
        values = {}

    configurable = snapshot.config.get("configurable", {})
    checkpoint_id = (
        configurable.get("checkpoint_id") if isinstance(configurable, dict) else None
    )

    response: dict[str, Any] = {
        "thread_id": thread_id,
        "graph_id": graph_id,
        "status": "ok",
        "checkpoint_id": checkpoint_id,
        "container_id": values.get("container_id"),
        "service_bootstrapped": values.get("service_bootstrapped"),
        "service_restart_count": values.get("service_restart_count"),
        "last_diagnostic_fingerprint": values.get("last_diagnostic_fingerprint"),
        "service_status": values.get("service_status"),
    }
    # 给前端直接可消费的日志摘要，避免传输整段超长 log_tail。
    response["runtime_excerpt"] = _build_log_excerpt(
        response.get("service_status"),
        log_lines=log_lines,
        errors_only=errors_only,
    )

    # 可选返回容器安全信息，便于定位容器状态与端口映射异常。
    if include_container_details and isinstance(response.get("container_id"), str):
        response["container_details"] = _get_safe_container_details(
            response["container_id"]
        )
        response["runtime_timestamp"] = utc_now_iso_z()

    if include_state_values:
        response["state_values"] = values
    return response


@router.post("/sandbox/threads/{thread_id}/initialize")
async def initialize_sandbox_thread_environment(
    thread_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """显式初始化线程沙盒环境（容器、拉代码、依赖安装）。"""

    stmt = select(ThreadORM).where(
        ThreadORM.thread_id == thread_id,
        ThreadORM.user_id == user.identity,
    )
    thread = await session.scalar(stmt)
    if not thread:
        raise HTTPException(404, f"Thread '{thread_id}' not found")

    graph_id = await resolve_thread_graph_id(session, thread=thread)
    metadata = thread.metadata_json if isinstance(thread.metadata_json, dict) else {}
    if extract_graph_id_from_metadata(metadata) is None:
        metadata = {**metadata, "graph_id": graph_id}
        thread.metadata_json = metadata
        await session.commit()

    config_dict = create_thread_config(thread_id, user, {})
    configurable = config_dict.get("configurable", {})
    if not isinstance(configurable, dict):
        configurable = {}

    config = RunnableConfig(configurable=configurable)
    runtime_proxy = SimpleNamespace(
        config={"configurable": configurable},
        store=None,
    )
    middleware = build_web_sandbox_docker_middleware()

    try:
        langgraph_service = get_langgraph_service()
        async with langgraph_service.get_graph(graph_id) as agent:
            snapshot = await agent.aget_state(config, subgraphs=False)
            values = (
                snapshot.values
                if snapshot and isinstance(snapshot.values, dict)
                else {}
            )
            if not isinstance(values, dict):
                values = {}

            init_result = await middleware.ainitialize_environment(
                state=values,
                runtime=runtime_proxy,
            )

            updates = init_result.get("updates")
            if isinstance(updates, dict) and updates:
                await agent.aupdate_state(config, updates)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            500,
            f"Failed to initialize sandbox environment for thread '{thread_id}': {exc}",
        ) from exc

    success = bool(init_result.get("success"))
    return {
        "thread_id": thread_id,
        "graph_id": graph_id,
        "status": "ok" if success else "error",
        "success": success,
        "error": init_result.get("error"),
        "steps": init_result.get("steps") or [],
        "container_id": init_result.get("container_id"),
        "service_status": init_result.get("service_status"),
        "runtime_timestamp": utc_now_iso_z(),
    }


@router.post("/sandbox/threads/{thread_id}/bootstrap")
async def start_sandbox_thread_bootstrap(
    thread_id: str,
    payload: SandboxBootstrapRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """异步初始化线程环境并由后端自动提交首条消息。"""

    thread, graph_id, _, bootstrap_state = await read_thread_and_bootstrap_state(
        session,
        thread_id=thread_id,
        user_id=user.identity,
    )
    if not thread:
        raise HTTPException(404, f"Thread '{thread_id}' not found")

    active_task = BOOTSTRAP_TASKS.get(thread_id)
    if active_task is not None and active_task.done():
        BOOTSTRAP_TASKS.pop(thread_id, None)
        active_task = None

    if not payload.force and active_task is not None:
        return build_bootstrap_response(
            thread_id=thread_id,
            graph_id=graph_id,
            state=bootstrap_state,
            accepted=False,
        )

    if not payload.force and bootstrap_state.get("status") == "running":
        return build_bootstrap_response(
            thread_id=thread_id,
            graph_id=graph_id,
            state=bootstrap_state,
            accepted=False,
        )

    request_id = str(uuid4())
    normalized_stream_mode = normalize_stream_mode(payload.stream_mode)
    now = utc_now_iso_z()
    next_state: dict[str, Any] = {
        "request_id": request_id,
        "status": "running",
        "steps": default_bootstrap_steps(),
        "logs": [],
        "events": [],
        "event_seq": 0,
        "error": None,
        "run_id": None,
        "run_status": None,
        "started_at": now,
        "updated_at": now,
        "finished_at": None,
    }
    append_bootstrap_log(next_state, level="info", message="已接收环境初始化任务。")
    await persist_bootstrap_state(
        session, thread=thread, graph_id=graph_id, state=next_state
    )

    if active_task is not None:
        _cancel_async_task_safely(active_task)

    task = asyncio.create_task(
        _run_bootstrap_task(
            thread_id=thread_id,
            graph_id=graph_id,
            request_id=request_id,
            message=payload.message.strip(),
            stream_mode=normalized_stream_mode,
            user_payload=snapshot_user_payload(user),
        )
    )
    BOOTSTRAP_TASKS[thread_id] = task
    task.add_done_callback(lambda _task: BOOTSTRAP_TASKS.pop(thread_id, None))

    return build_bootstrap_response(
        thread_id=thread_id,
        graph_id=graph_id,
        state=next_state,
        accepted=True,
    )


@router.get("/sandbox/threads/{thread_id}/bootstrap")
async def get_sandbox_thread_bootstrap_status(
    thread_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """获取线程环境初始化任务状态（支持前端重连恢复）。"""

    thread, graph_id, _, bootstrap_state = await read_thread_and_bootstrap_state(
        session,
        thread_id=thread_id,
        user_id=user.identity,
    )
    if not thread:
        raise HTTPException(404, f"Thread '{thread_id}' not found")

    active_task = BOOTSTRAP_TASKS.get(thread_id)
    if active_task is not None and active_task.done():
        BOOTSTRAP_TASKS.pop(thread_id, None)
        active_task = None

    if bootstrap_state.get("status") == "running" and active_task is None:
        bootstrap_state["status"] = "error"
        bootstrap_state["error"] = "环境初始化任务已中断，请重试。"
        bootstrap_state["finished_at"] = utc_now_iso_z()
        append_bootstrap_log(
            bootstrap_state,
            level="error",
            message="后台任务不存在，可能因服务重启中断。",
        )
        await persist_bootstrap_state(
            session,
            thread=thread,
            graph_id=graph_id,
            state=bootstrap_state,
        )

    run_id = bootstrap_state.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        run_status_stmt = select(RunORM.status).where(
            RunORM.run_id == run_id,
            RunORM.thread_id == thread_id,
            RunORM.user_id == user.identity,
        )
        run_status = await session.scalar(run_status_stmt)
        if isinstance(run_status, str) and run_status.strip():
            bootstrap_state["run_status"] = run_status

    return build_bootstrap_response(
        thread_id=thread_id,
        graph_id=graph_id,
        state=bootstrap_state,
    )


@router.post("/sandbox/threads/{thread_id}/cancel")
async def cancel_sandbox_thread(
    thread_id: str,
    action: Literal["cancel", "interrupt"] = Query(
        "cancel",
        description="Cancel strategy for active runs. Accepts: cancel, interrupt",
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """按线程维度取消活跃任务，用于 run_id 丢失时的兜底恢复。"""

    thread, graph_id, _, bootstrap_state = await read_thread_and_bootstrap_state(
        session,
        thread_id=thread_id,
        user_id=user.identity,
    )
    if not thread:
        raise HTTPException(404, f"Thread '{thread_id}' not found")

    active_runs_stmt = (
        select(RunORM)
        .where(
            RunORM.thread_id == thread_id,
            RunORM.user_id == user.identity,
            RunORM.status.in_(["pending", "running"]),
        )
        .order_by(RunORM.created_at.desc())
    )
    active_run_rows = (await session.scalars(active_runs_stmt)).all()

    cancelled_run_ids: list[str] = []
    for run in active_run_rows:
        run.status = "interrupted"
        if hasattr(run, "error_message"):
            run.error_message = (
                "Interrupted by thread-level cancel endpoint "
                f"(action={action}, at={utc_now_iso_z()})."
            )
        cancelled_run_ids.append(run.run_id)

    cancel_signal_failures: list[str] = []
    for run in active_run_rows:
        task = active_runs.get(run.run_id)
        if task is None:
            continue
        if not _cancel_async_task_safely(task):
            cancel_signal_failures.append(run.run_id)

    bootstrap_task_cancelled = False
    active_task = BOOTSTRAP_TASKS.pop(thread_id, None)
    if active_task is not None:
        bootstrap_task_cancelled = _cancel_async_task_safely(active_task)

    if bootstrap_state.get("status") == "running":
        now = utc_now_iso_z()
        bootstrap_state["status"] = "idle"
        bootstrap_state["error"] = "已通过线程级取消接口中断当前初始化任务。"
        bootstrap_state["finished_at"] = now
        append_bootstrap_log(
            bootstrap_state,
            level="warning",
            message=f"收到线程取消请求，action={action}，已中断初始化任务。",
        )
        await persist_bootstrap_state(
            session,
            thread=thread,
            graph_id=graph_id,
            state=bootstrap_state,
        )
    else:
        await session.commit()

    thread.status = "idle"
    await session.commit()

    return {
        "thread_id": thread_id,
        "action": action,
        "cancelled_run_ids": cancelled_run_ids,
        "cancelled_run_count": len(cancelled_run_ids),
        "cancel_signal_failures": cancel_signal_failures,
        "bootstrap_task_cancelled": bootstrap_task_cancelled,
        "thread_status": thread.status,
        "timestamp": utc_now_iso_z(),
    }


@router.post("/sandbox/threads/{thread_id}/bootstrap/reset")
async def reset_sandbox_thread_bootstrap(
    thread_id: str,
    payload: SandboxBootstrapResetRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """重置线程环境初始化状态，可选销毁当前容器。"""

    thread, graph_id, _, bootstrap_state = await read_thread_and_bootstrap_state(
        session,
        thread_id=thread_id,
        user_id=user.identity,
    )
    if not thread:
        raise HTTPException(404, f"Thread '{thread_id}' not found")

    if payload.destroy_container and not can_destroy_container_for_bootstrap_reset(
        bootstrap_state
    ):
        raise HTTPException(
            409,
            "Only allowed to reset container when container creation or repository sync failed.",
        )

    active_task = BOOTSTRAP_TASKS.pop(thread_id, None)
    if active_task is not None:
        _cancel_async_task_safely(active_task)

    now = utc_now_iso_z()
    reset_state: dict[str, Any] = {
        "status": "idle",
        "steps": default_bootstrap_steps(),
        "logs": [],
        "events": [],
        "event_seq": 0,
        "error": None,
        "request_id": None,
        "run_id": None,
        "run_status": None,
        "started_at": None,
        "updated_at": now,
        "finished_at": now,
    }
    append_bootstrap_log(
        reset_state,
        level="info",
        message="环境初始化已重置，可重新执行初始化。",
    )
    await persist_bootstrap_state(
        session,
        thread=thread,
        graph_id=graph_id,
        state=reset_state,
    )

    config_dict = create_thread_config(thread_id, user, {})
    configurable = config_dict.get("configurable", {})
    if not isinstance(configurable, dict):
        configurable = {}

    config = RunnableConfig(configurable=configurable)
    middleware = build_web_sandbox_docker_middleware()

    reset_result: dict[str, Any] = {}
    try:
        langgraph_service = get_langgraph_service()
        async with langgraph_service.get_graph(graph_id) as agent:
            snapshot = await agent.aget_state(config, subgraphs=False)
            values = (
                snapshot.values
                if snapshot and isinstance(snapshot.values, dict)
                else {}
            )
            if not isinstance(values, dict):
                values = {}

            reset_result = await middleware.areset_environment(
                state=values,
                destroy_container=payload.destroy_container,
            )

            updates = reset_result.get("updates")
            if isinstance(updates, dict) and updates:
                await agent.aupdate_state(config, updates)

            reset_error = reset_result.get("error")
            if isinstance(reset_error, str) and reset_error.strip():
                reset_state["error"] = reset_error.strip()
                append_bootstrap_log(
                    reset_state,
                    level="error",
                    message=f"环境重置失败：{reset_error.strip()}",
                )
                await persist_bootstrap_state(
                    session,
                    thread=thread,
                    graph_id=graph_id,
                    state=reset_state,
                )
    except Exception as exc:
        raise HTTPException(
            500,
            f"Failed to reset sandbox environment for thread '{thread_id}': {exc}",
        ) from exc

    response = build_bootstrap_response(
        thread_id=thread_id,
        graph_id=graph_id,
        state=reset_state,
    )
    response["reset_success"] = bool(reset_result.get("success", True))
    response["reset_error"] = reset_result.get("error")
    response["destroy_container"] = payload.destroy_container
    response["destroyed_container_id"] = reset_result.get("destroyed_container_id")
    return response


@router.get("/sandbox/threads/{thread_id}/bootstrap/stream")
async def stream_sandbox_thread_bootstrap_status(
    thread_id: str,
    request: Request,
    from_seq: int = Query(
        0,
        ge=0,
        description="Resume streaming from this event seq (inclusive resume cursor)",
    ),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """SSE 流式返回 bootstrap 日志与状态快照，支持重连续传。"""

    session_maker = _get_session_maker()
    initial_seq = max(0, from_seq)

    async def _event_stream() -> AsyncGenerator[str, None]:
        current_seq = initial_seq
        last_snapshot_signature: str | None = None

        while True:
            if await request.is_disconnected():
                break

            async with session_maker() as stream_session:
                (
                    thread,
                    graph_id,
                    _,
                    bootstrap_state,
                ) = await read_thread_and_bootstrap_state(
                    stream_session,
                    thread_id=thread_id,
                    user_id=user.identity,
                )

            if not thread:
                yield _format_sse_event(
                    "bootstrap_error",
                    {
                        "thread_id": thread_id,
                        "error": "thread_not_found",
                        "message": f"Thread '{thread_id}' not found",
                    },
                )
                break

            events = bootstrap_state.get("events")
            if isinstance(events, list):
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    seq = event.get("seq")
                    if not isinstance(seq, int):
                        continue
                    if seq <= current_seq:
                        continue
                    current_seq = seq
                    yield _format_sse_event("bootstrap_event", event)

            snapshot = build_bootstrap_response(
                thread_id=thread_id,
                graph_id=graph_id,
                state=bootstrap_state,
            )
            snapshot_signature = "|".join(
                [
                    str(snapshot.get("status") or ""),
                    str(snapshot.get("updated_at") or ""),
                    str(snapshot.get("run_status") or ""),
                    str(snapshot.get("event_seq") or ""),
                ]
            )
            if snapshot_signature != last_snapshot_signature:
                yield _format_sse_event("bootstrap_snapshot", snapshot)
                last_snapshot_signature = snapshot_signature

            terminal_status = snapshot.get("status")
            event_seq = snapshot.get("event_seq")
            if (
                terminal_status in {"success", "error", "idle"}
                and isinstance(event_seq, int)
                and current_seq >= event_seq
            ):
                yield _format_sse_event(
                    "bootstrap_done",
                    {
                        "thread_id": thread_id,
                        "status": terminal_status,
                        "event_seq": current_seq,
                    },
                )
                break

            await asyncio.sleep(0.7)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sandbox/threads/{thread_id}/debug")
async def get_sandbox_debug_bundle(
    thread_id: str,
    runs_limit: int = Query(
        5,
        ge=1,
        le=20,
        description="How many recent runs to include",
    ),
    events_limit: int = Query(
        10,
        ge=1,
        le=50,
        description="How many recent events per run to include",
    ),
    log_lines: int = Query(
        80,
        ge=20,
        le=500,
        description="Number of log lines in runtime excerpt",
    ),
    errors_only: bool = Query(
        False,
        description="Only return error lines in runtime excerpt",
    ),
    include_container_details: bool = Query(
        False,
        description="Include safe container inspect subset",
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    # 1) 校验线程归属，防止跨用户读取敏感调试信息。
    thread_stmt = select(ThreadORM).where(
        ThreadORM.thread_id == thread_id,
        ThreadORM.user_id == user.identity,
    )
    thread = await session.scalar(thread_stmt)
    if not thread:
        raise HTTPException(404, f"Thread '{thread_id}' not found")

    # 2) 复用 runtime 接口，统一运行态结构，避免两套实现漂移。
    runtime = await get_sandbox_runtime(
        thread_id=thread_id,
        include_state_values=False,
        log_lines=log_lines,
        errors_only=errors_only,
        include_container_details=include_container_details,
        user=user,
        session=session,
    )

    # 3) 拉取最近 runs，并附带每个 run 的事件错误摘要，便于快速定位失败链路。
    runs_stmt = (
        select(RunORM)
        .where(
            RunORM.thread_id == thread_id,
            RunORM.user_id == user.identity,
        )
        .order_by(RunORM.created_at.desc())
        .limit(runs_limit)
    )
    run_rows = (await session.scalars(runs_stmt)).all()

    runs: list[dict[str, Any]] = []
    for run in run_rows:
        run_events = await _fetch_recent_run_events(
            session,
            run_id=run.run_id,
            events_limit=events_limit,
        )
        runs.append(
            {
                "run_id": run.run_id,
                "assistant_id": run.assistant_id,
                "status": run.status,
                "error_message": run.error_message,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "updated_at": run.updated_at.isoformat() if run.updated_at else None,
                "events": run_events,
            }
        )

    # 4) 聚合返回：thread 基本信息 + runtime + runs，供前端调试面板一次拉取。
    metadata = thread.metadata_json if isinstance(thread.metadata_json, dict) else {}
    return {
        "thread": {
            "thread_id": thread.thread_id,
            "status": thread.status,
            "user_id": thread.user_id,
            "metadata": metadata,
            "created_at": thread.created_at.isoformat() if thread.created_at else None,
            "updated_at": thread.updated_at.isoformat() if thread.updated_at else None,
        },
        "runtime": runtime,
        "runs": runs,
        "summary": {
            "run_count": len(runs),
            "error_run_count": len(
                [
                    r
                    for r in runs
                    if r.get("status") in {"error", "timeout", "interrupted"}
                ]
            ),
            "has_runtime_diagnostic": bool(runtime.get("last_diagnostic_fingerprint")),
            "timestamp": utc_now_iso_z(),
        },
    }


@router.get("/sandbox/threads/{thread_id}/preview")
async def get_sandbox_preview(
    thread_id: str,
    redirect: bool = Query(
        True,
        description="Whether to return HTTP redirect to preview URL",
    ),
    path: str = Query(
        "/",
        description="Sub-path to append to preview URL (e.g. /src/main.jsx)",
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    # 复用 runtime 查询，确保 preview 路由与运行态数据源一致。
    runtime = await get_sandbox_runtime(
        thread_id=thread_id,
        include_state_values=False,
        log_lines=40,
        errors_only=True,
        include_container_details=False,
        user=user,
        session=session,
    )
    service_status = runtime.get("service_status")
    base_url = _pick_preview_url(service_status)
    if not base_url:
        raise HTTPException(
            409,
            "Preview URL is unavailable. Service may not be running yet.",
        )

    # 统一 path 规范，避免出现双斜杠拼接。
    normalized_path = path if path.startswith("/") else f"/{path}"
    target_url = f"{base_url.rstrip('/')}{normalized_path}"

    if redirect:
        # 默认重定向：前端可直接打开该 API，自动跳到真实端口。
        return RedirectResponse(url=target_url, status_code=307)

    # 非重定向模式：返回结构化信息，便于前端自己处理跳转。
    return {
        "thread_id": thread_id,
        "preview_url": target_url,
        "base_preview_url": base_url,
        "runtime_status": runtime.get("status"),
        "service_running": (
            service_status.get("service_running")
            if isinstance(service_status, dict)
            else None
        ),
        "preview_probes": (
            service_status.get("preview_probes")
            if isinstance(service_status, dict)
            else {}
        ),
    }
