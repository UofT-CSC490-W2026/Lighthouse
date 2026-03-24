"""add soft delete support to user_repos

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_repos", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_user_repos_deleted_at", "user_repos", ["deleted_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_user_repos_deleted_at", table_name="user_repos")
    op.drop_column("user_repos", "deleted_at")
