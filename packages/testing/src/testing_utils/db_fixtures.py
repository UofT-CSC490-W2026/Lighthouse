from __future__ import annotations

from collections.abc import Generator

import pytest
from db import (
    Chunk,
    DatabaseManager,
    IndexedBranch,
    IndexedFile,
    Repository,
    Session,
    StagingChunk,
    StagingWikiPage,
    User,
    UserHiddenRepository,
    WikiGeneration,
    WikiPage,
)

ALL_MODELS = [
    UserHiddenRepository,
    Session,
    IndexedBranch,
    IndexedFile,
    StagingChunk,
    Chunk,
    WikiPage,
    StagingWikiPage,
    WikiGeneration,
    Repository,
    User,
]


def _rebind_database_manager(manager: DatabaseManager) -> None:
    """Force a fresh Peewee proxy binding for the shared manager."""
    manager._database = None  # noqa: SLF001
    manager.connect()


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
    _rebind_database_manager(db_manager_session)
    yield db_manager_session
    _rebind_database_manager(db_manager_session)
    with db_manager_session.connection_context():
        for model in ALL_MODELS:
            model.delete().execute()
