from __future__ import annotations

import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ToolTelemetry(Base):
    """工具调用遥测统计表，用于分析 Agent 工具调用的成功率和错误分布."""

    __tablename__ = "tool_telemetry"

    id: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, autoincrement=True, comment="自增 ID"
    )
    thread_id: Mapped[str] = mapped_column(
        sa.Text, nullable=False, index=True, comment="对话会话 ID"
    )
    tool_name: Mapped[str] = mapped_column(
        sa.Text, nullable=False, index=True, comment="工具名称 (如 apply_patch)"
    )
    is_success: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, comment="是否成功执行"
    )
    error_code: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, index=True, comment="错误代码 (如 PATCH_NO_MATCH)"
    )
    message: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="工具返回的消息或错误摘要"
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="结构化的详细统计数据 (如 hunk 数量、Token 消耗等)",
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
        comment="记录创建时间",
    )
