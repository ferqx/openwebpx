import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aegra_api.api.assistants import router as assistants_router
from aegra_api.api.runs import router as runs_router
from aegra_api.api.stateless_runs import router as stateless_runs_router
from aegra_api.api.store import router as store_router
from aegra_api.api.threads import router as threads_router
from aegra_api.core import orm as aegra_orm
from aegra_api.core.database import db_manager
from aegra_api.core.health import router as health_router
from aegra_api.core.migrations import run_migrations_async
from aegra_api.settings import settings
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.core.env  # noqa: F401
from app.core.auth import authenticated_user
from app.routers.auth import router as auth_router
from app.routers.code_review_fixes import router as code_review_fixes_router
from app.routers.code_review_repositories import (
    router as code_review_repositories_router,
)
from app.routers.code_review_runs import router as code_review_runs_router
from app.routers.code_review_webhooks import (
    router as code_review_webhooks_router,
)
from app.routers.common import router as common_router
from app.routers.sandbox import router as sandbox_router
from app.routers.scm import router as scm_router
from app.routers.telemetry import router as telemetry_router

logger = logging.getLogger(__name__)

USE_SQLALCHEMY_NULLPOOL = os.getenv(
    "OPENWEBPX_SQLALCHEMY_USE_NULLPOOL", "true"
).strip().lower() not in {"0", "false", "no"}


async def _rebind_sqlalchemy_engine_to_nullpool() -> None:
    current_engine = db_manager.engine
    if current_engine is None:
        logger.warning("Skipping SQLAlchemy NullPool rebind: engine is not initialized")
        return

    if isinstance(current_engine.sync_engine.pool, NullPool):
        logger.info("SQLAlchemy engine already uses NullPool for custom routes")
        aegra_orm.async_session_maker = None
        return

    replacement_engine = create_async_engine(
        settings.db.database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
        echo=settings.db.DB_ECHO_LOG,
    )
    db_manager.engine = replacement_engine
    aegra_orm.async_session_maker = None
    await current_engine.dispose()
    logger.info("Rebound SQLAlchemy engine to NullPool for custom routes")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await run_migrations_async()
    await db_manager.initialize()
    if USE_SQLALCHEMY_NULLPOOL:
        await _rebind_sqlalchemy_engine_to_nullpool()
    try:
        yield
    finally:
        await db_manager.close()


app = FastAPI(lifespan=lifespan)

# Core Aegra API routes expected by the frontend SDK.
app.include_router(health_router, prefix="/api")
app.include_router(assistants_router, prefix="/api")
app.include_router(threads_router, prefix="/api")
app.include_router(runs_router, prefix="/api")
app.include_router(stateless_runs_router, prefix="/api")
app.include_router(store_router, prefix="/api")


# Public routes
app.include_router(common_router)
app.include_router(auth_router)
app.include_router(auth_router, prefix="/api")
app.include_router(code_review_webhooks_router)
app.include_router(
    scm_router, prefix="/api", dependencies=[Depends(authenticated_user)]
)
app.include_router(
    sandbox_router, prefix="/api", dependencies=[Depends(authenticated_user)]
)

# Protected custom routes
app.include_router(sandbox_router, dependencies=[Depends(authenticated_user)])
app.include_router(scm_router, dependencies=[Depends(authenticated_user)])
app.include_router(
    code_review_repositories_router, dependencies=[Depends(authenticated_user)]
)
app.include_router(code_review_runs_router, dependencies=[Depends(authenticated_user)])
app.include_router(code_review_fixes_router)
app.include_router(telemetry_router, dependencies=[Depends(authenticated_user)])
