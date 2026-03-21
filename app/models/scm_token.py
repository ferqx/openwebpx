from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ScmToken(Base):
    """SCM (GitHub/GitLab) OAuth 授权令牌存储表."""

    __tablename__ = "scm_tokens"

    cache_key: Mapped[str] = mapped_column(
        sa.Text, primary_key=True, nullable=False, comment="缓存键"
    )
    user_id: Mapped[str] = mapped_column(sa.Text, nullable=False, comment="用户 ID")
    provider: Mapped[str] = mapped_column(
        sa.Text, nullable=False, comment="提供商 (github/gitlab)"
    )
    gitlab_base_url: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="GitLab 自定义实例地址"
    )
    github_auth_mode: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="GitHub 认证模式"
    )
    token_encrypted: Mapped[str] = mapped_column(
        sa.Text, nullable=False, comment="加密的令牌载荷"
    )
    updated_at: Mapped[float] = mapped_column(
        sa.Float, nullable=False, comment="更新时间戳 (Unix time)"
    )

    __table_args__ = (sa.Index("idx_scm_tokens_user_provider", "user_id", "provider"),)
