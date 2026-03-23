from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlparse

from fastapi import Body
from pydantic import BaseModel

from ..models import UserRepo
from ..utilities import AuthenticatedUser, RequestError, get_logger, httproute, toolcall

if TYPE_CHECKING:
    from .engine import Engine


@dataclass(frozen=True, slots=True)
class NormalizedUserRepo:
    """Hold a normalized repository identifier and display fields."""

    repo_id: str
    repo_url: str
    display_name: str
    ref: str


class UserService:
    """Handle authenticated user profile and repository-management operations."""

    def __init__(self, engine: Engine) -> None:
        """Bind the user service to the shared engine."""
        self.engine = engine
        self.log = get_logger(__name__)

    @httproute(
        "GET",
        "/v1/auth/me",
        name="get_current_user",
        description="Return the current authenticated Lighthouse user.",
    )
    @toolcall(
        "get_current_user",
        description="Return the current authenticated Lighthouse user.",
    )
    async def get_current_user(self, auth: AuthenticatedUser) -> "UserResponse":
        """Return the authenticated user's profile fields."""
        return UserResponse(
            id=auth.id,
            github_id=auth.github_id,
            github_login=auth.github_login,
            display_name=auth.display_name,
            avatar_url=auth.avatar_url,
            email=auth.email,
        )

    @httproute(
        "POST",
        "/v1/user/repos",
        name="add_user_repo",
        description="Add or restore a repository for the current user.",
    )
    @toolcall(
        "add_user_repo",
        description="Add or restore a repository for the current user.",
    )
    async def add_user_repo(
        self,
        auth: AuthenticatedUser,
        repo_url: Annotated[str, Body(...)],
        ref: Annotated[str, Body()] = "main",
    ) -> "UserRepoResponse":
        """Create or restore a repository record for the authenticated user."""
        normalized = self._normalize_repo(repo_url, ref)
        repo = await asyncio.to_thread(self._upsert_user_repo_sync, auth.id, normalized)
        return self._to_user_repo_response(repo)

    @httproute(
        "DELETE",
        "/v1/user/repos/{repo_id:path}",
        name="remove_user_repo",
        description="Soft-delete a repository for the current user.",
    )
    @toolcall(
        "remove_user_repo",
        description="Soft-delete a repository for the current user.",
    )
    async def remove_user_repo(
        self,
        auth: AuthenticatedUser,
        repo_id: str,
    ) -> "RemoveUserRepoResponse":
        """Soft-delete a repository record for the authenticated user."""
        normalized_repo_id = self._normalize_repo_id(repo_id)
        deleted = await asyncio.to_thread(
            self._soft_delete_user_repo_sync,
            auth.id,
            normalized_repo_id,
        )
        return RemoveUserRepoResponse(repo_id=normalized_repo_id, deleted=deleted)

    def _upsert_user_repo_sync(
        self,
        user_id: str,
        normalized: NormalizedUserRepo,
    ) -> UserRepo:
        """Insert or update a repository row within a database connection context."""
        with self.engine.app.database.connection_context():
            repo = UserRepo.get_or_none(
                (UserRepo.user_id == user_id) & (UserRepo.repo_id == normalized.repo_id)
            )
            created = repo is None
            if repo is None:
                repo = UserRepo(
                    user_id=user_id,
                    repo_id=normalized.repo_id,
                    repo_url=normalized.repo_url,
                    display_name=normalized.display_name,
                    ref=normalized.ref,
                    deleted_at=None,
                )
            else:
                repo.repo_url = normalized.repo_url
                repo.display_name = normalized.display_name
                repo.ref = normalized.ref
                repo.deleted_at = None

            repo.save(force_insert=created)
            return repo

    def _soft_delete_user_repo_sync(self, user_id: str, repo_id: str) -> bool:
        """Mark an existing repository row as deleted without removing it."""
        with self.engine.app.database.connection_context():
            repo = UserRepo.get_or_none(
                (UserRepo.user_id == user_id)
                & (UserRepo.repo_id == repo_id)
                & UserRepo.deleted_at.is_null(True)
            )
            if repo is None:
                return False

            repo.deleted_at = datetime.now(timezone.utc)
            repo.save(only=[UserRepo.deleted_at])
            return True

    def _normalize_repo(self, repo_url: str, ref: str) -> NormalizedUserRepo:
        """Normalize user input into canonical repository metadata."""
        repo_id = self._normalize_repo_id(repo_url)
        normalized_ref = ref.strip() or "main"
        return NormalizedUserRepo(
            repo_id=repo_id,
            repo_url=f"https://github.com/{repo_id}",
            display_name=repo_id,
            ref=normalized_ref,
        )

    def _normalize_repo_id(self, repo: str) -> str:
        """Normalize a GitHub repository reference into `owner/repo` form."""
        candidate = repo.strip()
        if not candidate:
            raise RequestError("Repository is required.", status_code=422)

        if candidate.startswith(("http://", "https://")):
            parsed = urlparse(candidate)
            host = parsed.netloc.lower()
            if host not in {"github.com", "www.github.com"}:
                raise RequestError("Only github.com repositories are supported.")
            path = parsed.path
        else:
            path = candidate
            lowered = path.lower()
            if lowered.startswith("github.com/"):
                path = path[len("github.com/") :]
            elif lowered.startswith("www.github.com/"):
                path = path[len("www.github.com/") :]

        parts = [part for part in path.strip("/").split("/") if part]
        if len(parts) < 2:
            raise RequestError("Repository must be in owner/repo form.")

        owner = parts[0].strip()
        repo_name = parts[1].strip()
        if repo_name.lower().endswith(".git"):
            repo_name = repo_name[:-4]
        if not owner or not repo_name:
            raise RequestError("Repository must be in owner/repo form.")

        return f"{owner.lower()}/{repo_name.lower()}"

    def _to_user_repo_response(self, repo: UserRepo) -> "UserRepoResponse":
        """Convert a repository model into the API response shape."""
        return UserRepoResponse(
            id=repo.id,
            repo_id=repo.repo_id,
            repo_url=repo.repo_url,
            display_name=repo.display_name,
            ref=repo.ref,
            added_at=repo.added_at,
            index_status=None,
        )


class UserResponse(BaseModel):
    """Serialize the authenticated user's profile information."""

    id: str
    github_id: int
    github_login: str
    display_name: str | None
    avatar_url: str | None
    email: str | None


class UserRepoResponse(BaseModel):
    """Serialize a repository owned by the authenticated user."""

    id: str
    repo_id: str
    repo_url: str
    display_name: str
    ref: str
    added_at: datetime
    index_status: str | None = None


class RemoveUserRepoResponse(BaseModel):
    """Report whether a repository soft-delete was applied."""

    repo_id: str
    deleted: bool
