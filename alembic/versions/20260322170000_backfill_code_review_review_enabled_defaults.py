"""Backfill code review review_enabled defaults for legacy JSONB null rows

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-03-22 17:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


_LEGACY_JSONB_NULL_CONDITION = """
review_enabled IS TRUE
AND (review_triggers IS NULL OR review_triggers = 'null'::jsonb)
AND auto_fix_enabled IS FALSE
AND (auto_fix_severities IS NULL OR auto_fix_severities = 'null'::jsonb)
AND auto_fix_requires_approval IS TRUE
AND auto_publish_enabled IS FALSE
AND NOT EXISTS (
    SELECT 1
    FROM review_runs
    WHERE review_runs.repository_integration_id = repository_review_configs.repository_integration_id
)
"""


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE repository_review_configs
            SET review_enabled = FALSE
            WHERE {_LEGACY_JSONB_NULL_CONDITION}
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE repository_review_configs
            SET review_enabled = TRUE
            WHERE {_LEGACY_JSONB_NULL_CONDITION.replace("review_enabled IS TRUE", "review_enabled IS FALSE")}
            """
        )
    )
