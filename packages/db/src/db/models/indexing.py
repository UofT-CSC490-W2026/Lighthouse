from __future__ import annotations

from datetime import datetime, timezone
import uuid

from peewee import (
    BlobField,
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
    target_commit = CharField(null=True)
    last_indexed_commit = CharField(null=True)
    status = CharField(default="pending")
    github_token_encrypted = TextField(null=True)
    indexed_at = DateTimeField(null=True)
    created_at = DateTimeField(default=_utcnow)
    updated_at = DateTimeField(default=_utcnow)

    class Meta:
        table_name = "indexed_branches"
        indexes = ((("repository", "branch_name"), True),)


class Chunk(BaseModel):
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
    publish_id = CharField(default="legacy")
    created_at = DateTimeField(default=_utcnow)
    updated_at = DateTimeField(default=_utcnow)

    class Meta:
        table_name = "chunks"
        indexes = ((("repository", "branch", "file_path", "publish_id"), False),)


class IndexedFile(BaseModel):
    """Track the active published chunk version for a specific file."""

    id = CharField(primary_key=True, default=_uuid_text)
    repository = ForeignKeyField(
        Repository,
        backref="indexed_files",
        column_name="repository_id",
        on_delete="CASCADE",
        index=True,
    )
    branch_name = CharField()
    file_path = CharField()
    active_publish_id = CharField(null=True)
    created_at = DateTimeField(default=_utcnow)
    updated_at = DateTimeField(default=_utcnow)

    class Meta:
        table_name = "indexed_files"
        indexes = (
            (("repository", "branch_name", "file_path"), True),
            (("repository", "branch_name"), False),
        )


class StagingChunk(BaseModel):
    """Temporary staging table for chunks between Temporal activities."""

    id = CharField(primary_key=True, default=_uuid_text)
    batch_id = CharField(index=True)
    seq_index = IntegerField()
    repository_id = CharField()
    branch = CharField()
    file_path = CharField()
    start_line = IntegerField()
    end_line = IntegerField()
    content = TextField()
    language = CharField(null=True)
    chunk_hash = CharField()
    embedding = BlobField(null=True)
    created_at = DateTimeField(default=_utcnow)

    class Meta:
        table_name = "staging_chunks"
        indexes = ((("batch_id", "seq_index"), False),)
