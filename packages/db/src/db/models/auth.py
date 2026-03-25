from __future__ import annotations

from datetime import datetime, timezone
import uuid

from peewee import (
    BigIntegerField,
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKeyField,
    TextField,
)

from ..database import BaseModel


def _uuid_text() -> str:
    """Generate a UUID string for primary-key defaults."""
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    """Return the current UTC timestamp for model defaults."""
    return datetime.now(timezone.utc)


class User(BaseModel):
    """Store the Lighthouse user profile and bearer-token metadata."""

    id = CharField(primary_key=True, default=_uuid_text)
    github_id = BigIntegerField(unique=True)
    github_login = CharField()
    display_name = CharField(null=True)
    avatar_url = CharField(null=True)
    email = CharField(null=True)
    api_token_encrypted = TextField(null=True)
    api_token_hash = CharField(null=True, unique=True)
    api_token_issued_at = DateTimeField(null=True)
    mcp_token_encrypted = TextField(null=True)
    mcp_token_hash = CharField(null=True, unique=True)
    mcp_token_issued_at = DateTimeField(null=True)
    created_at = DateTimeField(default=_utcnow)
    updated_at = DateTimeField(default=_utcnow)

    class Meta:
        """Configure the Peewee table name for users."""

        table_name = "users"


class Session(BaseModel):
    """Store the latest encrypted GitHub access token for a user."""

    id = CharField(primary_key=True, default=_uuid_text)
    user = ForeignKeyField(
        User,
        backref="sessions",
        column_name="user_id",
        on_delete="CASCADE",
        index=True,
    )
    github_token_encrypted = TextField()
    expires_at = DateTimeField(index=True)
    created_at = DateTimeField(default=_utcnow)

    class Meta:
        """Configure the Peewee table name for sessions."""

        table_name = "sessions"


class Repository(BaseModel):
    """Store globally indexed repositories independently from local user records."""

    id = CharField(primary_key=True, default=_uuid_text)
    github_repo_id = BigIntegerField(unique=True)
    full_name = CharField(unique=True)
    repo_url = CharField()
    display_name = CharField()
    owner_login = CharField()
    owner_type = CharField()
    is_private = BooleanField(default=False)
    added_at = DateTimeField(default=_utcnow)

    class Meta:
        """Configure the Peewee table name for indexed repositories."""

        table_name = "repositories"


class UserHiddenRepository(BaseModel):
    """Track repositories hidden by a specific user without deleting the global record."""

    id = CharField(primary_key=True, default=_uuid_text)
    user = ForeignKeyField(
        User,
        backref="hidden_repositories",
        column_name="user_id",
        on_delete="CASCADE",
        index=True,
    )
    repository = ForeignKeyField(
        Repository,
        backref="hidden_by_users",
        column_name="repository_id",
        on_delete="CASCADE",
        index=True,
    )
    hidden_at = DateTimeField(default=_utcnow)

    class Meta:
        """Configure the Peewee table name and uniqueness for user hidden repositories."""

        table_name = "user_hidden_repositories"
        indexes = ((("user", "repository"), True),)
