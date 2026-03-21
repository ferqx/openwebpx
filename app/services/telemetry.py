from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import insert

from app.core.database import get_async_session_maker
from app.models.tool_telemetry import ToolTelemetry

logger = logging.getLogger(__name__)


async def record_tool_telemetry(
    *,
    thread_id: str,
    tool_name: str,
    is_success: bool,
    error_code: str | None = None,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """异步记录工具调用遥测数据到数据库."""
    if not thread_id:
        return

    session_maker = get_async_session_maker()
    if session_maker is None:
        return

    try:
        async with session_maker() as session:
            stmt = insert(ToolTelemetry).values(
                thread_id=thread_id,
                tool_name=tool_name,
                is_success=is_success,
                error_code=error_code,
                message=message,
                details=details,
            )
            await session.execute(stmt)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to record tool telemetry: {e}")
