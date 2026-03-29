from __future__ import annotations

from collections.abc import Generator
import os
from pathlib import Path

import pytest
from testcontainers.milvus import MilvusContainer
from testcontainers.postgres import PostgresContainer


DOCKER_DESKTOP_SOCKET = Path.home() / ".docker" / "run" / "docker.sock"


def _resolve_host_docker_socket() -> Path | None:
    """Return the host Docker socket path used by the local Docker daemon."""
    docker_host = os.environ.get("DOCKER_HOST")
    if docker_host and docker_host.startswith("unix://"):
        socket_path = Path(docker_host.removeprefix("unix://"))
        if socket_path.exists():
            return socket_path

    if DOCKER_DESKTOP_SOCKET.exists():
        return DOCKER_DESKTOP_SOCKET

    default_socket = Path("/var/run/docker.sock")
    if default_socket.exists():
        return default_socket

    return None


def _configure_testcontainers_docker_host() -> None:
    """Point testcontainers and Ryuk at the host Docker socket."""
    socket_path = _resolve_host_docker_socket()
    if socket_path is None:
        return

    os.environ.setdefault("DOCKER_HOST", f"unix://{socket_path}")
    if socket_path == DOCKER_DESKTOP_SOCKET:
        os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
        return

    os.environ.setdefault("TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE", str(socket_path))


@pytest.fixture(scope="session")
def pg_container() -> Generator[PostgresContainer, None, None]:
    """Start a Postgres container once per test session."""
    _configure_testcontainers_docker_host()
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
    _configure_testcontainers_docker_host()
    with MilvusContainer("milvusdb/milvus:v2.4.4") as container:
        yield container


@pytest.fixture(scope="session")
def milvus_uri(milvus_container: MilvusContainer) -> str:
    """Return the URI for the running Milvus testcontainer."""
    host = milvus_container.get_container_host_ip()
    port = milvus_container.get_exposed_port(19530)
    return f"http://{host}:{port}"
