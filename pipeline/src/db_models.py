"""SQLAlchemy models for pipeline persistence tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative SQLAlchemy base for pipeline persistence models."""

    pass


class IndexJob(Base):
    """Runtime index job lifecycle table keyed by `job_id`."""

    __tablename__ = "index_jobs"
    __table_args__ = (
        CheckConstraint(
            "progress_pct >= 0 AND progress_pct <= 100",
            name="ck_index_jobs_progress_pct",
        ),
        Index("idx_index_jobs_repo_ref", "repo_id", "ref"),
        Index("idx_index_jobs_workflow_id", "workflow_id"),
    )

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String, nullable=False)
    repo_id: Mapped[str] = mapped_column(String, nullable=False)
    ref: Mapped[str] = mapped_column(String, nullable=False, default="main")
    status: Mapped[str] = mapped_column(String, nullable=False)
    stage: Mapped[str | None] = mapped_column(String, nullable=True)
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class IndexState(Base):
    """Current repo/ref readiness state table keyed by `(repo_id, ref)`."""

    __tablename__ = "index_states"
    __table_args__ = (Index("idx_index_states_status", "status"),)

    repo_id: Mapped[str] = mapped_column(String, primary_key=True)
    ref: Mapped[str] = mapped_column(String, primary_key=True, default="main")
    snapshot_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    active_job_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("index_jobs.job_id", ondelete="SET NULL"),
        nullable=True,
    )
    stale_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class DatasetInstance(Base):
    """Offline gold dataset export table for normalized benchmark instances."""

    __tablename__ = "dataset_instances"
    __table_args__ = (
        PrimaryKeyConstraint(
            "dataset_name",
            "dataset_version",
            "instance_id",
            name="pk_dataset_instances",
        ),
        Index("idx_dataset_instances_repo_id", "repo_id"),
        Index("idx_dataset_instances_split", "split"),
    )

    dataset_name: Mapped[str] = mapped_column(String, nullable=False)
    dataset_version: Mapped[str] = mapped_column(String, nullable=False)
    instance_id: Mapped[str] = mapped_column(String, nullable=False)

    task: Mapped[str] = mapped_column(Text, nullable=False)
    repo_id: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_type: Mapped[str] = mapped_column(String, nullable=False)
    failure_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_diff_ref: Mapped[str] = mapped_column(Text, nullable=False)
    split: Mapped[str] = mapped_column(String, nullable=False)

    workflow_id: Mapped[str | None] = mapped_column(String, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
