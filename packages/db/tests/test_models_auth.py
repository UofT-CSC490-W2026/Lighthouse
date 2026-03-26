import pytest
from datetime import datetime, timezone, timedelta
from peewee import IntegrityError
from db import User, Session, Repository, UserHiddenRepository, DatabaseManager

@pytest.mark.integration
class TestUserModel:
    def test_create_user(self, db_manager):
        with db_manager.connection_context():
            user = User.create(github_id=12345, github_login="testuser", display_name="Test")
            assert user.id is not None
            assert user.github_id == 12345
            assert user.created_at is not None

    def test_github_id_unique(self, db_manager):
        with db_manager.connection_context():
            User.create(github_id=111, github_login="user1")
            with pytest.raises(IntegrityError):
                User.create(github_id=111, github_login="user2")

    def test_user_defaults(self, db_manager):
        with db_manager.connection_context():
            user = User.create(github_id=222, github_login="u")
            assert user.api_token_encrypted is None
            assert user.mcp_token_encrypted is None
            assert len(user.id) == 36  # UUID format

@pytest.mark.integration
class TestSessionModel:
    def test_create_session(self, db_manager):
        with db_manager.connection_context():
            user = User.create(github_id=333, github_login="u")
            session = Session.create(
                user=user, github_token_encrypted="enc", expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
            )
            assert session.user_id == user.id

    def test_session_cascade_on_user_delete(self, db_manager):
        with db_manager.connection_context():
            user = User.create(github_id=444, github_login="u")
            Session.create(user=user, github_token_encrypted="enc", expires_at=datetime.now(timezone.utc))
            user.delete_instance()
            assert Session.select().count() == 0

@pytest.mark.integration
class TestRepositoryModel:
    def test_create_repository(self, db_manager):
        with db_manager.connection_context():
            repo = Repository.create(
                github_repo_id=1001, full_name="owner/repo", repo_url="https://github.com/owner/repo",
                display_name="repo", owner_login="owner", owner_type="User",
            )
            assert repo.id is not None
            assert repo.is_private == False

    def test_full_name_unique(self, db_manager):
        with db_manager.connection_context():
            Repository.create(github_repo_id=1002, full_name="a/b", repo_url="u", display_name="b", owner_login="a", owner_type="User")
            with pytest.raises(IntegrityError):
                Repository.create(github_repo_id=1003, full_name="a/b", repo_url="u2", display_name="b", owner_login="a", owner_type="User")

    def test_github_repo_id_unique(self, db_manager):
        with db_manager.connection_context():
            Repository.create(github_repo_id=1004, full_name="a/c", repo_url="u", display_name="c", owner_login="a", owner_type="User")
            with pytest.raises(IntegrityError):
                Repository.create(github_repo_id=1004, full_name="a/d", repo_url="u2", display_name="d", owner_login="a", owner_type="User")

@pytest.mark.integration
class TestUserHiddenRepository:
    def test_create_hidden(self, db_manager):
        with db_manager.connection_context():
            user = User.create(github_id=555, github_login="u")
            repo = Repository.create(github_repo_id=2001, full_name="o/r1", repo_url="u", display_name="r1", owner_login="o", owner_type="User")
            hidden = UserHiddenRepository.create(user=user, repository=repo)
            assert hidden.id is not None

    def test_unique_user_repo(self, db_manager):
        with db_manager.connection_context():
            user = User.create(github_id=556, github_login="u")
            repo = Repository.create(github_repo_id=2002, full_name="o/r2", repo_url="u", display_name="r2", owner_login="o", owner_type="User")
            UserHiddenRepository.create(user=user, repository=repo)
            with pytest.raises(IntegrityError):
                UserHiddenRepository.create(user=user, repository=repo)

    def test_cascade_on_user_delete(self, db_manager):
        with db_manager.connection_context():
            user = User.create(github_id=557, github_login="u")
            repo = Repository.create(github_repo_id=2003, full_name="o/r3", repo_url="u", display_name="r3", owner_login="o", owner_type="User")
            UserHiddenRepository.create(user=user, repository=repo)
            user.delete_instance()
            assert UserHiddenRepository.select().count() == 0

    def test_cascade_on_repo_delete(self, db_manager):
        with db_manager.connection_context():
            user = User.create(github_id=558, github_login="u")
            repo = Repository.create(github_repo_id=2004, full_name="o/r4", repo_url="u", display_name="r4", owner_login="o", owner_type="User")
            UserHiddenRepository.create(user=user, repository=repo)
            repo.delete_instance()
            assert UserHiddenRepository.select().count() == 0
