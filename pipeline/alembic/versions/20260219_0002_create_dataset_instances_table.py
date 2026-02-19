"""create dataset_instances table

Revision ID: 20260219_0002
Revises: 20260218_0001
Create Date: 2026-02-19 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260219_0002"
down_revision = "20260218_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create offline gold export table and supporting secondary indexes."""
    op.create_table(
        "dataset_instances",
        sa.Column("dataset_name", sa.String(), nullable=False),
        sa.Column("dataset_version", sa.String(), nullable=False),
        sa.Column("instance_id", sa.String(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("snapshot_sha", sa.String(), nullable=True),
        sa.Column("failure_type", sa.String(), nullable=False),
        sa.Column("failure_ref", sa.Text(), nullable=True),
        sa.Column("corrected_diff_ref", sa.Text(), nullable=False),
        sa.Column("split", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.String(), nullable=True),
        sa.Column("run_id", sa.String(), nullable=True),
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
        sa.PrimaryKeyConstraint(
            "dataset_name",
            "dataset_version",
            "instance_id",
            name="pk_dataset_instances",
        ),
    )
    op.create_index("idx_dataset_instances_repo_id", "dataset_instances", ["repo_id"])
    op.create_index("idx_dataset_instances_split", "dataset_instances", ["split"])


def downgrade() -> None:
    """Drop offline gold export table and related indexes."""
    op.drop_index("idx_dataset_instances_split", table_name="dataset_instances")
    op.drop_index("idx_dataset_instances_repo_id", table_name="dataset_instances")
    op.drop_table("dataset_instances")

