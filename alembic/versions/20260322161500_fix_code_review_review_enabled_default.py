"""Fix code review default review_enabled flag

Revision ID: a1b2c3d4e5f6
Revises: f0f2a8d6c9b7
Create Date: 2026-03-22 16:15:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f0f2a8d6c9b7"
branch_labels = None
depends_on = None


_LEGACY_DEFAULT_SHAPE_CONDITION = """
review_enabled IS TRUE
AND review_triggers IS NULL
AND auto_fix_enabled IS FALSE
AND auto_fix_severities IS NULL
AND auto_fix_requires_approval IS TRUE
AND auto_publish_enabled IS FALSE
AND NOT EXISTS (
    SELECT 1
    FROM review_runs
    WHERE review_runs.repository_integration_id = repository_review_configs.repository_integration_id
)
"""


def upgrade() -> None:
    op.alter_column(
        "repository_review_configs",
        "review_enabled",
        existing_type=sa.Boolean(),
        server_default=sa.false(),
        existing_nullable=False,
    )
    op.execute(
        sa.text(
            f"""
            UPDATE repository_review_configs
            SET review_enabled = FALSE
            WHERE {_LEGACY_DEFAULT_SHAPE_CONDITION}
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE repository_review_configs
            SET review_enabled = TRUE
            WHERE {_LEGACY_DEFAULT_SHAPE_CONDITION.replace("review_enabled IS TRUE", "review_enabled IS FALSE")}
            """
        )
    )
    op.alter_column(
        "repository_review_configs",
        "review_enabled",
        existing_type=sa.Boolean(),
        server_default=sa.true(),
        existing_nullable=False,
    )
