from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.tool_telemetry import ToolTelemetry

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


@router.get("/stats")
async def get_global_stats(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """获取全局工具调用统计数据."""
    # 1. 总成功率
    total_stmt = sa.select(sa.func.count(ToolTelemetry.id))
    success_stmt = sa.select(sa.func.count(ToolTelemetry.id)).where(
        ToolTelemetry.is_success
    )

    total_res = await db.execute(total_stmt)
    success_res = await db.execute(success_stmt)

    total_count = total_res.scalar() or 0
    success_count = success_res.scalar() or 0

    # 2. 错误类型分布
    error_stmt = (
        sa.select(ToolTelemetry.error_code, sa.func.count(ToolTelemetry.id))
        .where(sa.not_(ToolTelemetry.is_success))
        .group_by(ToolTelemetry.error_code)
    )

    error_res = await db.execute(error_stmt)
    error_distribution = {row[0]: row[1] for row in error_res.all() if row[0]}

    # 3. 工具使用频率
    tool_stmt = sa.select(
        ToolTelemetry.tool_name, sa.func.count(ToolTelemetry.id)
    ).group_by(ToolTelemetry.tool_name)
    tool_res = await db.execute(tool_stmt)
    tool_usage = {row[0]: row[1] for row in tool_res.all()}

    return {
        "total_calls": total_count,
        "success_rate": (success_count / total_count * 100) if total_count > 0 else 0,
        "error_distribution": error_distribution,
        "tool_usage": tool_usage,
    }


@router.get("/logs/{thread_id}")
async def get_thread_logs(
    thread_id: str,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """获取特定会话的工具调用日志流."""
    stmt = (
        sa.select(ToolTelemetry)
        .where(ToolTelemetry.thread_id == thread_id)
        .order_by(ToolTelemetry.created_at.desc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    logs = res.scalars().all()

    return [
        {
            "id": log.id,
            "tool_name": log.tool_name,
            "is_success": log.is_success,
            "error_code": log.error_code,
            "message": log.message,
            "details": log.details,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]
