from __future__ import annotations

from datetime import datetime, timezone

from db import DatabaseManager, IndexedBranch


class BranchService:
    """Manage IndexedBranch status and metadata."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    def update_status(
        self,
        repository_id: str,
        branch: str,
        status: str,
        latest_commit: str | None = None,
        target_commit: str | None = None,
        github_token: str | None = None,
    ) -> str:
        """Update or create an IndexedBranch record with the given status."""
        with self.db.connection_context():
            indexed_branch, _ = IndexedBranch.get_or_create(
                repository_id=repository_id,
                branch_name=branch,
                defaults={
                    "status": "pending",
                    "github_token_encrypted": github_token,
                },
            )
            if target_commit is not None:
                indexed_branch.target_commit = target_commit

            current_target_commit = indexed_branch.target_commit
            commit_matches_target = (
                latest_commit is not None
                and current_target_commit is not None
                and latest_commit == current_target_commit
            )

            if status == "failed" and current_target_commit and latest_commit is not None:
                if latest_commit != current_target_commit:
                    return indexed_branch.status

            if status == "indexed" and latest_commit is not None and current_target_commit is not None:
                if latest_commit != current_target_commit:
                    return indexed_branch.status

            indexed_branch.status = status
            indexed_branch.updated_at = datetime.now(timezone.utc)
            if latest_commit is not None:
                if status != "indexed" or current_target_commit is None or commit_matches_target:
                    indexed_branch.last_indexed_commit = latest_commit
            if status == "indexed":
                indexed_branch.indexed_at = datetime.now(timezone.utc)
                if commit_matches_target:
                    indexed_branch.target_commit = None
            if github_token is not None:
                indexed_branch.github_token_encrypted = github_token
            indexed_branch.save()
            return status

    def get_github_token(self, repository_id: str, branch: str) -> str | None:
        """Retrieve the stored github token for a branch."""
        with self.db.connection_context():
            ib = IndexedBranch.get_or_none(
                (IndexedBranch.repository_id == repository_id)
                & (IndexedBranch.branch_name == branch)
            )
            if ib is None:
                return None
            return ib.github_token_encrypted
