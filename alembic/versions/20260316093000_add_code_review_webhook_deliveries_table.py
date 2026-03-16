"""Add code review webhook deliveries table

Revision ID: b7a2d4c91f10
Revises: 6fd5c9f2a1b4
Create Date: 2026-03-16 09:30:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b7a2d4c91f10"
down_revision = "6fd5c9f2a1b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "code_review_webhook_deliveries",
        sa.Column("delivery_key", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("delivery_id", sa.Text(), nullable=False),
        sa.Column("repository", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("delivery_key"),
    )

    op.create_index(
        "idx_code_review_webhook_deliveries_lookup",
        "code_review_webhook_deliveries",
        ["user_id", "provider", "delivery_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_code_review_webhook_deliveries_lookup",
        table_name="code_review_webhook_deliveries",
    )
    op.drop_table("code_review_webhook_deliveries")
