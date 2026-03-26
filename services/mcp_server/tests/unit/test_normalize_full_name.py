import pytest
from unittest.mock import MagicMock

from mcp_server.engine.user import UserEngine
from mcp_server.utilities.errors import RequestError


@pytest.fixture
def engine():
    return UserEngine(MagicMock())


@pytest.mark.unit
class TestNormalizeFullName:
    """Tests for UserEngine._normalize_full_name."""

    def test_simple_owner_repo(self, engine):
        assert engine._normalize_full_name("owner/repo") == "owner/repo"

    def test_github_https_url(self, engine):
        assert engine._normalize_full_name("https://github.com/Owner/Repo") == "owner/repo"

    def test_github_https_www(self, engine):
        assert engine._normalize_full_name("https://www.github.com/owner/repo") == "owner/repo"

    def test_github_url_with_git_suffix(self, engine):
        assert engine._normalize_full_name("https://github.com/owner/repo.git") == "owner/repo"

    def test_bare_github_prefix(self, engine):
        assert engine._normalize_full_name("github.com/owner/repo") == "owner/repo"

    def test_bare_www_github_prefix(self, engine):
        assert engine._normalize_full_name("www.github.com/owner/repo") == "owner/repo"

    def test_lowercased(self, engine):
        assert engine._normalize_full_name("Owner/REPO") == "owner/repo"

    def test_trailing_slashes(self, engine):
        assert engine._normalize_full_name("owner/repo/") == "owner/repo"

    def test_empty_raises(self, engine):
        with pytest.raises(RequestError):
            engine._normalize_full_name("")

    def test_whitespace_only_raises(self, engine):
        with pytest.raises(RequestError):
            engine._normalize_full_name("   ")

    def test_single_part_raises(self, engine):
        with pytest.raises(RequestError):
            engine._normalize_full_name("justrepo")

    def test_non_github_url_raises(self, engine):
        with pytest.raises(RequestError):
            engine._normalize_full_name("https://gitlab.com/o/r")

    def test_http_non_github_raises(self, engine):
        with pytest.raises(RequestError):
            engine._normalize_full_name("http://bitbucket.org/o/r")
