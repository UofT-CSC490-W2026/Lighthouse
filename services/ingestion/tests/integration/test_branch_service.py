import pytest
from db import IndexedBranch
from ingestion.utilities.services.branch import BranchService
from testing_utils.factories import create_repository

@pytest.mark.integration
class TestBranchService:
    def test_update_status_creates_new(self, db_manager):
        repo = create_repository(db_manager)
        svc = BranchService(db_manager)
        result = svc.update_status(repo.id, "main", "indexing")
        assert result == "indexing"
        with db_manager.connection_context():
            ib = IndexedBranch.get(IndexedBranch.repository == repo.id)
            assert ib.status == "indexing"
            assert ib.branch_name == "main"

    def test_update_status_updates_existing(self, db_manager):
        repo = create_repository(db_manager)
        svc = BranchService(db_manager)
        svc.update_status(repo.id, "main", "indexing", target_commit="abc123")
        svc.update_status(repo.id, "main", "indexed", latest_commit="abc123")
        with db_manager.connection_context():
            ib = IndexedBranch.get(IndexedBranch.repository == repo.id)
            assert ib.status == "indexed"
            assert ib.last_indexed_commit == "abc123"
            assert ib.target_commit is None

    def test_indexed_status_sets_indexed_at(self, db_manager):
        repo = create_repository(db_manager)
        svc = BranchService(db_manager)
        svc.update_status(repo.id, "main", "indexed")
        with db_manager.connection_context():
            ib = IndexedBranch.get(IndexedBranch.repository == repo.id)
            assert ib.indexed_at is not None

    def test_non_indexed_status_no_indexed_at(self, db_manager):
        repo = create_repository(db_manager)
        svc = BranchService(db_manager)
        svc.update_status(repo.id, "main", "indexing")
        with db_manager.connection_context():
            ib = IndexedBranch.get(IndexedBranch.repository == repo.id)
            assert ib.indexed_at is None

    def test_stores_github_token(self, db_manager):
        repo = create_repository(db_manager)
        svc = BranchService(db_manager)
        svc.update_status(repo.id, "main", "pending", github_token="my-token")
        with db_manager.connection_context():
            ib = IndexedBranch.get(IndexedBranch.repository == repo.id)
            assert ib.github_token_encrypted == "my-token"

    def test_stale_indexed_update_does_not_overwrite_newer_target(self, db_manager):
        repo = create_repository(db_manager)
        svc = BranchService(db_manager)
        svc.update_status(repo.id, "main", "indexing", target_commit="new123")
        result = svc.update_status(repo.id, "main", "indexed", latest_commit="old123")
        with db_manager.connection_context():
            ib = IndexedBranch.get(IndexedBranch.repository == repo.id)
            assert result == "indexing"
            assert ib.status == "indexing"
            assert ib.target_commit == "new123"
            assert ib.last_indexed_commit is None

    def test_get_github_token_exists(self, db_manager):
        repo = create_repository(db_manager)
        svc = BranchService(db_manager)
        svc.update_status(repo.id, "dev", "pending", github_token="tok123")
        result = svc.get_github_token(repo.id, "dev")
        assert result == "tok123"

    def test_get_github_token_missing(self, db_manager):
        repo = create_repository(db_manager)
        svc = BranchService(db_manager)
        result = svc.get_github_token(repo.id, "nonexistent")
        assert result is None

    def test_stale_failed_update_does_not_overwrite_newer_target(self, db_manager):
        """When status=failed but latest_commit != target_commit, preserve existing status."""
        repo = create_repository(db_manager)
        svc = BranchService(db_manager)
        # Set target_commit to "new123"
        svc.update_status(repo.id, "main", "indexing", target_commit="new123")
        # Fail with an old commit — should not update status
        result = svc.update_status(repo.id, "main", "failed", latest_commit="old_commit")
        with db_manager.connection_context():
            ib = IndexedBranch.get(IndexedBranch.repository == repo.id)
            assert result == "indexing"
            assert ib.status == "indexing"
