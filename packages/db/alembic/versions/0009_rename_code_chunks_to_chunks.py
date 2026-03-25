"""rename code_chunks table to chunks

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-24
"""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("code_chunks", "chunks")
    op.execute(
        "ALTER INDEX idx_code_chunks_repository_id "
        "RENAME TO idx_chunks_repository_id"
    )
    op.execute(
        "ALTER INDEX idx_code_chunks_repository_branch "
        "RENAME TO idx_chunks_repository_branch"
    )
    op.execute(
        "ALTER INDEX idx_code_chunks_chunk_hash RENAME TO idx_chunks_chunk_hash"
    )
    op.execute(
        "ALTER INDEX idx_code_chunks_content_fts RENAME TO idx_chunks_content_fts"
    )
    op.execute(
        "ALTER TABLE chunks RENAME CONSTRAINT fk_code_chunks_repository "
        "TO fk_chunks_repository"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE chunks RENAME CONSTRAINT fk_chunks_repository "
        "TO fk_code_chunks_repository"
    )
    op.execute(
        "ALTER INDEX idx_chunks_content_fts RENAME TO idx_code_chunks_content_fts"
    )
    op.execute(
        "ALTER INDEX idx_chunks_chunk_hash RENAME TO idx_code_chunks_chunk_hash"
    )
    op.execute(
        "ALTER INDEX idx_chunks_repository_branch "
        "RENAME TO idx_code_chunks_repository_branch"
    )
    op.execute(
        "ALTER INDEX idx_chunks_repository_id "
        "RENAME TO idx_code_chunks_repository_id"
    )
    op.rename_table("chunks", "code_chunks")
