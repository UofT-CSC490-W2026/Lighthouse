from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlparse

import httpx
from fastapi import Body
from pydantic import BaseModel
from shared.schemas.ingestion import IndexAcceptedResponse, IndexRequest, RepoIndexRequest

from db import Repository, UserHiddenRepository
from ..utilities import (
    AuthenticatedUser,
    GitHubRepository,
    RequestError,
    get_logger,
    httproute,
    toolcall,
)

if TYPE_CHECKING:
    from .engine import Engine


class UserEngine:
    """Handle authenticated user profile and indexed-repository operations."""

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
        "GET",
        "/v1/user/repos",
        name="list_user_repos",
        description="List repositories visible to the current user.",
    )
    @toolcall(
        "list_user_repos",
        description="List repositories visible to the current user.",
    )
    async def list_user_repos(
        self, auth: AuthenticatedUser
    ) -> list["UserRepoResponse"]:
        """Return public repositories plus private repositories the user can currently access."""
        visible_private_repo_ids = (
            await self.engine.app.authenticator.list_visible_private_repository_ids(
                auth.id
            )
        )
        repos = await asyncio.to_thread(
            self._list_user_repos_sync,
            auth.id,
            visible_private_repo_ids,
        )
        return [self._to_user_repo_response(repo) for repo in repos]

    @httproute(
        "POST",
        "/v1/user/repos",
        name="add_user_repo",
        description="Add a repository to the shared Lighthouse index or unhide it for the current user.",
    )
    @toolcall(
        "add_user_repo",
        description="Add a repository to the shared Lighthouse index or unhide it for the current user.",
    )
    async def add_user_repo(
        self,
        auth: AuthenticatedUser,
        repo_url: Annotated[str, Body(..., embed=True)],
    ) -> "UserRepoResponse":
        """Validate and create or unhide an indexed repository for the current user."""
        normalized_full_name = self._normalize_full_name(repo_url)
        github_repo = await self.engine.app.authenticator.fetch_github_repository(
            normalized_full_name,
            user_id=auth.id,
        )
        repo = await asyncio.to_thread(
            self._upsert_user_repo_sync, github_repo, auth.id
        )

        # Fire-and-forget ingestion trigger
        await self._trigger_ingestion(github_repo, auth.id)

        return self._to_user_repo_response(repo)

    @httproute(
        "DELETE",
        "/v1/user/repos/{full_name:path}",
        name="remove_user_repo",
        description="Hide a repository from the current user without deleting it globally.",
    )
    @toolcall(
        "remove_user_repo",
        description="Hide a repository from the current user without deleting it globally.",
    )
    async def remove_user_repo(
        self,
        auth: AuthenticatedUser,
        full_name: str,
    ) -> "HideUserRepoResponse":
        """Hide an indexed repository for the current user."""
        normalized_full_name = self._normalize_full_name(full_name)
        hidden = await asyncio.to_thread(
            self._hide_user_repo_sync,
            auth.id,
            normalized_full_name,
        )
        return HideUserRepoResponse(full_name=normalized_full_name, hidden=hidden)

    async def _trigger_ingestion(
        self,
        github_repo: GitHubRepository,
        user_id: str,
    ) -> None:
        """Call the ingestion service to index the repository. Best-effort."""
        ingestion_url = self.engine.app.settings.ingestion_service_url

        github_token = await asyncio.to_thread(
            self.engine.app.authenticator._get_github_access_token_sync, user_id
        )

        index_request = IndexRequest(
            repositories=[
                RepoIndexRequest(
                    github_repo_id=github_repo.github_repo_id,
                    repo_url=github_repo.repo_url,
                    full_name=github_repo.full_name,
                    branches=[github_repo.default_branch],
                    github_token=github_token,
                )
            ]
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{ingestion_url}/index",
                    json=index_request.model_dump(exclude_none=True),
                )
                resp.raise_for_status()
                result = IndexAcceptedResponse.model_validate(resp.json())
                self.log.info(
                    "Ingestion triggered for %s, workflow_ids=%s",
                    github_repo.full_name,
                    result.workflow_ids,
                )
        except httpx.HTTPStatusError as exc:
            self.log.warning(
                "Ingestion service returned %s for %s: %s",
                exc.response.status_code,
                github_repo.full_name,
                exc.response.text,
            )
        except httpx.RequestError as exc:
            self.log.warning(
                "Failed to reach ingestion service for %s: %s",
                github_repo.full_name,
                exc,
            )

    def _upsert_user_repo_sync(
        self,
        github_repo: GitHubRepository,
        user_id: str,
    ) -> Repository:
        """Insert or update a globally indexed repository row and clear any user hide."""
        with self.engine.app.database.connection_context():
            repo = Repository.get_or_none(
                Repository.github_repo_id == github_repo.github_repo_id
            )
            created = repo is None
            if repo is None:
                repo = Repository(
                    github_repo_id=github_repo.github_repo_id,
                    full_name=github_repo.full_name,
                    repo_url=github_repo.repo_url,
                    display_name=github_repo.display_name,
                    owner_login=github_repo.owner_login,
                    owner_type=github_repo.owner_type,
                    is_private=github_repo.is_private,
                )
            else:
                repo.github_repo_id = github_repo.github_repo_id
                repo.full_name = github_repo.full_name
                repo.repo_url = github_repo.repo_url
                repo.display_name = github_repo.display_name
                repo.owner_login = github_repo.owner_login
                repo.owner_type = github_repo.owner_type
                repo.is_private = github_repo.is_private

            repo.save(force_insert=created)
            (
                UserHiddenRepository.delete()
                .where(
                    (UserHiddenRepository.user == user_id)
                    & (UserHiddenRepository.repository == repo)
                )
                .execute()
            )
            return repo

    def _list_user_repos_sync(
        self,
        user_id: str,
        visible_private_repo_ids: set[int],
    ) -> list[Repository]:
        """Load visible repositories in newest-first order."""
        with self.engine.app.database.connection_context():
            visibility_clause = ~Repository.is_private
            if visible_private_repo_ids:
                visibility_clause = (
                    visibility_clause
                    | Repository.github_repo_id.in_(
                        sorted(visible_private_repo_ids)
                    )
                )

            hidden_repository_ids = UserHiddenRepository.select(
                UserHiddenRepository.repository
            ).where(UserHiddenRepository.user == user_id)
            query = (
                Repository.select()
                .where(
                    (visibility_clause) & ~(Repository.id.in_(hidden_repository_ids))
                )
                .order_by(Repository.added_at.desc())
            )
            return list(query)

    def _hide_user_repo_sync(self, user_id: str, full_name: str) -> bool:
        """Hide an existing repository for a single user without deleting it globally."""
        with self.engine.app.database.connection_context():
            repo = Repository.get_or_none(Repository.full_name == full_name)
            if repo is None:
                return False

            hidden_repo = UserHiddenRepository.get_or_none(
                (UserHiddenRepository.user == user_id)
                & (UserHiddenRepository.repository == repo)
            )
            if hidden_repo is not None:
                return False

            UserHiddenRepository.create(user=user_id, repository=repo)
            return True

    def _normalize_full_name(self, repo: str) -> str:
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

    def _to_user_repo_response(self, repo: Repository) -> "UserRepoResponse":
        """Convert a repository model into the API response shape."""
        return UserRepoResponse(
            id=repo.id,
            github_repo_id=repo.github_repo_id,
            full_name=repo.full_name,
            repo_url=repo.repo_url,
            display_name=repo.display_name,
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
    """Serialize an indexed repository visible to the authenticated user."""

    id: str
    github_repo_id: int
    full_name: str
    repo_url: str
    display_name: str
    added_at: datetime
    index_status: str | None = None


class HideUserRepoResponse(BaseModel):
    """Report whether a repository hide operation was applied."""

    full_name: str
    hidden: bool


UserRepoResponse.model_rebuild()
