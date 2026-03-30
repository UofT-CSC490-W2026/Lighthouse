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


class WikiGeneration(BaseModel):
    """Track the status of a wiki generation run for a repository branch."""

    id = CharField(primary_key=True, default=_uuid_text)
    repository = ForeignKeyField(
        Repository,
        backref="wiki_generations",
        column_name="repository_id",
        on_delete="CASCADE",
        index=True,
    )
    branch = CharField()
    status = CharField(default="pending")
    wiki_title = CharField(null=True)
    wiki_description = TextField(null=True)
    structure_json = TextField(null=True)
    page_count = IntegerField(default=0)
    created_at = DateTimeField(default=_utcnow)
    updated_at = DateTimeField(default=_utcnow)

    class Meta:
        table_name = "wiki_generations"


class WikiPage(BaseModel):
    """A single generated wiki page."""

    id = CharField(primary_key=True, default=_uuid_text)
    wiki_generation = ForeignKeyField(
        WikiGeneration,
        backref="pages",
        column_name="wiki_generation_id",
        on_delete="CASCADE",
        index=True,
    )
    repository = ForeignKeyField(
        Repository,
        backref="wiki_pages",
        column_name="repository_id",
        on_delete="CASCADE",
        index=True,
    )
    branch = CharField()
    slug = CharField()
    title = CharField()
    content = TextField()
    section_path = CharField()
    related_pages = TextField(null=True)
    source_files = TextField(null=True)
    created_at = DateTimeField(default=_utcnow)
    updated_at = DateTimeField(default=_utcnow)

    class Meta:
        table_name = "wiki_pages"
        indexes = ((("wiki_generation", "slug"), True),)


class StagingWikiPage(BaseModel):
    """Temporary staging table for wiki pages between Temporal activities."""

    id = CharField(primary_key=True, default=_uuid_text)
    batch_id = CharField(index=True)
    seq_index = IntegerField()
    repository_id = CharField()
    branch = CharField()
    slug = CharField()
    title = CharField()
    content = TextField(default="")
    section_path = CharField()
    related_pages = TextField(null=True)
    source_files = TextField(null=True)
    embedding = BlobField(null=True)
    created_at = DateTimeField(default=_utcnow)

    class Meta:
        table_name = "staging_wiki_pages"
        indexes = ((("batch_id", "seq_index"), False),)
