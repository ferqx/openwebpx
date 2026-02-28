"""Add persistent scm_tokens table

Revision ID: 3c2f7a9b1d4e
Revises: d042a0ca1cb5
Create Date: 2026-03-01 09:30:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "3c2f7a9b1d4e"
down_revision = "d042a0ca1cb5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scm_tokens",
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("gitlab_base_url", sa.Text(), nullable=True),
        sa.Column("github_auth_mode", sa.Text(), nullable=True),
        sa.Column("token_encrypted", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("cache_key"),
    )
    op.create_index(
        "idx_scm_tokens_user_provider",
        "scm_tokens",
        ["user_id", "provider"],
    )


def downgrade() -> None:
    op.drop_index("idx_scm_tokens_user_provider", table_name="scm_tokens")
    op.drop_table("scm_tokens")
