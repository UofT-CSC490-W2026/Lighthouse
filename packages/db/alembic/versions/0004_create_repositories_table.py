"""create repositories table

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column(
            "id",
            sa.String(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()::text"),
        ),
        sa.Column("github_repo_id", sa.BigInteger(), nullable=True),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("repo_url", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("owner_login", sa.String(), nullable=False),
        sa.Column("owner_type", sa.String(), nullable=False),
        sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ref", sa.String(), nullable=False, server_default="main"),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_repo_id", name="uq_repositories_github_repo_id"),
        sa.UniqueConstraint("repo_id", name="uq_repositories_repo_id"),
    )
    op.create_index(
        "idx_repositories_deleted_at",
        "repositories",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        "idx_repositories_is_private",
        "repositories",
        ["is_private"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO repositories (
            repo_id,
            repo_url,
            display_name,
            owner_login,
            owner_type,
            is_private,
            ref,
            added_at,
            deleted_at
        )
        SELECT DISTINCT ON (repo_id)
            repo_id,
            repo_url,
            display_name,
            split_part(repo_id, '/', 1),
            'User',
            FALSE,
            ref,
            added_at,
            deleted_at
        FROM user_repos
        ORDER BY repo_id, added_at DESC
        """
    )


def downgrade() -> None:
    op.drop_index("idx_repositories_is_private", table_name="repositories")
    op.drop_index("idx_repositories_deleted_at", table_name="repositories")
    op.drop_table("repositories")
