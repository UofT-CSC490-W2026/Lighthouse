"""add dedicated mcp token fields to users

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mcp_token_encrypted", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("mcp_token_hash", sa.String(), nullable=True))
    op.add_column("users", sa.Column("mcp_token_issued_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_users_mcp_token_hash", "users", ["mcp_token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_users_mcp_token_hash", table_name="users")
    op.drop_column("users", "mcp_token_issued_at")
    op.drop_column("users", "mcp_token_hash")
    op.drop_column("users", "mcp_token_encrypted")
