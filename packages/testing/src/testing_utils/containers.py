from __future__ import annotations

from collections.abc import Generator

import pytest
from testcontainers.milvus import MilvusContainer
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def pg_container() -> Generator[PostgresContainer, None, None]:
    """Start a Postgres container once per test session."""
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def pg_dsn(pg_container: PostgresContainer) -> str:
    """Return the DSN for the running Postgres testcontainer.

    Peewee's playhouse.db_url expects ``postgresql://`` (no driver suffix),
    but testcontainers returns ``postgresql+psycopg2://``.  Strip the driver.
    """
    url = pg_container.get_connection_url()
    return url.replace("postgresql+psycopg2://", "postgresql://").replace(
        "postgres+psycopg2://", "postgresql://"
    )


@pytest.fixture(scope="session")
def milvus_container() -> Generator[MilvusContainer, None, None]:
    """Start a Milvus container once per test session."""
    with MilvusContainer("milvusdb/milvus:v2.4.4") as container:
        yield container


@pytest.fixture(scope="session")
def milvus_uri(milvus_container: MilvusContainer) -> str:
    """Return the URI for the running Milvus testcontainer."""
    host = milvus_container.get_container_host_ip()
    port = milvus_container.get_exposed_port(19530)
    return f"http://{host}:{port}"
