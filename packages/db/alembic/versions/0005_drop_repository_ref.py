"""drop ref from repositories

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("repositories", "ref")


def downgrade() -> None:
    op.add_column(
        "repositories",
        sa.Column("ref", sa.String(), nullable=False, server_default="main"),
    )
