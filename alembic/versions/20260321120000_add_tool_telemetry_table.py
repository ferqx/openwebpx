"""Add tool telemetry table for agent performance analysis

Revision ID: c8b3e5d02g21
Revises: 6fd5c9f2a1b4
Create Date: 2026-03-21 12:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision = "c8b3e5d02g21"
down_revision = "6fd5c9f2a1b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_telemetry",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("is_success", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("idx_tool_telemetry_thread_id", "tool_telemetry", ["thread_id"])
    op.create_index("idx_tool_telemetry_tool_name", "tool_telemetry", ["tool_name"])
    op.create_index("idx_tool_telemetry_error_code", "tool_telemetry", ["error_code"])


def downgrade() -> None:
    op.drop_index("idx_tool_telemetry_error_code", table_name="tool_telemetry")
    op.drop_index("idx_tool_telemetry_tool_name", table_name="tool_telemetry")
    op.drop_index("idx_tool_telemetry_thread_id", table_name="tool_telemetry")
    op.drop_table("tool_telemetry")
