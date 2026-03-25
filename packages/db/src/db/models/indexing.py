from __future__ import annotations

from datetime import datetime, timezone
import uuid

from peewee import (
    CharField,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    TextField,
)

from ..database import BaseModel
from .auth import Repository


def _uuid_text() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IndexedBranch(BaseModel):
    """Track indexing status for a specific branch of a repository."""

    id = CharField(primary_key=True, default=_uuid_text)
    repository = ForeignKeyField(
        Repository,
        backref="indexed_branches",
        column_name="repository_id",
        on_delete="CASCADE",
        index=True,
    )
    branch_name = CharField()
    last_indexed_commit = CharField(null=True)
    status = CharField(default="pending")
    github_token_encrypted = TextField(null=True)
    indexed_at = DateTimeField(null=True)
    created_at = DateTimeField(default=_utcnow)
    updated_at = DateTimeField(default=_utcnow)

    class Meta:
        table_name = "indexed_branches"
        indexes = ((("repository", "branch_name"), True),)


class CodeChunk(BaseModel):
    """Store a chunk of code for keyword search and metadata."""

    id = CharField(primary_key=True, default=_uuid_text)
    repository = ForeignKeyField(
        Repository,
        backref="chunks",
        column_name="repository_id",
        on_delete="CASCADE",
        index=True,
    )
    branch = CharField()
    file_path = CharField()
    start_line = IntegerField()
    end_line = IntegerField()
    content = TextField()
    language = CharField(null=True)
    chunk_hash = CharField()
    created_at = DateTimeField(default=_utcnow)
    updated_at = DateTimeField(default=_utcnow)

    class Meta:
        table_name = "chunks"
