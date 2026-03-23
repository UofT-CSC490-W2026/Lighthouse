"""add api token fields to users

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("api_token_encrypted", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("api_token_hash", sa.String(), nullable=True))
    op.add_column("users", sa.Column("api_token_issued_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_users_api_token_hash", "users", ["api_token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_users_api_token_hash", table_name="users")
    op.drop_column("users", "api_token_issued_at")
    op.drop_column("users", "api_token_hash")
    op.drop_column("users", "api_token_encrypted")
