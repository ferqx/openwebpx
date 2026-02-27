from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import docker
from aegra_api.core.auth_deps import get_current_user
from aegra_api.core.orm import Run as RunORM
from aegra_api.core.orm import RunEvent as RunEventORM
from aegra_api.core.orm import Thread as ThreadORM
from aegra_api.core.orm import get_session
from aegra_api.services.langgraph_service import (
    create_thread_config,
    get_langgraph_service,
)
from docker.errors import DockerException, NotFound
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from aegra_api.models.auth import User

router = APIRouter()


def _utc_now_iso_z() -> str:
    """返回 UTC ISO 时间戳（以 Z 结尾）。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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

    thread_metadata = thread.metadata_json or {}
    graph_id = thread_metadata.get("graph_id")
    if not graph_id:
        return {
            "thread_id": thread_id,
            "graph_id": None,
            "status": "no_graph",
            "service_status": None,
            "container_id": None,
        }

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
        response["runtime_timestamp"] = _utc_now_iso_z()

    if include_state_values:
        response["state_values"] = values
    return response


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
            "timestamp": _utc_now_iso_z(),
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
