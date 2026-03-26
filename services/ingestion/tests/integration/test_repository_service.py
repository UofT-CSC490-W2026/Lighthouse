import pytest
from db import Repository
from ingestion.utilities.services.repository import RepositoryService

@pytest.mark.integration
class TestRepositoryService:
    def test_ensure_creates_new(self, db_manager):
        svc = RepositoryService(db_manager)
        repo_id = svc.ensure(12345, "https://github.com/o/r", "o/r")
        assert repo_id is not None
        with db_manager.connection_context():
            repo = Repository.get_by_id(repo_id)
            assert repo.full_name == "o/r"
            assert repo.owner_login == "o"
            assert repo.display_name == "r"

    def test_ensure_returns_existing(self, db_manager):
        svc = RepositoryService(db_manager)
        id1 = svc.ensure(22222, "url", "a/b")
        id2 = svc.ensure(22222, "url", "a/b")
        assert id1 == id2

    def test_ensure_updates_renamed_repo(self, db_manager):
        svc = RepositoryService(db_manager)
        svc.ensure(33333, "url", "old/name")
        svc.ensure(33333, "url", "new/name")
        with db_manager.connection_context():
            repo = Repository.get(Repository.github_repo_id == 33333)
            assert repo.full_name == "new/name"
            assert repo.owner_login == "new"
            assert repo.display_name == "name"

    def test_ensure_updates_url(self, db_manager):
        svc = RepositoryService(db_manager)
        svc.ensure(44444, "old-url", "o/r")
        svc.ensure(44444, "new-url", "o/r")
        with db_manager.connection_context():
            repo = Repository.get(Repository.github_repo_id == 44444)
            assert repo.repo_url == "new-url"

    def test_ensure_owner_extraction_no_slash(self, db_manager):
        svc = RepositoryService(db_manager)
        repo_id = svc.ensure(55555, "url", "repoonly")
        with db_manager.connection_context():
            repo = Repository.get_by_id(repo_id)
            assert repo.owner_login == ""
            assert repo.display_name == "repoonly"
