"""Postgres connector primitives for pipeline runtime checks."""

from __future__ import annotations

import asyncio

import asyncpg


class PostgresConnector:
    """Asyncpg-based Postgres connector with lightweight health probe."""

    def __init__(self, *, dsn: str, min_pool_size: int = 1, max_pool_size: int = 5):
        self.dsn = dsn
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    async def get_pool(self) -> asyncpg.Pool:
        """Lazily initialize and return a pooled asyncpg connection."""
        if self._pool is not None:
            return self._pool

        async with self._lock:
            if self._pool is None:
                self._pool = await asyncpg.create_pool(
                    dsn=self.dsn,
                    min_size=self.min_pool_size,
                    max_size=self.max_pool_size,
                )

        assert self._pool is not None
        return self._pool

    async def check_connection(self) -> None:
        """Verify connectivity by issuing `SELECT 1`."""
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
