from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field
from shared.schemas.ingestion import IndexAcceptedResponse, IndexRequest, RepoIndexRequest

from db import IndexedBranch, Repository, UserHiddenRepository
from ..utilities import (
    AppError,
    AuthenticatedUser,
    GitHubRepository,
    get_logger,
    httproute,
    toolcall,
)

if TYPE_CHECKING:
    from .engine import Engine


class UserEngine:
    """Handle authenticated user profile and indexed-repository operations."""

    LIST_USER_REPOS_DESCRIPTION = (
        "List repositories visible to the current user."
        " Use first to confirm repository names/visibility before retrieval calls."
    )

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
        description=LIST_USER_REPOS_DESCRIPTION,
    )
    @toolcall(
        "list_user_repos",
        description=LIST_USER_REPOS_DESCRIPTION,
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
        return [self._to_user_repo_response(repo, branches) for repo, branches in repos]

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
        request: "AddUserRepoRequest",
    ) -> "UserRepoResponse":
        """Validate and create or unhide an indexed repository for the current user."""
        normalized_full_name = self._normalize_full_name(request.repo_url)
        github_repo = await self.engine.app.authenticator.fetch_github_repository(
            normalized_full_name,
            user_id=auth.id,
        )
        requested_branches = self._normalize_branch_names(request.branches)
        repo, needs_ingestion = await asyncio.to_thread(
            self._upsert_user_repo_sync, github_repo, auth.id
        )

        if needs_ingestion:
            branches = self._merge_default_branch(
                github_repo.default_branch,
                requested_branches,
            )
            await self._trigger_ingestion(github_repo, auth.id, branches)
        else:
            self.log.info(
                "Skipping ingestion for %s (repository unhidden for user)",
                github_repo.full_name,
            )

        return self._to_user_repo_response(repo, [])

    @httproute(
        "POST",
        "/v1/user/repos/{full_name:path}/branches",
        name="add_user_repo_branches",
        description="Add branches to an existing indexed repository for the current user.",
    )
    @toolcall(
        "add_user_repo_branches",
        description="Add branches to an existing indexed repository for the current user.",
    )
    async def add_user_repo_branches(
        self,
        auth: AuthenticatedUser,
        full_name: str,
        request: "AddRepoBranchesRequest",
    ) -> "UserRepoResponse":
        """Trigger indexing for new branches on an existing visible repository."""
        normalized_full_name = self._normalize_full_name(full_name)
        requested_branches = self._normalize_branch_names(request.branches)
        if not requested_branches:
            raise AppError(
                message="At least one branch is required.",
                status_code=422,
                error_code="INVALID_ARGUMENT",
                recoverable=True,
                context={"field": "branches"},
                internal_message="All provided branches were blank after normalization.",
            )

        visible_private_repo_ids = (
            await self.engine.app.authenticator.list_visible_private_repository_ids(
                auth.id
            )
        )
        repo, indexed_branches = await asyncio.to_thread(
            self._get_visible_user_repo_sync,
            auth.id,
            normalized_full_name,
            visible_private_repo_ids,
        )
        if repo is None:
            raise AppError(
                message="Repository does not exist or you do not currently have access to it.",
                status_code=404,
                error_code="REPOSITORY_NOT_FOUND_OR_INACCESSIBLE",
                recoverable=True,
                context={"full_name": normalized_full_name},
            )

        existing_branch_names = {branch.branch_name for branch in indexed_branches}
        new_branches = [
            branch for branch in requested_branches if branch not in existing_branch_names
        ]
        if not new_branches:
            raise AppError(
                message="All requested branches are already indexed for this repository.",
                status_code=409,
                error_code="CONFLICT",
                recoverable=True,
                context={"full_name": normalized_full_name},
            )

        github_repo = await self.engine.app.authenticator.fetch_github_repository(
            normalized_full_name,
            user_id=auth.id,
        )
        await self._trigger_ingestion(github_repo, auth.id, new_branches)

        refreshed_repo, refreshed_branches = await asyncio.to_thread(
            self._get_visible_user_repo_sync,
            auth.id,
            normalized_full_name,
            visible_private_repo_ids,
        )
        assert refreshed_repo is not None
        return self._to_user_repo_response(refreshed_repo, refreshed_branches)

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
        branches: list[str],
    ) -> IndexAcceptedResponse:
        """Call the ingestion service to start indexing. Raises on failure."""
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
                    branches=branches,
                    github_token=github_token,
                )
            ]
        )

        token = self.engine.app.settings.internal_service_token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
                resp = await client.post(
                    f"{ingestion_url}/index",
                    json=index_request.model_dump(exclude_none=True),
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AppError(
                message=f"Ingestion service error: {exc.response.status_code}",
                status_code=502,
                error_code="UPSTREAM_ERROR",
                recoverable=True,
                context={
                    "service": "ingestion",
                    "repository": github_repo.full_name,
                    "upstream_status": exc.response.status_code,
                },
                internal_message=(
                    f"Ingestion service returned {exc.response.status_code} for "
                    f"{github_repo.full_name}."
                ),
                upstream_detail=exc.response.text,
            ) from exc
        except httpx.RequestError as exc:
            raise AppError(
                message="Ingestion service unavailable.",
                status_code=502,
                error_code="UPSTREAM_UNAVAILABLE",
                recoverable=True,
                context={"service": "ingestion", "repository": github_repo.full_name},
                internal_message=str(exc),
                cause_metadata={
                    "request_url": str(exc.request.url) if exc.request else None
                },
            ) from exc

        result = IndexAcceptedResponse.model_validate(resp.json())
        self.log.info(
            "Ingestion triggered for %s, workflow_ids=%s",
            github_repo.full_name,
            result.workflow_ids,
        )
        return result

    def _upsert_user_repo_sync(
        self,
        github_repo: GitHubRepository,
        user_id: str,
    ) -> tuple[Repository, bool]:
        """Insert or update a globally indexed repository row and clear any user hide.

        Returns the saved ``Repository`` and whether ingestion should run. Ingestion is
        skipped when the repository already existed and the only change was removing a
        per-user hide (re-adding a previously removed repository).
        """
        with self.engine.app.database.connection_context():
            repo = Repository.get_or_none(
                Repository.github_repo_id == github_repo.github_repo_id
            )
            created = repo is None
            unhide_only = False
            if not created:
                unhide_only = (
                    UserHiddenRepository.get_or_none(
                        (UserHiddenRepository.user == user_id)
                        & (UserHiddenRepository.repository == repo)
                    )
                    is not None
                )
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
            needs_ingestion = created or not unhide_only
            return repo, needs_ingestion

    def _list_user_repos_sync(
        self,
        user_id: str,
        visible_private_repo_ids: set[int],
    ) -> list[tuple[Repository, list[IndexedBranch]]]:
        """Load visible repositories in newest-first order, with their indexed branches."""
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
            result = []
            for repo in query:
                branches = list(
                    IndexedBranch.select()
                    .where(IndexedBranch.repository == repo)
                    .order_by(IndexedBranch.branch_name)
                )
                result.append((repo, branches))
            return result

    def _get_visible_user_repo_sync(
        self,
        user_id: str,
        full_name: str,
        visible_private_repo_ids: set[int],
    ) -> tuple[Repository | None, list[IndexedBranch]]:
        """Load one visible repository plus its indexed branches for the user."""
        with self.engine.app.database.connection_context():
            visibility_clause = ~Repository.is_private
            if visible_private_repo_ids:
                visibility_clause = (
                    visibility_clause
                    | Repository.github_repo_id.in_(sorted(visible_private_repo_ids))
                )

            hidden_repository_ids = UserHiddenRepository.select(
                UserHiddenRepository.repository
            ).where(UserHiddenRepository.user == user_id)
            repo = Repository.get_or_none(
                (Repository.full_name == full_name)
                & visibility_clause
                & ~(Repository.id.in_(hidden_repository_ids))
            )
            if repo is None:
                return None, []

            branches = list(
                IndexedBranch.select()
                .where(IndexedBranch.repository == repo)
                .order_by(IndexedBranch.branch_name)
            )
            return repo, branches

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
            raise AppError(
                message="Repository is required.",
                status_code=422,
                error_code="INVALID_ARGUMENT",
                recoverable=True,
                context={"field": "repo"},
            )

        if candidate.startswith(("http://", "https://")):
            parsed = urlparse(candidate)
            host = parsed.netloc.lower()
            if host not in {"github.com", "www.github.com"}:
                raise AppError(
                    message="Only github.com repositories are supported.",
                    status_code=422,
                    error_code="INVALID_ARGUMENT",
                    recoverable=True,
                    context={"host": host},
                )
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
            raise AppError(
                message="Repository must be in owner/repo form.",
                status_code=422,
                error_code="INVALID_ARGUMENT",
                recoverable=True,
                context={"repository": candidate},
            )

        owner = parts[0].strip()
        repo_name = parts[1].strip()
        if repo_name.lower().endswith(".git"):
            repo_name = repo_name[:-4]
        if not owner or not repo_name:
            raise AppError(
                message="Repository must be in owner/repo form.",
                status_code=422,
                error_code="INVALID_ARGUMENT",
                recoverable=True,
                context={"repository": candidate},
            )

        return f"{owner.lower()}/{repo_name.lower()}"

    def _normalize_branch_names(self, branches: list[str]) -> list[str]:
        """Trim, de-duplicate, and preserve branch order."""
        normalized: list[str] = []
        seen: set[str] = set()
        for branch in branches:
            candidate = branch.strip()
            if not candidate or candidate in seen:
                continue
            normalized.append(candidate)
            seen.add(candidate)
        return normalized

    def _merge_default_branch(
        self,
        default_branch: str,
        requested_branches: list[str],
    ) -> list[str]:
        """Ensure the default branch is indexed first on initial repo add."""
        merged = [default_branch]
        for branch in requested_branches:
            if branch != default_branch:
                merged.append(branch)
        return merged

    def _to_user_repo_response(self, repo: Repository, branches: list[IndexedBranch]) -> "UserRepoResponse":
        """Convert a repository model into the API response shape."""
        branch_infos = [
            BranchInfo(branch_name=b.branch_name, status=cast("BranchStatus", b.status.upper()))
            for b in branches
        ]
        return UserRepoResponse(
            id=repo.id,
            github_repo_id=repo.github_repo_id,
            full_name=repo.full_name,
            repo_url=repo.repo_url,
            display_name=repo.display_name,
            added_at=repo.added_at,
            index_status=self._compute_index_status(branch_infos),
            branches=branch_infos,
        )

    def _compute_index_status(self, branches: list["BranchInfo"]) -> "BranchStatus | None":
        """Derive a single repo-level status from its branch statuses."""
        if not branches:
            return None
        statuses = {b.status for b in branches}
        for priority in ("INDEXING", "PENDING", "FAILED", "INDEXED"):
            if priority in statuses:
                return cast("BranchStatus", priority)
        return branches[0].status


class UserResponse(BaseModel):
    """Serialize the authenticated user's profile information."""

    id: str
    github_id: int
    github_login: str
    display_name: str | None
    avatar_url: str | None
    email: str | None


BranchStatus = Literal["PENDING", "INDEXING", "INDEXED", "FAILED"]


class BranchInfo(BaseModel):
    """Serialize a single indexed branch and its status."""

    branch_name: str
    status: BranchStatus


class AddUserRepoRequest(BaseModel):
    """Deserialize a repository add request."""

    repo_url: str
    branches: list[str] = Field(default_factory=list)


class AddRepoBranchesRequest(BaseModel):
    """Deserialize a request to index additional branches."""

    branches: list[str]


class UserRepoResponse(BaseModel):
    """Serialize an indexed repository visible to the authenticated user."""

    id: str
    github_repo_id: int
    full_name: str
    repo_url: str
    display_name: str
    added_at: datetime
    index_status: BranchStatus | None = None
    branches: list[BranchInfo] = []


class HideUserRepoResponse(BaseModel):
    """Report whether a repository hide operation was applied."""

    full_name: str
    hidden: bool


UserRepoResponse.model_rebuild()
