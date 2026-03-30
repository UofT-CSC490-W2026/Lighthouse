"""add target commit to indexed branches

Revision ID: 0014
Revises: 0013
Create Date: 2026-03-29 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "indexed_branches",
        sa.Column("target_commit", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("indexed_branches", "target_commit")
