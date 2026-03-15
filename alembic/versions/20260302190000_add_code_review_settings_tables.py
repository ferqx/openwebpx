"""Add code review settings tables

Revision ID: c4d8f8b8a812
Revises: 3c2f7a9b1d4e
Create Date: 2026-03-02 19:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c4d8f8b8a812"
down_revision = "3c2f7a9b1d4e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "code_review_profiles",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column(
            "auto_review_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "default_trigger",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pr_open'"),
        ),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "code_review_repo_settings",
        sa.Column("setting_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("gitlab_base_url", sa.Text(), nullable=True),
        sa.Column("repository", sa.Text(), nullable=False),
        sa.Column(
            "auto_review",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'follow_global'"),
        ),
        sa.Column(
            "trigger",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'follow_global'"),
        ),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("setting_id"),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "gitlab_base_url",
            "repository",
            name="uq_code_review_repo_settings_user_repo",
        ),
    )

    op.create_index(
        "idx_code_review_repo_settings_user",
        "code_review_repo_settings",
        ["user_id", "provider"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_code_review_repo_settings_user",
        table_name="code_review_repo_settings",
    )
    op.drop_table("code_review_repo_settings")
    op.drop_table("code_review_profiles")
