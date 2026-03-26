from __future__ import annotations

from collections.abc import Generator

import pytest
from db import (
    Chunk,
    DatabaseManager,
    IndexedBranch,
    Repository,
    Session,
    StagingChunk,
    User,
    UserHiddenRepository,
)

ALL_MODELS = [
    UserHiddenRepository,
    Session,
    IndexedBranch,
    StagingChunk,
    Chunk,
    Repository,
    User,
]


@pytest.fixture(scope="session")
def db_manager_session(pg_dsn: str) -> Generator[DatabaseManager, None, None]:
    """Session-scoped: create a DatabaseManager, connect, and create all tables."""
    mgr = DatabaseManager(pg_dsn)
    mgr.connect()
    mgr.database.create_tables(ALL_MODELS)
    yield mgr
    mgr.close()


@pytest.fixture
def db_manager(db_manager_session: DatabaseManager) -> Generator[DatabaseManager, None, None]:
    """Function-scoped: yield the shared manager, then truncate all tables for isolation."""
    yield db_manager_session
    with db_manager_session.connection_context():
        for model in ALL_MODELS:
            model.delete().execute()
