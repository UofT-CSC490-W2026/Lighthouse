from __future__ import annotations

from datetime import datetime, timezone
import uuid

from peewee import BigIntegerField, CharField, DateTimeField, ForeignKeyField, TextField

from .database import BaseModel


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
    created_at = DateTimeField(default=_utcnow)
    updated_at = DateTimeField(default=_utcnow)

    class Meta:
        """Configure the Peewee table name for users."""

        table_name = "users"


class Session(BaseModel):
    """Store legacy GitHub session data while the schema still carries it."""

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


class UserRepo(BaseModel):
    """Store repositories linked to a user, including soft-delete state."""

    id = CharField(primary_key=True, default=_uuid_text)
    user = ForeignKeyField(
        User,
        backref="repos",
        column_name="user_id",
        on_delete="CASCADE",
        index=True,
    )
    repo_id = CharField()
    repo_url = CharField()
    display_name = CharField()
    ref = CharField(default="main")
    added_at = DateTimeField(default=_utcnow)
    deleted_at = DateTimeField(null=True, index=True)

    class Meta:
        """Configure the Peewee table name and uniqueness constraints for user repos."""

        table_name = "user_repos"
        indexes = ((("user", "repo_id"), True),)
