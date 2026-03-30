import pytest
from unittest.mock import MagicMock

from mcp_server.utilities.auth import Authenticator, AuthorizationError


@pytest.fixture
def auth():
    return Authenticator(MagicMock())


@pytest.mark.unit
class TestExtractBearerToken:
    def test_extract_bearer_valid(self, auth):
        assert auth.extract_bearer_token("Bearer abc123") == "abc123"

    def test_extract_bearer_with_spaces(self, auth):
        assert auth.extract_bearer_token("Bearer  abc123 ") == "abc123"

    def test_extract_missing_header(self, auth):
        with pytest.raises(AuthorizationError):
            auth.extract_bearer_token(None)

    def test_extract_empty_header(self, auth):
        with pytest.raises(AuthorizationError):
            auth.extract_bearer_token("")

    def test_extract_wrong_scheme(self, auth):
        with pytest.raises(AuthorizationError):
            auth.extract_bearer_token("Basic abc123")

    def test_extract_bearer_no_token(self, auth):
        with pytest.raises(AuthorizationError):
            auth.extract_bearer_token("Bearer ")


@pytest.mark.unit
class TestHashToken:
    def test_hash_token_deterministic(self, auth):
        assert auth.hash_token("mytoken") == auth.hash_token("mytoken")

    def test_hash_token_different(self, auth):
        assert auth.hash_token("token_a") != auth.hash_token("token_b")

    def test_hash_token_is_hex(self, auth):
        result = auth.hash_token("anything")
        assert len(result) == 64
        int(result, 16)  # raises ValueError if not valid hex


@pytest.mark.unit
class TestAuthorizationError:
    def test_authorization_error_defaults_to_auth_required_for_401(self):
        from mcp_server.utilities.auth import AuthorizationError
        exc = AuthorizationError(status_code=401)
        assert exc.error_code == "AUTH_REQUIRED"

    def test_authorization_error_defaults_to_forbidden_for_403(self):
        from mcp_server.utilities.auth import AuthorizationError
        exc = AuthorizationError("Access denied", status_code=403)
        assert exc.error_code == "FORBIDDEN"

    def test_authorization_error_defaults_to_invalid_token_for_other_codes(self):
        from mcp_server.utilities.auth import AuthorizationError
        exc = AuthorizationError("bad token", status_code=400)
        assert exc.error_code == "AUTH_INVALID_TOKEN"

    def test_authorization_error_respects_explicit_error_code(self):
        from mcp_server.utilities.auth import AuthorizationError
        exc = AuthorizationError("custom", status_code=401, error_code="CUSTOM_CODE")
        assert exc.error_code == "CUSTOM_CODE"
