"""create wiki_generations, wiki_pages, and staging_wiki_pages tables

Revision ID: 0012
Revises: 0011
Create Date: 2026-03-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wiki_generations",
        sa.Column(
            "id",
            sa.String(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()::text"),
        ),
        sa.Column("repository_id", sa.String(), nullable=False),
        sa.Column("branch", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("wiki_title", sa.String(), nullable=True),
        sa.Column("wiki_description", sa.Text(), nullable=True),
        sa.Column("structure_json", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_wiki_gen_repository",
        "wiki_generations",
        ["repository_id"],
    )

    op.create_table(
        "wiki_pages",
        sa.Column(
            "id",
            sa.String(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()::text"),
        ),
        sa.Column("wiki_generation_id", sa.String(), nullable=False),
        sa.Column("repository_id", sa.String(), nullable=False),
        sa.Column("branch", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("section_path", sa.String(), nullable=False),
        sa.Column("related_pages", sa.Text(), nullable=True),
        sa.Column("source_files", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["wiki_generation_id"],
            ["wiki_generations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("wiki_generation_id", "slug", name="uq_wiki_page_gen_slug"),
    )
    op.create_index(
        "idx_wiki_page_repository",
        "wiki_pages",
        ["repository_id"],
    )
    op.create_index(
        "idx_wiki_page_generation",
        "wiki_pages",
        ["wiki_generation_id"],
    )

    op.create_table(
        "staging_wiki_pages",
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
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("section_path", sa.String(), nullable=False),
        sa.Column("related_pages", sa.Text(), nullable=True),
        sa.Column("source_files", sa.Text(), nullable=True),
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
        "idx_staging_wiki_batch_seq",
        "staging_wiki_pages",
        ["batch_id", "seq_index"],
    )


def downgrade() -> None:
    op.drop_index("idx_staging_wiki_batch_seq", table_name="staging_wiki_pages")
    op.drop_table("staging_wiki_pages")
    op.drop_index("idx_wiki_page_generation", table_name="wiki_pages")
    op.drop_index("idx_wiki_page_repository", table_name="wiki_pages")
    op.drop_table("wiki_pages")
    op.drop_index("idx_wiki_gen_repository", table_name="wiki_generations")
    op.drop_table("wiki_generations")
