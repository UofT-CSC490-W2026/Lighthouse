"""create indexed_branches and code_chunks tables

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "indexed_branches",
        sa.Column(
            "id",
            sa.String(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()::text"),
        ),
        sa.Column("repository_id", sa.String(), nullable=False),
        sa.Column("branch_name", sa.String(), nullable=False),
        sa.Column("last_indexed_commit", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("github_token_encrypted", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
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
            name="fk_indexed_branches_repository",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_id",
            "branch_name",
            name="uq_indexed_branches_repository_branch",
        ),
    )
    op.create_index(
        "idx_indexed_branches_repository_id",
        "indexed_branches",
        ["repository_id"],
        unique=False,
    )
    op.create_index(
        "idx_indexed_branches_status",
        "indexed_branches",
        ["status"],
        unique=False,
    )

    op.create_table(
        "code_chunks",
        sa.Column(
            "id",
            sa.String(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()::text"),
        ),
        sa.Column("repository_id", sa.String(), nullable=False),
        sa.Column("branch", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("chunk_hash", sa.String(), nullable=False),
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
            name="fk_code_chunks_repository",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_code_chunks_repository_id",
        "code_chunks",
        ["repository_id"],
        unique=False,
    )
    op.create_index(
        "idx_code_chunks_repository_branch",
        "code_chunks",
        ["repository_id", "branch"],
        unique=False,
    )
    op.create_index(
        "idx_code_chunks_chunk_hash",
        "code_chunks",
        ["chunk_hash"],
        unique=False,
    )
    # GIN index for PostgreSQL full-text search
    op.execute(
        "CREATE INDEX idx_code_chunks_content_fts "
        "ON code_chunks USING GIN (to_tsvector('english', content))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_code_chunks_content_fts")
    op.drop_index("idx_code_chunks_chunk_hash", table_name="code_chunks")
    op.drop_index("idx_code_chunks_repository_branch", table_name="code_chunks")
    op.drop_index("idx_code_chunks_repository_id", table_name="code_chunks")
    op.drop_table("code_chunks")

    op.drop_index("idx_indexed_branches_status", table_name="indexed_branches")
    op.drop_index(
        "idx_indexed_branches_repository_id", table_name="indexed_branches"
    )
    op.drop_table("indexed_branches")
