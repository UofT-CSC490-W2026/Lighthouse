"""Read repository for index job and repo state records."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

import asyncpg

from ..utils import settings


@dataclass(frozen=True, slots=True)
class IndexJobRecord:
    job_id: str
    workflow_id: str
    repo_id: str
    ref: str
    status: str
    stage: str | None
    progress_pct: int
    error_code: str | None
    error_message: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class IndexStateRecord:
    repo_id: str
    ref: str
    status: str
    snapshot_sha: str | None
    active_job_id: str | None
    stale_after: datetime | None
    last_indexed_at: datetime | None
    updated_at: datetime | None


class IndexRepository:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    async def get_job(self, job_id: str) -> IndexJobRecord | None:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            SELECT
                job_id,
                workflow_id,
                repo_id,
                ref,
                status,
                stage,
                progress_pct,
                error_code,
                error_message,
                created_at,
                updated_at
            FROM index_jobs
            WHERE job_id = $1
            """,
            job_id,
        )
        if row is None:
            return None
        return IndexJobRecord(**dict(row))

    async def get_repo_state(self, repo_id: str, ref: str) -> IndexStateRecord | None:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            SELECT
                repo_id,
                ref,
                status,
                snapshot_sha,
                active_job_id,
                stale_after,
                last_indexed_at,
                updated_at
            FROM index_states
            WHERE repo_id = $1 AND ref = $2
            """,
            repo_id,
            ref,
        )
        if row is None:
            return None
        return IndexStateRecord(**dict(row))

    async def find_active_job_id(self, repo_id: str, ref: str) -> str | None:
        pool = await self._get_pool()
        row = await pool.fetchrow(
            """
            SELECT active_job_id
            FROM index_states
            WHERE repo_id = $1 AND ref = $2
            """,
            repo_id,
            ref,
        )
        if row is None:
            return None
        return row["active_job_id"]

    async def _get_pool(self) -> asyncpg.Pool:
        dsn = settings.postgres_dsn
        if not dsn:
            raise RuntimeError("POSTGRES_DSN is required for MCP index-control reads")

        if self._pool is not None:
            return self._pool

        async with self._lock:
            if self._pool is None:
                self._pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)

        assert self._pool is not None
        return self._pool
