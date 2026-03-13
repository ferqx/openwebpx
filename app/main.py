import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any

from aegra_api.core import orm as aegra_orm
from aegra_api.core.auth_deps import require_auth
from aegra_api.core.database import db_manager
from aegra_api.core.orm import Run as RunORM
from aegra_api.core.orm import Thread as ThreadORM
from aegra_api.settings import settings
from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.routers.auth import router as auth_router
from app.routers.code_review import public_router as code_review_public_router
from app.routers.code_review import router as code_review_router
from app.routers.common import router as common_router
from app.routers.sandbox import router as sandbox_router
from app.routers.scm import router as scm_router

logger = logging.getLogger(__name__)

USE_SQLALCHEMY_NULLPOOL = os.getenv(
    "OPENWEBPX_SQLALCHEMY_USE_NULLPOOL", "true"
).strip().lower() not in {"0", "false", "no"}
BOOTSTRAP_METADATA_KEY = "sandbox_bootstrap"
BOOTSTRAP_LOG_LIMIT = 80
BOOTSTRAP_EVENT_LIMIT = 400


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Reset cached sessionmaker so it always binds to the current async engine/loop.
    aegra_orm.async_session_maker = None
    _install_loop_safe_session_maker_patch()
    _install_langgraph_missing_graph_fallback_patch()
    await _recover_interrupted_runtime_state()
    yield
    aegra_orm.async_session_maker = None


app = FastAPI(lifespan=lifespan)


def _utc_now_iso_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _append_bootstrap_restart_log(
    state: dict[str, Any],
    *,
    now_iso: str,
    message: str,
) -> None:
    logs = state.get("logs")
    if not isinstance(logs, list):
        logs = []
    logs.append(
        {
            "timestamp": now_iso,
            "level": "error",
            "message": message,
        }
    )
    state["logs"] = logs[-BOOTSTRAP_LOG_LIMIT:]

    current_seq = state.get("event_seq")
    next_seq = int(current_seq) + 1 if isinstance(current_seq, int) else 1
    state["event_seq"] = next_seq

    events = state.get("events")
    if not isinstance(events, list):
        events = []
    events.append(
        {
            "seq": next_seq,
            "type": "log",
            "timestamp": now_iso,
            "level": "error",
            "message": message,
        }
    )
    state["events"] = events[-BOOTSTRAP_EVENT_LIMIT:]
    state["updated_at"] = now_iso


def _recover_thread_metadata_after_restart(
    metadata: Any,
    *,
    now_iso: str,
) -> tuple[dict[str, Any], bool]:
    next_metadata = dict(metadata) if isinstance(metadata, dict) else {}

    raw_state = next_metadata.get(BOOTSTRAP_METADATA_KEY)
    if not isinstance(raw_state, dict):
        return next_metadata, False

    status = raw_state.get("status")
    if status != "running":
        return next_metadata, False

    next_state = dict(raw_state)
    next_state["status"] = "error"
    next_state["error"] = "服务重启导致初始化任务中断，请重新触发。"
    next_state["finished_at"] = now_iso
    next_state["updated_at"] = now_iso

    run_status = next_state.get("run_status")
    if not isinstance(run_status, str) or run_status in {"pending", "running"}:
        next_state["run_status"] = "interrupted"

    steps = next_state.get("steps")
    if isinstance(steps, list):
        normalized_steps: list[dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            next_step = dict(step)
            if next_step.get("status") == "running":
                next_step["status"] = "error"
                next_step.setdefault("detail", "服务重启中断")
            normalized_steps.append(next_step)
        next_state["steps"] = normalized_steps

    _append_bootstrap_restart_log(
        next_state,
        now_iso=now_iso,
        message="后台初始化任务因服务重启中断，状态已自动回收。",
    )
    next_metadata[BOOTSTRAP_METADATA_KEY] = next_state
    return next_metadata, True


async def _recover_interrupted_runtime_state() -> None:
    try:
        maker = aegra_orm._get_session_maker()
    except RuntimeError as exc:
        if "Database not initialized" in str(exc):
            logger.info(
                "Skipping stranded runtime recovery because database is not initialized yet."
            )
            return
        raise
    now = datetime.now(UTC)
    now_iso = now.isoformat().replace("+00:00", "Z")

    async with maker() as session:
        pending_runs = (
            await session.scalars(
                select(RunORM).where(RunORM.status.in_(["pending", "running"]))
            )
        ).all()
        busy_threads = (
            await session.scalars(select(ThreadORM).where(ThreadORM.status == "busy"))
        ).all()

        recovered_runs = 0
        recovered_threads = 0

        for run in pending_runs:
            run.status = "interrupted"
            run.updated_at = now
            run.error_message = (
                "Run interrupted because the service restarted before execution "
                "finished. Please retry the thread."
            )
            recovered_runs += 1

        for thread in busy_threads:
            thread.status = "idle"
            thread.updated_at = now

            next_metadata, metadata_changed = _recover_thread_metadata_after_restart(
                getattr(thread, "metadata_json", None),
                now_iso=now_iso,
            )
            if metadata_changed:
                thread.metadata_json = next_metadata
            recovered_threads += 1

        if not recovered_runs and not recovered_threads:
            return

        await session.commit()
        logger.warning(
            "Recovered stranded runtime state after service restart: %s runs, %s threads.",
            recovered_runs,
            recovered_threads,
        )


def _install_loop_safe_session_maker_patch() -> None:
    """Patch aegra ORM sessionmaker cache to be event-loop aware.

    In reload or mixed-loop runtime paths, reusing a cached async_sessionmaker
    can close asyncpg connections from a different loop and raise:
    "Future attached to a different loop".
    """
    if getattr(aegra_orm, "_openwebpx_loop_safe_patch_installed", False):
        return

    original_get_session_maker: Callable[..., Any] = aegra_orm._get_session_maker
    pool_size = settings.pool.SQLALCHEMY_POOL_SIZE
    max_overflow = settings.pool.SQLALCHEMY_MAX_OVERFLOW
    echo = settings.db.DB_ECHO_LOG

    def _create_loop_safe_engine():
        engine_kwargs: dict[str, Any] = {
            "pool_pre_ping": True,
            "echo": echo,
        }
        if USE_SQLALCHEMY_NULLPOOL:
            engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs["pool_size"] = pool_size
            engine_kwargs["max_overflow"] = max_overflow
        return create_async_engine(db_manager._database_url, **engine_kwargs)

    def _is_engine_pool_bound_to_current_loop() -> bool:
        if USE_SQLALCHEMY_NULLPOOL:
            return False
        engine = db_manager.engine
        if engine is None:
            return False
        with suppress(RuntimeError):
            current_loop = asyncio.get_running_loop()
            pool = getattr(engine, "pool", None)
            async_adapted_pool = getattr(pool, "_pool", None)
            raw_queue = getattr(async_adapted_pool, "_queue", None)
            bound_loop = getattr(raw_queue, "_loop", None)
            if bound_loop is not None and bound_loop is not current_loop:
                return True
        return False

    def _rebind_sqlalchemy_engine_for_current_loop() -> None:
        old_engine = db_manager.engine
        if old_engine is None:
            return

        db_manager.engine = _create_loop_safe_engine()
        # Best-effort cleanup of old engine pool; ignore failures caused by stale loop.
        with suppress(Exception):
            loop = asyncio.get_running_loop()

            async def _dispose_old_engine() -> None:
                with suppress(Exception):
                    await old_engine.dispose()

            loop.create_task(_dispose_old_engine())

    def _loop_safe_get_session_maker():
        try:
            loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            loop_id = None

        cached_loop_id = getattr(aegra_orm, "_openwebpx_session_maker_loop_id", None)
        loop_changed = loop_id is not None and cached_loop_id != loop_id
        pool_loop_mismatch = _is_engine_pool_bound_to_current_loop()
        if loop_changed or pool_loop_mismatch:
            if pool_loop_mismatch and not loop_changed:
                logger.warning(
                    "Detected SQLAlchemy pool bound to stale event loop; rebinding engine."
                )
            if USE_SQLALCHEMY_NULLPOOL:
                logger.warning("Using SQLAlchemy NullPool for loop-safe DB access.")
            _rebind_sqlalchemy_engine_for_current_loop()
            aegra_orm.async_session_maker = None
            aegra_orm._openwebpx_session_maker_loop_id = loop_id
        return original_get_session_maker()

    aegra_orm._get_session_maker = _loop_safe_get_session_maker
    aegra_orm._openwebpx_loop_safe_patch_installed = True


def _pick_fallback_graph_id(
    *,
    available_graph_ids: list[str],
    preferred_default: str | None,
) -> str | None:
    if not available_graph_ids:
        return None
    if preferred_default and preferred_default in available_graph_ids:
        return preferred_default

    versioned: list[tuple[int, str]] = []
    for graph_id in available_graph_ids:
        match = re.fullmatch(r"build_app_agent_v(\d+)", graph_id)
        if match is None:
            continue
        versioned.append((int(match.group(1)), graph_id))
    if versioned:
        versioned.sort(key=lambda item: item[0], reverse=True)
        return versioned[0][1]

    return available_graph_ids[-1]


def _install_langgraph_missing_graph_fallback_patch() -> None:
    """Patch LangGraphService to fallback when a historical graph_id is missing."""
    try:
        from aegra_api.services import langgraph_service as langgraph_service_module
    except Exception:
        return

    if getattr(
        langgraph_service_module,
        "_openwebpx_missing_graph_fallback_patch_installed",
        False,
    ):
        return

    service_cls = langgraph_service_module.LangGraphService
    original_get_base_graph: Callable[..., Any] = service_cls._get_base_graph

    async def _fallback_get_base_graph(self: Any, graph_id: str):
        try:
            return await original_get_base_graph(self, graph_id)
        except ValueError as exc:
            if "Graph not found:" not in str(exc):
                raise

            registry = getattr(self, "_graph_registry", None)
            if not isinstance(registry, dict):
                raise

            available_graph_ids = list(registry.keys())
            fallback_graph_id = _pick_fallback_graph_id(
                available_graph_ids=available_graph_ids,
                preferred_default=str(
                    os.getenv("OPENWEBPX_DEFAULT_TASK_GRAPH_ID", "")
                ).strip()
                or None,
            )
            if fallback_graph_id is None or fallback_graph_id == graph_id:
                raise

            # Keep an in-memory alias so subsequent calls with old ids work.
            registry[graph_id] = registry[fallback_graph_id]
            logger.warning(
                "Graph '%s' not found; falling back to '%s'.",
                graph_id,
                fallback_graph_id,
            )
            return await original_get_base_graph(self, graph_id)

    service_cls._get_base_graph = _fallback_get_base_graph
    langgraph_service_module._openwebpx_missing_graph_fallback_patch_installed = True


# Public routes
app.include_router(common_router)
app.include_router(auth_router)
app.include_router(code_review_public_router)

# Protected custom routes
app.include_router(sandbox_router, dependencies=[Depends(require_auth)])
app.include_router(scm_router, dependencies=[Depends(require_auth)])
app.include_router(code_review_router, dependencies=[Depends(require_auth)])
