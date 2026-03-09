import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from aegra_api.core import orm as aegra_orm
from aegra_api.core.auth_deps import require_auth
from fastapi import Depends, FastAPI

from app.routers.auth import router as auth_router
from app.routers.code_review import public_router as code_review_public_router
from app.routers.code_review import router as code_review_router
from app.routers.common import router as common_router
from app.routers.sandbox import router as sandbox_router
from app.routers.scm import router as scm_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Reset cached sessionmaker so it always binds to the current async engine/loop.
    aegra_orm.async_session_maker = None
    _install_loop_safe_session_maker_patch()
    _install_langgraph_missing_graph_fallback_patch()
    yield
    aegra_orm.async_session_maker = None


app = FastAPI(lifespan=lifespan)


def _install_loop_safe_session_maker_patch() -> None:
    """Patch aegra ORM sessionmaker cache to be event-loop aware.

    In reload or mixed-loop runtime paths, reusing a cached async_sessionmaker
    can close asyncpg connections from a different loop and raise:
    "Future attached to a different loop".
    """
    if getattr(aegra_orm, "_openwebpx_loop_safe_patch_installed", False):
        return

    original_get_session_maker: Callable[..., Any] = aegra_orm._get_session_maker

    def _loop_safe_get_session_maker():
        try:
            loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            loop_id = None

        cached_loop_id = getattr(aegra_orm, "_openwebpx_session_maker_loop_id", None)
        if loop_id is not None and cached_loop_id != loop_id:
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
