"""create staging_chunks table for inter-activity data passing

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "staging_chunks",
        sa.Column(
            "id",
            sa.String(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()::text"),
        ),
        sa.Column("batch_id", sa.String(), nullable=False),
        sa.Column("seq_index", sa.Integer(), nullable=False),
        sa.Column("repository_id", sa.String(), nullable=False),
        sa.Column("branch", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("chunk_hash", sa.String(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_staging_batch_seq",
        "staging_chunks",
        ["batch_id", "seq_index"],
        unique=False,
    )
    op.create_index(
        "idx_staging_created",
        "staging_chunks",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_staging_created", table_name="staging_chunks")
    op.drop_index("idx_staging_batch_seq", table_name="staging_chunks")
    op.drop_table("staging_chunks")
