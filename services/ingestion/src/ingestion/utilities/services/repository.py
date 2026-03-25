from __future__ import annotations

import logging

from db import DatabaseManager, Repository

logger = logging.getLogger(__name__)


class RepositoryService:
    """CRUD operations for Repository records."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    def ensure(
        self, github_repo_id: int, repo_url: str, full_name: str
    ) -> str:
        """Get or create a Repository record, returning its id."""
        with self.db.connection_context():
            repo = Repository.get_or_none(
                Repository.github_repo_id == github_repo_id
            )
            if repo is None:
                parts = full_name.split("/")
                owner = parts[0] if len(parts) > 1 else ""
                name = parts[-1]
                repo = Repository.create(
                    github_repo_id=github_repo_id,
                    full_name=full_name,
                    repo_url=repo_url,
                    display_name=name,
                    owner_login=owner,
                    owner_type="User",
                )
                logger.info("Created repository record: %s", full_name)
            else:
                if repo.full_name != full_name:
                    logger.info(
                        "Repository renamed: %s -> %s", repo.full_name, full_name
                    )
                    repo.full_name = full_name
                    parts = full_name.split("/")
                    repo.owner_login = parts[0] if len(parts) > 1 else ""
                    repo.display_name = parts[-1]
                if repo.repo_url != repo_url:
                    repo.repo_url = repo_url
                repo.save()
            return repo.id
