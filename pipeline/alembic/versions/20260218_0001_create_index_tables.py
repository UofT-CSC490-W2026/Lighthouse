"""create index job and state tables

Revision ID: 20260218_0001
Revises:
Create Date: 2026-02-18 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260218_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create index lifecycle/state tables and supporting indexes."""
    op.create_table(
        "index_jobs",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("ref", sa.String(), nullable=False, server_default="main"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=True),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "progress_pct >= 0 AND progress_pct <= 100",
            name="ck_index_jobs_progress_pct",
        ),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("idx_index_jobs_repo_ref", "index_jobs", ["repo_id", "ref"])
    op.create_index("idx_index_jobs_workflow_id", "index_jobs", ["workflow_id"])

    op.create_table(
        "index_states",
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("ref", sa.String(), nullable=False, server_default="main"),
        sa.Column("snapshot_sha", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("active_job_id", sa.String(), nullable=True),
        sa.Column("stale_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["active_job_id"],
            ["index_jobs.job_id"],
            name="fk_index_states_active_job",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("repo_id", "ref"),
    )
    op.create_index("idx_index_states_status", "index_states", ["status"])


def downgrade() -> None:
    """Drop index lifecycle/state tables and their secondary indexes."""
    op.drop_index("idx_index_states_status", table_name="index_states")
    op.drop_table("index_states")
    op.drop_index("idx_index_jobs_workflow_id", table_name="index_jobs")
    op.drop_index("idx_index_jobs_repo_ref", table_name="index_jobs")
    op.drop_table("index_jobs")
