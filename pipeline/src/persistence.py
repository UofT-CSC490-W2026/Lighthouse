"""Persistence layer for index job/state writes in Postgres via SQLAlchemy."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import settings
from .contracts import IndexStage, IndexStatus
from .db_models import IndexJob, IndexState

_ENGINE: AsyncEngine | None = None
_SESSION_FACTORY: async_sessionmaker[AsyncSession] | None = None
_ENGINE_LOCK = asyncio.Lock()


@dataclass(frozen=True, slots=True)
class IndexJobWrite:
    """Typed upsert payload for `index_jobs` records."""

    job_id: str
    workflow_id: str
    repo_id: str
    ref: str
    status: IndexStatus
    stage: IndexStage | None = None
    progress_pct: int = 0
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class IndexStateWrite:
    """Typed upsert payload for `index_states` records."""

    repo_id: str
    ref: str
    status: IndexStatus
    active_job_id: str | None = None
    snapshot_sha: str | None = None
    stale_after: datetime | None = None
    last_indexed_at: datetime | None = None


async def record_runtime_index_started(
    *,
    job_id: str,
    workflow_id: str,
    repo_id: str,
    ref: str,
) -> None:
    """Persist initial `PENDING` job/state when runtime indexing begins."""
    await upsert_index_job(
        IndexJobWrite(
            job_id=job_id,
            workflow_id=workflow_id,
            repo_id=repo_id,
            ref=ref,
            status=IndexStatus.PENDING,
            stage=IndexStage.INGEST,
            progress_pct=0,
        )
    )
    await upsert_index_state(
        IndexStateWrite(
            repo_id=repo_id,
            ref=ref,
            status=IndexStatus.PENDING,
            active_job_id=job_id,
        )
    )


async def record_runtime_index_ready(
    *,
    job_id: str,
    workflow_id: str,
    repo_id: str,
    ref: str,
    snapshot_sha: str | None,
) -> None:
    """Persist terminal `READY` job/state when runtime indexing succeeds."""
    now = datetime.now(timezone.utc)
    await upsert_index_job(
        IndexJobWrite(
            job_id=job_id,
            workflow_id=workflow_id,
            repo_id=repo_id,
            ref=ref,
            status=IndexStatus.READY,
            stage=IndexStage.STORE,
            progress_pct=100,
        )
    )
    await upsert_index_state(
        IndexStateWrite(
            repo_id=repo_id,
            ref=ref,
            status=IndexStatus.READY,
            active_job_id=None,
            snapshot_sha=snapshot_sha,
            last_indexed_at=now,
        )
    )


async def record_runtime_index_progress(
    *,
    job_id: str,
    workflow_id: str,
    repo_id: str,
    ref: str,
    stage: IndexStage,
    progress_pct: int,
) -> None:
    """Persist intermediate runtime stage and percentage progress updates."""
    progress = _validate_progress(progress_pct)
    await upsert_index_job(
        IndexJobWrite(
            job_id=job_id,
            workflow_id=workflow_id,
            repo_id=repo_id,
            ref=ref,
            status=IndexStatus.PENDING,
            stage=stage,
            progress_pct=progress,
            error_code=None,
            error_message=None,
        )
    )
    await upsert_index_state(
        IndexStateWrite(
            repo_id=repo_id,
            ref=ref,
            status=IndexStatus.PENDING,
            active_job_id=job_id,
        )
    )


async def record_runtime_index_failed(
    *,
    job_id: str,
    workflow_id: str,
    repo_id: str,
    ref: str,
    stage: IndexStage | None,
    error_code: str,
    error_message: str,
    progress_pct: int = 0,
) -> None:
    """Persist terminal `FAILED` job/state and attached error metadata."""
    progress = _validate_progress(progress_pct)
    await upsert_index_job(
        IndexJobWrite(
            job_id=job_id,
            workflow_id=workflow_id,
            repo_id=repo_id,
            ref=ref,
            status=IndexStatus.FAILED,
            stage=stage,
            progress_pct=progress,
            error_code=error_code,
            error_message=error_message,
        )
    )
    await upsert_index_state(
        IndexStateWrite(
            repo_id=repo_id,
            ref=ref,
            status=IndexStatus.FAILED,
            active_job_id=None,
        )
    )


async def upsert_index_job(write: IndexJobWrite) -> None:
    """Insert or update one `index_jobs` record."""
    session_factory = await _get_session_factory()
    values = {
        "job_id": write.job_id,
        "workflow_id": write.workflow_id,
        "repo_id": write.repo_id,
        "ref": write.ref,
        "status": write.status.value,
        "stage": write.stage.value if write.stage else None,
        "progress_pct": write.progress_pct,
        "error_code": write.error_code,
        "error_message": write.error_message,
    }
    stmt = insert(IndexJob).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[IndexJob.job_id],
        set_={
            "workflow_id": stmt.excluded.workflow_id,
            "repo_id": stmt.excluded.repo_id,
            "ref": stmt.excluded.ref,
            "status": stmt.excluded.status,
            "stage": stmt.excluded.stage,
            "progress_pct": stmt.excluded.progress_pct,
            "error_code": stmt.excluded.error_code,
            "error_message": stmt.excluded.error_message,
            "updated_at": func.now(),
        },
    )
    await _execute_and_commit(session_factory, stmt)


async def upsert_index_state(write: IndexStateWrite) -> None:
    """Insert or update one `index_states` record."""
    session_factory = await _get_session_factory()
    values = {
        "repo_id": write.repo_id,
        "ref": write.ref,
        "snapshot_sha": write.snapshot_sha,
        "status": write.status.value,
        "active_job_id": write.active_job_id,
        "stale_after": write.stale_after,
        "last_indexed_at": write.last_indexed_at,
    }
    stmt = insert(IndexState).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[IndexState.repo_id, IndexState.ref],
        set_={
            "snapshot_sha": func.coalesce(
                stmt.excluded.snapshot_sha, IndexState.snapshot_sha
            ),
            "status": stmt.excluded.status,
            "active_job_id": stmt.excluded.active_job_id,
            "stale_after": func.coalesce(
                stmt.excluded.stale_after, IndexState.stale_after
            ),
            "last_indexed_at": func.coalesce(
                stmt.excluded.last_indexed_at,
                IndexState.last_indexed_at,
            ),
            "updated_at": func.now(),
        },
    )
    await _execute_and_commit(session_factory, stmt)


async def _execute_and_commit(
    session_factory: async_sessionmaker[AsyncSession],
    statement,
) -> None:
    """Execute a write statement and commit it in a short-lived session."""
    async with session_factory() as session:
        await session.execute(statement)
        await session.commit()


async def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Lazily initialize and cache the async SQLAlchemy session factory."""
    dsn = settings.postgres_dsn
    if not dsn:
        raise RuntimeError("POSTGRES_DSN is required for pipeline index persistence")

    global _ENGINE, _SESSION_FACTORY
    if _SESSION_FACTORY is not None:
        return _SESSION_FACTORY

    async with _ENGINE_LOCK:
        if _SESSION_FACTORY is None:
            _ENGINE = create_async_engine(dsn, pool_pre_ping=True)
            _SESSION_FACTORY = async_sessionmaker(
                bind=_ENGINE,
                expire_on_commit=False,
            )

    assert _SESSION_FACTORY is not None
    return _SESSION_FACTORY


async def dispose_persistence_engine() -> None:
    """Dispose cached engine/session objects, primarily for shutdown/tests."""
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        await _ENGINE.dispose()
    _ENGINE = None
    _SESSION_FACTORY = None


def _validate_progress(progress_pct: int) -> int:
    """Validate progress percentages are bounded within `[0, 100]`."""
    if progress_pct < 0 or progress_pct > 100:
        raise ValueError("progress_pct must be between 0 and 100")
    return progress_pct
