from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from aegra_api.core import orm as aegra_orm
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def get_async_session_maker():
    """统一获取异步 SessionMaker 的入口."""
    session_maker = getattr(aegra_orm, "async_session_maker", None)
    if session_maker is None:
        try:
            session_maker = aegra_orm._get_session_maker()
        except RuntimeError:
            logger.warning("Core: async_session_maker not found in aegra_api.")
    return session_maker


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖注入使用的数据库会话."""
    session_maker = get_async_session_maker()
    if session_maker is None:
        raise RuntimeError("Database not initialized")

    async with session_maker() as session:
        yield session
