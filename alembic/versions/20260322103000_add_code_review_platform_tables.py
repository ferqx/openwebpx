"""Add code review platform tables

Revision ID: f0f2a8d6c9b7
Revises: c8b3e5d02g21
Create Date: 2026-03-22 10:30:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision = "f0f2a8d6c9b7"
down_revision = "c8b3e5d02g21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repository_integrations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("external_repo_id", sa.Text(), nullable=False),
        sa.Column(
            "repository_identity_key",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("default_branch", sa.Text(), nullable=True),
        sa.Column("gitlab_base_url", sa.Text(), nullable=True),
        sa.Column("webhook_status", sa.Text(), nullable=True),
        sa.Column("webhook_management_mode", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "external_repo_id",
            "repository_identity_key",
            name="uq_repository_integrations_provider_external_repo_identity_key",
        ),
    )

    op.create_table(
        "repository_memberships",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "repository_integration_id",
            sa.Integer(),
            sa.ForeignKey("repository_integrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column(
            "can_approve_fixes",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_integration_id",
            "user_id",
            name="uq_repository_memberships_repository_integration_id_user_id",
        ),
    )

    op.create_table(
        "repository_review_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "repository_integration_id",
            sa.Integer(),
            sa.ForeignKey("repository_integrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "review_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("review_triggers", JSONB(), nullable=True),
        sa.Column(
            "auto_fix_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("auto_fix_severities", JSONB(), nullable=True),
        sa.Column(
            "auto_fix_requires_approval",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "auto_publish_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repository_integration_id"),
    )

    op.create_table(
        "review_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "repository_integration_id",
            sa.Integer(),
            sa.ForeignKey("repository_integrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("external_event_id", sa.Text(), nullable=True),
        sa.Column("external_pr_or_mr_id", sa.Text(), nullable=True),
        sa.Column("head_commit_id", sa.Text(), nullable=True),
        sa.Column("base_commit_id", sa.Text(), nullable=True),
        sa.Column("base_branch", sa.Text(), nullable=True),
        sa.Column("head_branch", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "analyzing",
                "completed",
                "failed",
                name="review_run_status",
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("created_by_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )

    op.create_table(
        "review_findings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "review_run_id",
            sa.Integer(),
            sa.ForeignKey("review_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("rule_id", sa.Text(), nullable=True),
        sa.Column(
            "can_auto_fix",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "review_run_id",
            "id",
            name="uq_review_findings_review_run_id_id",
        ),
    )

    op.create_table(
        "review_timeline_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "review_run_id",
            sa.Integer(),
            sa.ForeignKey("review_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "review_run_id",
            "event_type",
            "dedupe_key",
            name="uq_review_timeline_events_dedupe",
        ),
    )

    op.create_table(
        "review_fix_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "review_run_id",
            sa.Integer(),
            sa.ForeignKey("review_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("review_finding_id", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "auto_policy",
                name="review_fix_request_source",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending_approval",
                "approved",
                "rejected",
                "running",
                "completed",
                "failed",
                name="review_fix_request_status",
            ),
            nullable=False,
        ),
        sa.Column(
            "approval_required",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.Text(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("runner_job_id", sa.Text(), nullable=True),
        sa.Column("result_payload", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["review_run_id", "review_finding_id"],
            ["review_findings.review_run_id", "review_findings.id"],
            name="fk_review_fix_requests_review_run_id_review_finding_id",
            ondelete="CASCADE",
        ),
    )

    op.create_index(
        "idx_repository_memberships_user_id_repository_integration_id",
        "repository_memberships",
        ["user_id", "repository_integration_id"],
    )
    op.create_index(
        "idx_review_runs_repository_integration_id_status",
        "review_runs",
        ["repository_integration_id", "status"],
    )
    op.create_index(
        "idx_review_fix_requests_review_run_id_status",
        "review_fix_requests",
        ["review_run_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_review_fix_requests_review_run_id_status", table_name="review_fix_requests"
    )
    op.drop_index(
        "idx_review_runs_repository_integration_id_status", table_name="review_runs"
    )
    op.drop_index(
        "idx_repository_memberships_user_id_repository_integration_id",
        table_name="repository_memberships",
    )
    op.drop_table("review_fix_requests")
    op.drop_table("review_timeline_events")
    op.drop_table("review_findings")
    op.drop_table("review_runs")
    op.drop_table("repository_review_configs")
    op.drop_table("repository_memberships")
    op.drop_table("repository_integrations")
    op.execute(sa.text("DROP TYPE IF EXISTS review_fix_request_status"))
    op.execute(sa.text("DROP TYPE IF EXISTS review_fix_request_source"))
    op.execute(sa.text("DROP TYPE IF EXISTS review_run_status"))
