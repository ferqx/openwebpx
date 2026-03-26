from __future__ import annotations

import datetime
import enum
from typing import Any

import sqlalchemy as sa
from aegra_api.core.orm import Base
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates


class ReviewRunStatus(enum.StrEnum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewFixRequestStatus(enum.StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewFixRequestSource(enum.StrEnum):
    AUTO_POLICY = "auto_policy"


class RepositoryIntegration(Base):
    __tablename__ = "repository_integrations"

    id: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, autoincrement=True, comment="自增 ID"
    )
    provider: Mapped[str] = mapped_column(sa.Text, nullable=False, comment="提供商")
    external_repo_id: Mapped[str] = mapped_column(
        sa.Text, nullable=False, comment="外部仓库 ID"
    )
    repository_identity_key: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        server_default=sa.text("''"),
        comment="仓库唯一身份键；GitHub 使用空字符串，GitLab 使用实例地址",
    )
    full_name: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="仓库全名"
    )
    default_branch: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="默认分支"
    )
    gitlab_base_url: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="GitLab 自定义实例地址"
    )
    webhook_status: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="Webhook 状态"
    )
    webhook_management_mode: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="Webhook 管理模式"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        comment="更新时间，phase 1 由服务层维护",
        nullable=False,
    )

    memberships: Mapped[list[RepositoryMembership]] = relationship(
        back_populates="repository_integration", cascade="all, delete-orphan"
    )
    review_config: Mapped[RepositoryReviewConfig | None] = relationship(
        back_populates="repository_integration",
        uselist=False,
        cascade="all, delete-orphan",
    )
    review_runs: Mapped[list[ReviewRun]] = relationship(
        back_populates="repository_integration", cascade="all, delete-orphan"
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "provider",
            "external_repo_id",
            "repository_identity_key",
            name="uq_repository_integrations_provider_external_repo_identity_key",
        ),
    )


class RepositoryMembership(Base):
    __tablename__ = "repository_memberships"

    id: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, autoincrement=True, comment="自增 ID"
    )
    repository_integration_id: Mapped[int] = mapped_column(
        sa.ForeignKey("repository_integrations.id", ondelete="CASCADE"),
        nullable=False,
        comment="仓库集成 ID",
    )
    user_id: Mapped[str] = mapped_column(sa.Text, nullable=False, comment="用户 ID")
    role: Mapped[str | None] = mapped_column(sa.Text, nullable=True, comment="成员角色")
    can_approve_fixes: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false(), comment="是否可审批修复"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        comment="更新时间，phase 1 由服务层维护",
        nullable=False,
    )

    repository_integration: Mapped[RepositoryIntegration] = relationship(
        back_populates="memberships"
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "repository_integration_id",
            "user_id",
            name="uq_repository_memberships_repository_integration_id_user_id",
        ),
    )


class RepositoryReviewConfig(Base):
    __tablename__ = "repository_review_configs"

    id: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, autoincrement=True, comment="自增 ID"
    )
    repository_integration_id: Mapped[int] = mapped_column(
        sa.ForeignKey("repository_integrations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="仓库集成 ID",
    )
    review_enabled: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false(), comment="是否启用评审"
    )
    review_triggers: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="评审触发配置"
    )
    auto_fix_enabled: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        comment="是否启用自动修复",
    )
    auto_fix_severities: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="自动修复严重级别"
    )
    auto_fix_requires_approval: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.true(),
        comment="自动修复是否需要审批",
    )
    auto_publish_enabled: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        comment="是否启用自动发布",
    )
    updated_by: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="更新人"
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        comment="更新时间，phase 1 由服务层维护",
        nullable=False,
    )

    repository_integration: Mapped[RepositoryIntegration] = relationship(
        back_populates="review_config"
    )


class ReviewRun(Base):
    __tablename__ = "review_runs"

    id: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, autoincrement=True, comment="自增 ID"
    )
    repository_integration_id: Mapped[int] = mapped_column(
        sa.ForeignKey("repository_integrations.id", ondelete="CASCADE"),
        nullable=False,
        comment="仓库集成 ID",
    )
    provider: Mapped[str] = mapped_column(sa.Text, nullable=False, comment="提供商")
    event_type: Mapped[str] = mapped_column(sa.Text, nullable=False, comment="事件类型")
    external_event_id: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="外部事件 ID"
    )
    external_pr_or_mr_id: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="外部 PR/MR ID"
    )
    head_commit_id: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="Head 提交 ID"
    )
    base_commit_id: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="Base 提交 ID"
    )
    base_branch: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="Base 分支"
    )
    head_branch: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="Head 分支"
    )
    status: Mapped[ReviewRunStatus] = mapped_column(
        sa.Enum(
            ReviewRunStatus,
            name="review_run_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        comment="运行状态",
    )
    idempotency_key: Mapped[str] = mapped_column(
        sa.Text, nullable=False, unique=True, comment="幂等键"
    )
    thread_id: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="关联的 Aegra 会话线程 ID"
    )
    created_by_event_at: Mapped[datetime.datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, comment="事件创建时间"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        comment="更新时间，phase 1 由服务层维护",
        nullable=False,
    )

    repository_integration: Mapped[RepositoryIntegration] = relationship(
        back_populates="review_runs"
    )
    findings: Mapped[list[ReviewFinding]] = relationship(
        back_populates="review_run", cascade="all, delete-orphan"
    )
    timeline_events: Mapped[list[ReviewTimelineEvent]] = relationship(
        back_populates="review_run", cascade="all, delete-orphan"
    )
    fix_requests: Mapped[list[ReviewFixRequest]] = relationship(
        back_populates="review_run", cascade="all, delete-orphan"
    )


class ReviewFinding(Base):
    __tablename__ = "review_findings"

    id: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, autoincrement=True, comment="自增 ID"
    )
    review_run_id: Mapped[int] = mapped_column(
        sa.ForeignKey("review_runs.id", ondelete="CASCADE"),
        nullable=False,
        comment="评审运行 ID",
    )
    severity: Mapped[str] = mapped_column(sa.Text, nullable=False, comment="严重级别")
    category: Mapped[str | None] = mapped_column(sa.Text, nullable=True, comment="分类")
    file_path: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="文件路径"
    )
    line_start: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True, comment="起始行"
    )
    line_end: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True, comment="结束行"
    )
    title: Mapped[str] = mapped_column(sa.Text, nullable=False, comment="标题")
    body: Mapped[str | None] = mapped_column(sa.Text, nullable=True, comment="描述")
    rule_id: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="规则 ID"
    )
    can_auto_fix: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false(), comment="是否可自动修复"
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True, comment="finding 元数据"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
        comment="创建时间",
    )

    review_run: Mapped[ReviewRun] = relationship(back_populates="findings")
    fix_requests: Mapped[list[ReviewFixRequest]] = relationship(
        back_populates="review_finding",
        cascade="all, delete-orphan",
        overlaps="review_run,fix_requests",
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "review_run_id",
            "id",
            name="uq_review_findings_review_run_id_id",
        ),
    )


class ReviewTimelineEvent(Base):
    __tablename__ = "review_timeline_events"

    id: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, autoincrement=True, comment="自增 ID"
    )
    review_run_id: Mapped[int] = mapped_column(
        sa.ForeignKey("review_runs.id", ondelete="CASCADE"),
        nullable=False,
        comment="评审运行 ID",
    )
    event_type: Mapped[str] = mapped_column(sa.Text, nullable=False, comment="事件类型")
    dedupe_key: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="去重键"
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="事件载荷"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
        comment="创建时间",
    )

    review_run: Mapped[ReviewRun] = relationship(back_populates="timeline_events")

    __table_args__ = (
        sa.UniqueConstraint(
            "review_run_id",
            "event_type",
            "dedupe_key",
            name="uq_review_timeline_events_dedupe",
        ),
    )


class ReviewFixRequest(Base):
    __tablename__ = "review_fix_requests"

    id: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, autoincrement=True, comment="自增 ID"
    )
    review_run_id: Mapped[int] = mapped_column(
        sa.ForeignKey("review_runs.id", ondelete="CASCADE"),
        nullable=False,
        comment="评审运行 ID",
    )
    review_finding_id: Mapped[int] = mapped_column(
        nullable=False,
        comment="评审 finding ID",
    )
    source: Mapped[ReviewFixRequestSource] = mapped_column(
        sa.Enum(
            ReviewFixRequestSource,
            name="review_fix_request_source",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        comment="创建来源",
    )
    status: Mapped[ReviewFixRequestStatus] = mapped_column(
        sa.Enum(
            ReviewFixRequestStatus,
            name="review_fix_request_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        comment="修复请求状态",
    )
    approval_required: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.true(), comment="是否需要审批"
    )
    approved_by: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="审批人"
    )
    approved_at: Mapped[datetime.datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, comment="审批时间"
    )
    rejected_by: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="拒绝人"
    )
    rejected_at: Mapped[datetime.datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, comment="拒绝时间"
    )
    runner_job_id: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True, comment="运行器任务 ID"
    )
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="结果载荷"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        comment="更新时间，phase 1 由服务层维护",
        nullable=False,
    )

    review_run: Mapped[ReviewRun] = relationship(
        back_populates="fix_requests",
        overlaps="fix_requests,review_finding",
    )
    review_finding: Mapped[ReviewFinding] = relationship(
        back_populates="fix_requests",
        overlaps="fix_requests,review_run",
    )

    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["review_run_id", "review_finding_id"],
            ["review_findings.review_run_id", "review_findings.id"],
            name="fk_review_fix_requests_review_run_id_review_finding_id",
            ondelete="CASCADE",
        ),
    )

    @validates("review_run_id", "review_finding")
    def _validate_run_and_finding(
        self, key: str, value: int | ReviewFinding | None
    ) -> int | ReviewFinding | None:
        if key == "review_run_id":
            if (
                self.review_finding is not None
                and value is not None
                and self.review_finding.review_run_id != value
            ):
                raise ValueError(
                    "review_run_id must match the review_finding.review_run_id"
                )
        else:
            if (
                value is not None
                and self.review_run_id is not None
                and value.review_run_id != self.review_run_id
            ):
                raise ValueError(
                    "review_finding.review_run_id must match review_run_id"
                )
        return value
