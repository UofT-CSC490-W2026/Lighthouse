"""Milvus connector primitives for pipeline runtime checks."""

from __future__ import annotations

from uuid import uuid4

from pymilvus import connections, utility


class MilvusConnector:
    """Minimal Milvus connector with connectivity probe support."""

    def __init__(
        self,
        *,
        uri: str,
        user: str | None = None,
        password: str | None = None,
        database: str = "default",
    ) -> None:
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database

    def check_connection(self) -> None:
        """Open and close a temporary Milvus connection and list collections."""
        alias = f"pipeline_probe_{uuid4().hex[:8]}"
        try:
            connections.connect(
                alias=alias,
                uri=self.uri,
                user=self.user,
                password=self.password,
                db_name=self.database,
            )
            utility.list_collections(using=alias)
        finally:
            connections.disconnect(alias=alias)
