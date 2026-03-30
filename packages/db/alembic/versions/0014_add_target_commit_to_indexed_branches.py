"""add target commit to indexed branches

Revision ID: 0014_add_target_commit_to_indexed_branches
Revises: 0013_add_publish_tracking_for_incremental_indexing
Create Date: 2026-03-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0014_add_target_commit_to_indexed_branches"
down_revision: str | Sequence[str] | None = "0013_add_publish_tracking_for_incremental_indexing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "indexed_branches",
        sa.Column("target_commit", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("indexed_branches", "target_commit")
