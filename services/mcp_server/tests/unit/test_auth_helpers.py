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
