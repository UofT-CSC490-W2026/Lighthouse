"""replace global repo deletes with per-user hidden repositories

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_hidden_repositories",
        sa.Column(
            "id",
            sa.String(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()::text"),
        ),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("repository_id", sa.String(), nullable=False),
        sa.Column(
            "hidden_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_hidden_repositories_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name="fk_user_hidden_repositories_repository",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "repository_id",
            name="uq_user_hidden_repositories_user_repository",
        ),
    )
    op.create_index(
        "idx_user_hidden_repositories_user_id",
        "user_hidden_repositories",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "idx_user_hidden_repositories_repository_id",
        "user_hidden_repositories",
        ["repository_id"],
        unique=False,
    )

    op.drop_index("idx_repositories_deleted_at", table_name="repositories")
    op.drop_column("repositories", "deleted_at")


def downgrade() -> None:
    op.add_column(
        "repositories",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_repositories_deleted_at",
        "repositories",
        ["deleted_at"],
        unique=False,
    )

    op.drop_index(
        "idx_user_hidden_repositories_repository_id",
        table_name="user_hidden_repositories",
    )
    op.drop_index(
        "idx_user_hidden_repositories_user_id",
        table_name="user_hidden_repositories",
    )
    op.drop_table("user_hidden_repositories")
