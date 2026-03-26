import pytest
from pydantic import ValidationError

from shared.schemas.search import CodeSnippet, SearchRequest, SearchResult


# ── SearchRequest ──────────────────────────────────────────────────


@pytest.mark.unit
def test_search_request_defaults():
    req = SearchRequest(query="find auth", github_repo_id=1)
    assert req.branch == "main"
    assert req.top_k == 10


@pytest.mark.unit
def test_search_request_top_k_zero_raises():
    with pytest.raises(ValidationError):
        SearchRequest(query="q", github_repo_id=1, top_k=0)


@pytest.mark.unit
def test_search_request_top_k_101_raises():
    with pytest.raises(ValidationError):
        SearchRequest(query="q", github_repo_id=1, top_k=101)


@pytest.mark.unit
def test_search_request_empty_branch_raises():
    with pytest.raises(ValidationError):
        SearchRequest(query="q", github_repo_id=1, branch="")


# ── CodeSnippet ────────────────────────────────────────────────────


@pytest.mark.unit
def test_code_snippet_defaults():
    snippet = CodeSnippet(
        file_path="src/main.py",
        start_line=1,
        end_line=10,
        content="print('hi')",
    )
    assert snippet.score == 0.0
    assert snippet.language is None
    assert snippet.reason is None


# ── SearchResult ───────────────────────────────────────────────────


@pytest.mark.unit
def test_search_result_defaults():
    result = SearchResult(query="find auth")
    assert result.snippets == []
    assert result.total_results == 0
