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
        svc.update_status(repo.id, "main", "indexing")
        svc.update_status(repo.id, "main", "indexed", latest_commit="abc123")
        with db_manager.connection_context():
            ib = IndexedBranch.get(IndexedBranch.repository == repo.id)
            assert ib.status == "indexed"
            assert ib.last_indexed_commit == "abc123"

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
