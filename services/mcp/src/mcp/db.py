"""Database access layer using asyncpg."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime

import asyncpg

from .config import settings


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: str
    github_id: int
    github_login: str
    display_name: str | None
    avatar_url: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: str
    user_id: str
    github_token_encrypted: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class UserRepoRecord:
    id: str
    user_id: str
    repo_id: str
    repo_url: str
    display_name: str
    ref: str
    added_at: datetime | None


_pool: asyncpg.Pool | None = None
_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    async with _lock:
        if _pool is None:
            _pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=5)
    assert _pool is not None
    return _pool


# ── Users ───────────────────────────────────────────────


async def upsert_user(
    *,
    github_id: int,
    github_login: str,
    display_name: str | None = None,
    avatar_url: str | None = None,
    email: str | None = None,
) -> UserRecord:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO users (id, github_id, github_login, display_name, avatar_url, email)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (github_id) DO UPDATE SET
            github_login = EXCLUDED.github_login,
            display_name = EXCLUDED.display_name,
            avatar_url   = EXCLUDED.avatar_url,
            email        = EXCLUDED.email,
            updated_at   = NOW()
        RETURNING id, github_id, github_login, display_name, avatar_url, email
        """,
        str(uuid.uuid4()),
        github_id,
        github_login,
        display_name,
        avatar_url,
        email,
    )
    return UserRecord(**dict(row))


async def get_user(user_id: str) -> UserRecord | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, github_id, github_login, display_name, avatar_url, email FROM users WHERE id = $1",
        user_id,
    )
    return UserRecord(**dict(row)) if row else None


# ── Sessions ────────────────────────────────────────────


async def create_session(
    *, user_id: str, github_token_encrypted: str, expires_at: datetime
) -> SessionRecord:
    pool = await get_pool()
    session_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """
        INSERT INTO sessions (id, user_id, github_token_encrypted, expires_at)
        VALUES ($1, $2, $3, $4)
        RETURNING id, user_id, github_token_encrypted, expires_at
        """,
        session_id,
        user_id,
        github_token_encrypted,
        expires_at,
    )
    return SessionRecord(**dict(row))


async def get_session(session_id: str) -> SessionRecord | None:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, user_id, github_token_encrypted, expires_at
        FROM sessions
        WHERE id = $1 AND expires_at > NOW()
        """,
        session_id,
    )
    return SessionRecord(**dict(row)) if row else None


async def delete_session(session_id: str) -> None:
    pool = await get_pool()
    await pool.execute("DELETE FROM sessions WHERE id = $1", session_id)


# ── User Repos ──────────────────────────────────────────


async def add_repo(
    *,
    user_id: str,
    repo_id: str,
    repo_url: str,
    display_name: str,
    ref: str = "main",
) -> UserRepoRecord:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO user_repos (id, user_id, repo_id, repo_url, display_name, ref)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT ON CONSTRAINT uq_user_repos_user_repo DO UPDATE SET
            repo_url     = EXCLUDED.repo_url,
            display_name = EXCLUDED.display_name,
            ref          = EXCLUDED.ref
        RETURNING id, user_id, repo_id, repo_url, display_name, ref, added_at
        """,
        str(uuid.uuid4()),
        user_id,
        repo_id,
        repo_url,
        display_name,
        ref,
    )
    return UserRepoRecord(**dict(row))


async def list_repos(user_id: str) -> list[UserRepoRecord]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, user_id, repo_id, repo_url, display_name, ref, added_at
        FROM user_repos WHERE user_id = $1 ORDER BY added_at DESC
        """,
        user_id,
    )
    return [UserRepoRecord(**dict(r)) for r in rows]


async def delete_repo(*, user_id: str, repo_id: str) -> bool:
    pool = await get_pool()
    result = await pool.execute(
        "DELETE FROM user_repos WHERE user_id = $1 AND repo_id = $2",
        user_id,
        repo_id,
    )
    return result != "DELETE 0"
