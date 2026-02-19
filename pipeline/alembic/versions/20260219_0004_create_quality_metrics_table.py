"""create quality_metrics table

Revision ID: 20260219_0004
Revises: 20260219_0003
Create Date: 2026-02-19 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260219_0004"
down_revision = "20260219_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create quality metric storage table and supporting index."""
    op.create_table(
        "quality_metrics",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("metric_name", sa.String(), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("metric_context", sa.Text(), nullable=True),
        sa.Column("workflow_id", sa.String(), nullable=True),
        sa.Column("dataset_name", sa.String(), nullable=True),
        sa.Column("dataset_version", sa.String(), nullable=True),
        sa.Column(
            "measured_at",
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
            "metric_value >= 0",
            name="ck_quality_metrics_metric_value_non_negative",
        ),
        sa.PrimaryKeyConstraint(
            "run_id",
            "metric_name",
            name="pk_quality_metrics",
        ),
    )
    op.create_index(
        "idx_quality_metrics_dataset",
        "quality_metrics",
        ["dataset_name", "dataset_version"],
    )


def downgrade() -> None:
    """Drop quality metric table and related index."""
    op.drop_index("idx_quality_metrics_dataset", table_name="quality_metrics")
    op.drop_table("quality_metrics")

