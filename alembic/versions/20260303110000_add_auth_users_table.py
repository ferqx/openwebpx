"""Add auth_users table for local and LDAP identities

Revision ID: 6fd5c9f2a1b4
Revises: c4d8f8b8a812
Create Date: 2026-03-03 11:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "6fd5c9f2a1b4"
down_revision = "c4d8f8b8a812"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_users",
        sa.Column("identity", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column(
            "auth_source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'local'"),
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("team_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("identity"),
    )
    op.create_index("idx_auth_users_team_id", "auth_users", ["team_id"])


def downgrade() -> None:
    op.drop_index("idx_auth_users_team_id", table_name="auth_users")
    op.drop_table("auth_users")
