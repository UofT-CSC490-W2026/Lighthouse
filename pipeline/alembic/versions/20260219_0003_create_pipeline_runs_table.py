"""create pipeline_runs table

Revision ID: 20260219_0003
Revises: 20260219_0002
Create Date: 2026-02-19 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260219_0003"
down_revision = "20260219_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create per-run metrics table and secondary indexes."""
    op.create_table(
        "pipeline_runs",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=False),
        sa.Column("workflow_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("repo_id", sa.String(), nullable=True),
        sa.Column("ref", sa.String(), nullable=True),
        sa.Column("dataset_name", sa.String(), nullable=True),
        sa.Column("dataset_version", sa.String(), nullable=True),
        sa.Column("trigger", sa.String(), nullable=True),
        sa.Column("requested_by", sa.String(), nullable=True),
        sa.Column("source_event_id", sa.String(), nullable=True),
        sa.Column("records_in", sa.Integer(), nullable=True),
        sa.Column("records_out", sa.Integer(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            "records_in IS NULL OR records_in >= 0",
            name="ck_pipeline_runs_records_in_non_negative",
        ),
        sa.CheckConstraint(
            "records_out IS NULL OR records_out >= 0",
            name="ck_pipeline_runs_records_out_non_negative",
        ),
        sa.CheckConstraint(
            "failure_count IS NULL OR failure_count >= 0",
            name="ck_pipeline_runs_failure_count_non_negative",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_pipeline_runs_duration_ms_non_negative",
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "idx_pipeline_runs_workflow_type", "pipeline_runs", ["workflow_type"]
    )
    op.create_index("idx_pipeline_runs_status", "pipeline_runs", ["status"])
    op.create_index(
        "idx_pipeline_runs_dataset",
        "pipeline_runs",
        ["dataset_name", "dataset_version"],
    )


def downgrade() -> None:
    """Drop per-run metrics table and indexes."""
    op.drop_index("idx_pipeline_runs_dataset", table_name="pipeline_runs")
    op.drop_index("idx_pipeline_runs_status", table_name="pipeline_runs")
    op.drop_index("idx_pipeline_runs_workflow_type", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
