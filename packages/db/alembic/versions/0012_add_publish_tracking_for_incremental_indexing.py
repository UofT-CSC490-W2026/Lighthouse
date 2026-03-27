"""add publish tracking for incremental indexing

Revision ID: 0012
Revises: 0011
Create Date: 2026-03-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chunks",
        sa.Column(
            "publish_id",
            sa.String(),
            nullable=False,
            server_default=sa.text("'legacy'"),
        ),
    )
    op.create_index(
        "idx_chunks_repository_branch_file_publish",
        "chunks",
        ["repository_id", "branch", "file_path", "publish_id"],
        unique=False,
    )

    op.create_table(
        "indexed_files",
        sa.Column(
            "id",
            sa.String(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()::text"),
        ),
        sa.Column("repository_id", sa.String(), nullable=False),
        sa.Column("branch_name", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("active_publish_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name="fk_indexed_files_repository",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_id",
            "branch_name",
            "file_path",
            name="uq_indexed_files_repository_branch_file",
        ),
    )
    op.create_index(
        "idx_indexed_files_repository_branch",
        "indexed_files",
        ["repository_id", "branch_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_indexed_files_repository_branch",
        table_name="indexed_files",
    )
    op.drop_table("indexed_files")

    op.drop_index(
        "idx_chunks_repository_branch_file_publish",
        table_name="chunks",
    )
    op.drop_column("chunks", "publish_id")
