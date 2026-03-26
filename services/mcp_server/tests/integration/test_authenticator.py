import pytest
from unittest.mock import MagicMock
from cryptography.fernet import Fernet
from db import User, DatabaseManager
from mcp_server.utilities.auth import Authenticator, AuthorizationError, GitHubUser

def _make_authenticator(db_manager):
    """Create an Authenticator with a mock App that has a real database."""
    key = Fernet.generate_key().decode()
    app = MagicMock()
    app.database = db_manager
    app.settings.session_encryption_key = key
    app.settings.github_oauth_client_id = "test-client-id"
    app.settings.github_oauth_client_secret = "test-secret"
    app.settings.github_oauth_callback_url = "http://localhost/callback"
    app.settings.web_client_url = "http://localhost:3000"
    return Authenticator(app)

@pytest.mark.integration
class TestAuthenticator:
    def test_upsert_and_authenticate(self, db_manager):
        auth = _make_authenticator(db_manager)
        gh_user = GitHubUser(id=1001, login="testuser", name="Test", avatar_url=None, email="t@t.com")
        authed_user, api_token = auth._upsert_github_user_and_issue_token_sync(gh_user, "gh-token")
        assert authed_user.github_id == 1001
        assert authed_user.github_login == "testuser"

        # Now authenticate with the token
        result = auth._authenticate_bearer_token_sync(api_token)
        assert result.id == authed_user.id

    def test_authenticate_invalid_token(self, db_manager):
        auth = _make_authenticator(db_manager)
        with pytest.raises(AuthorizationError):
            auth._authenticate_bearer_token_sync("totally-fake-token")

    def test_revoke_token(self, db_manager):
        auth = _make_authenticator(db_manager)
        gh_user = GitHubUser(id=2002, login="u2", name="U", avatar_url=None, email=None)
        authed_user, api_token = auth._upsert_github_user_and_issue_token_sync(gh_user, "gh-token")
        auth._revoke_token_sync(authed_user.id)
        with pytest.raises(AuthorizationError):
            auth._authenticate_bearer_token_sync(api_token)

    def test_mcp_token_lifecycle(self, db_manager):
        auth = _make_authenticator(db_manager)
        gh_user = GitHubUser(id=3003, login="u3", name="U", avatar_url=None, email=None)
        authed_user, _ = auth._upsert_github_user_and_issue_token_sync(gh_user, "gh-token")

        # No MCP token initially
        managed = auth._get_mcp_token_sync(authed_user.id)
        assert managed.token is None

        # Rotate (create)
        managed = auth._rotate_mcp_token_sync(authed_user.id)
        assert managed.token is not None
        mcp_token = managed.token

        # Authenticate with MCP token
        result = auth._authenticate_bearer_token_sync(mcp_token)
        assert result.authenticated_via == "mcp"

        # Revoke MCP
        auth._revoke_mcp_token_sync(authed_user.id)
        with pytest.raises(AuthorizationError):
            auth._authenticate_bearer_token_sync(mcp_token)

    def test_upsert_existing_user_updates(self, db_manager):
        auth = _make_authenticator(db_manager)
        gh_user1 = GitHubUser(id=4004, login="oldlogin", name="Old", avatar_url=None, email=None)
        auth._upsert_github_user_and_issue_token_sync(gh_user1, "gh-token")

        gh_user2 = GitHubUser(id=4004, login="newlogin", name="New", avatar_url="http://img", email="new@e.com")
        authed, new_token = auth._upsert_github_user_and_issue_token_sync(gh_user2, "gh-token2")
        assert authed.github_login == "newlogin"
        assert authed.display_name == "New"

        # Old token should be invalid (rotated)
        result = auth._authenticate_bearer_token_sync(new_token)
        assert result.github_login == "newlogin"

    def test_hash_and_encrypt_roundtrip(self, db_manager):
        auth = _make_authenticator(db_manager)
        token = auth.generate_api_token()
        encrypted = auth.encrypt_token(token)
        decrypted = auth.decrypt_token(encrypted)
        assert decrypted == token
