from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from db import Chunk, DatabaseManager, Repository, StagingChunk, User


def _rand_id() -> str:
    return uuid.uuid4().hex[:8]


def make_user(**overrides) -> dict:
    defaults = {
        "github_id": random.randint(1, 999_999),
        "github_login": f"testuser-{_rand_id()}",
        "display_name": "Test User",
        "avatar_url": "https://example.com/avatar.png",
        "email": "test@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_user(db_manager: DatabaseManager, **overrides) -> User:
    with db_manager.connection_context():
        return User.create(**make_user(**overrides))


def make_repository(**overrides) -> dict:
    rid = _rand_id()
    defaults = {
        "github_repo_id": random.randint(1, 999_999),
        "full_name": f"testowner/testrepo-{rid}",
        "repo_url": f"https://github.com/testowner/testrepo-{rid}",
        "display_name": f"testrepo-{rid}",
        "owner_login": "testowner",
        "owner_type": "User",
        "is_private": False,
    }
    defaults.update(overrides)
    return defaults


def create_repository(db_manager: DatabaseManager, **overrides) -> Repository:
    with db_manager.connection_context():
        return Repository.create(**make_repository(**overrides))


def make_chunk(repository_id: str, **overrides) -> dict:
    defaults = {
        "repository_id": repository_id,
        "branch": "main",
        "file_path": f"src/test_{_rand_id()}.py",
        "start_line": 1,
        "end_line": 10,
        "content": f"def test_func_{_rand_id()}():\n    pass\n",
        "language": "python",
        "chunk_hash": uuid.uuid4().hex,
    }
    defaults.update(overrides)
    return defaults


def create_chunk(db_manager: DatabaseManager, repository: Repository, **overrides) -> Chunk:
    with db_manager.connection_context():
        return Chunk.create(**make_chunk(repository.id, **overrides))


def make_staging_chunk(batch_id: str, seq_index: int, repository_id: str, **overrides) -> dict:
    defaults = {
        "batch_id": batch_id,
        "seq_index": seq_index,
        "repository_id": repository_id,
        "branch": "main",
        "file_path": f"src/file_{_rand_id()}.py",
        "start_line": 1,
        "end_line": 10,
        "content": f"# chunk content {_rand_id()}",
        "language": "python",
        "chunk_hash": uuid.uuid4().hex,
    }
    defaults.update(overrides)
    return defaults


def create_staging_chunk(
    db_manager: DatabaseManager, batch_id: str, seq_index: int, repository_id: str, **overrides
) -> StagingChunk:
    with db_manager.connection_context():
        return StagingChunk.create(
            **make_staging_chunk(batch_id, seq_index, repository_id, **overrides)
        )
