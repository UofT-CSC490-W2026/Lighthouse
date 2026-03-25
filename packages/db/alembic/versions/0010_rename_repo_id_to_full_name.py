"""rename repo_id to full_name and make github_repo_id non-nullable

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-24
"""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "repositories",
        "repo_id",
        new_column_name="full_name",
    )
    op.execute(
        "ALTER TABLE repositories "
        "RENAME CONSTRAINT uq_repositories_repo_id TO uq_repositories_full_name"
    )
    op.alter_column(
        "repositories",
        "github_repo_id",
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "repositories",
        "github_repo_id",
        nullable=True,
    )
    op.execute(
        "ALTER TABLE repositories "
        "RENAME CONSTRAINT uq_repositories_full_name TO uq_repositories_repo_id"
    )
    op.alter_column(
        "repositories",
        "full_name",
        new_column_name="repo_id",
    )
