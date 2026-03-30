"""Tests for LLMCombinedSearchStrategy covering all missing lines."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.schemas.search import (
    CombinedSearchResult,
    CombinedSnippet,
    SearchContextSource,
    SearchRequest,
)
from search.strategies.llm_combined_strategy import (
    LLMCombinedSearchStrategy,
    _combined_snippet_key,
)


@contextmanager
def _connection_context():
    yield


def _make_strategy(**overrides):
    db_manager = SimpleNamespace(connection_context=_connection_context)
    milvus_code = MagicMock()
    milvus_wiki = MagicMock()
    embedder = MagicMock()
    embedder.embed_single.return_value = [0.1] * 8
    llm = MagicMock()
    llm.complete_json.return_value = {"keywords": ["foo", "bar"]}
    reranker = MagicMock()
    reranker.rerank = AsyncMock(return_value=[])

    kwargs = dict(
        db_manager=db_manager,
        milvus_code=milvus_code,
        milvus_wiki=milvus_wiki,
        embedder=embedder,
        llm=llm,
        reranker=reranker,
        llm_reasoning_effort="default",
    )
    kwargs.update(overrides)
    return LLMCombinedSearchStrategy(**kwargs)


def _make_request(**overrides):
    kwargs = dict(query="find auth code", github_repo_id=1, branch="main", top_k=5)
    kwargs.update(overrides)
    return SearchRequest(**kwargs)


# ---------------------------------------------------------------------------
# Tests for _combined_snippet_key
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_combined_snippet_key_code():
    snippet = CombinedSnippet(
        context_source=SearchContextSource.code,
        content="x",
        score=0.5,
        file_path="src/auth.py",
        start_line=10,
        end_line=20,
    )
    key = _combined_snippet_key(snippet)
    assert key == "code:src/auth.py:10:20"


@pytest.mark.unit
def test_combined_snippet_key_wiki():
    snippet = CombinedSnippet(
        context_source=SearchContextSource.wiki,
        content="x",
        score=0.5,
        slug="auth-guide",
        section_path="security/auth",
        page_title="Auth Guide",
    )
    key = _combined_snippet_key(snippet)
    assert key == "wiki:auth-guide:security/auth:Auth Guide"


# ---------------------------------------------------------------------------
# Tests for _rrf_fusion_multi
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rrf_fusion_multi_empty():
    result = LLMCombinedSearchStrategy._rrf_fusion_multi([])
    assert result == []


@pytest.mark.unit
def test_rrf_fusion_multi_deduplicates():
    list1 = [{"chunk_id": "a", "score": 0.9}, {"chunk_id": "b", "score": 0.8}]
    list2 = [{"chunk_id": "a", "score": 0.7}, {"chunk_id": "c", "score": 0.6}]

    result = LLMCombinedSearchStrategy._rrf_fusion_multi([list1, list2])
    ids = [r["chunk_id"] for r in result]
    assert ids[0] == "a"
    assert ids.count("a") == 1
    assert set(ids) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# Tests for _rrf_fuse_combined
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rrf_fuse_combined_empty():
    result = LLMCombinedSearchStrategy._rrf_fuse_combined([])
    assert result == []


@pytest.mark.unit
def test_rrf_fuse_combined_merges_code_and_wiki():
    code = [
        CombinedSnippet(
            context_source=SearchContextSource.code,
            content="code content",
            score=0.9,
            file_path="a.py",
            start_line=1,
            end_line=10,
        )
    ]
    wiki = [
        CombinedSnippet(
            context_source=SearchContextSource.wiki,
            content="wiki content",
            score=0.8,
            slug="guide",
            section_path="",
            page_title="Guide",
        )
    ]
    result = LLMCombinedSearchStrategy._rrf_fuse_combined([code, wiki])
    assert len(result) == 2
    sources = {r.context_source for r in result}
    assert SearchContextSource.code in sources
    assert SearchContextSource.wiki in sources


# ---------------------------------------------------------------------------
# Tests for _resolve_repo_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_repo_id_found(monkeypatch):
    strategy = _make_strategy()
    repo = SimpleNamespace(id="repo-uuid-1")
    monkeypatch.setattr(
        "search.strategies.llm_combined_strategy.Repository.get_or_none",
        MagicMock(return_value=repo),
    )
    assert strategy._resolve_repo_id(42) == "repo-uuid-1"


@pytest.mark.unit
def test_resolve_repo_id_not_found(monkeypatch):
    strategy = _make_strategy()
    monkeypatch.setattr(
        "search.strategies.llm_combined_strategy.Repository.get_or_none",
        MagicMock(return_value=None),
    )
    assert strategy._resolve_repo_id(99) is None


# ---------------------------------------------------------------------------
# Tests for _generate_keywords
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_keywords_success():
    strategy = _make_strategy()
    strategy.llm.complete_json.return_value = {"keywords": ["auth", "login"]}
    result = await strategy._generate_keywords("find authentication code")
    assert result == ["auth", "login"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_keywords_exception_returns_empty():
    strategy = _make_strategy()
    strategy.llm.complete_json.side_effect = RuntimeError("LLM failed")
    result = await strategy._generate_keywords("query")
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_keywords_non_list_returns_empty():
    strategy = _make_strategy()
    strategy.llm.complete_json.return_value = {"keywords": "not-a-list"}
    result = await strategy._generate_keywords("query")
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_keywords_empty_list_returns_empty():
    strategy = _make_strategy()
    strategy.llm.complete_json.return_value = {"keywords": []}
    result = await strategy._generate_keywords("query")
    assert result == []


# ---------------------------------------------------------------------------
# Tests for _code_vector_search
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_code_vector_search_returns_filtered(monkeypatch):
    strategy = _make_strategy()

    @dataclass
    class SearchHit:
        chunk_id: str
        score: float
        repository_id: str
        branch: str
        file_path: str
        publish_id: str

    hit = SearchHit(
        chunk_id="c1",
        score=0.9,
        repository_id="repo-1",
        branch="main",
        file_path="a.py",
        publish_id="legacy",
    )
    strategy.milvus_code.search.return_value = [hit]
    monkeypatch.setattr(strategy, "_filter_vector_results", MagicMock(return_value=[{"chunk_id": "c1"}]))

    result = await strategy._code_vector_search("query", "repo-1", "main", 5)
    assert result == [{"chunk_id": "c1"}]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_code_vector_search_exception_returns_empty():
    strategy = _make_strategy()
    strategy.milvus_code.search.side_effect = RuntimeError("milvus down")
    result = await strategy._code_vector_search("query", "repo-1", "main", 5)
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_code_vector_search_no_repo_id():
    """When repo_id is None, no repository_id filter is applied."""
    strategy = _make_strategy()
    strategy.milvus_code.search.return_value = []
    result = await strategy._code_vector_search("query", None, "main", 5)
    assert result == []
    call_kwargs = strategy.milvus_code.search.call_args[1]
    # No repo filter means branch-only filter
    assert call_kwargs.get("filters", {}).get("repository_id") is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_code_vector_search_no_branch():
    """When branch is empty string, no branch filter is applied."""
    strategy = _make_strategy()
    strategy.milvus_code.search.return_value = []
    result = await strategy._code_vector_search("query", "repo-1", "", 5)
    assert result == []
    call_kwargs = strategy.milvus_code.search.call_args[1]
    assert "branch" not in (call_kwargs.get("filters") or {})


# ---------------------------------------------------------------------------
# Tests for _wiki_vector_search
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_vector_search_returns_results():
    strategy = _make_strategy()

    @dataclass
    class WikiHit:
        chunk_id: str
        score: float
        repository_id: str
        branch: str
        file_path: str
        publish_id: str

    strategy.milvus_wiki.search.return_value = [
        WikiHit(chunk_id="w1", score=0.8, repository_id="r1", branch="main", file_path="", publish_id="legacy")
    ]
    result = await strategy._wiki_vector_search("query", "r1", "main", 5)
    assert len(result) == 1
    assert result[0]["chunk_id"] == "w1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_vector_search_exception_returns_empty():
    strategy = _make_strategy()
    strategy.milvus_wiki.search.side_effect = RuntimeError("milvus wiki down")
    result = await strategy._wiki_vector_search("query", "r1", "main", 5)
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_vector_search_no_repo_no_branch():
    strategy = _make_strategy()
    strategy.milvus_wiki.search.return_value = []
    result = await strategy._wiki_vector_search("query", None, "", 5)
    assert result == []
    call_kwargs = strategy.milvus_wiki.search.call_args[1]
    assert call_kwargs.get("filters") is None


# ---------------------------------------------------------------------------
# Tests for _code_keyword_search
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_code_keyword_search_returns_rows(monkeypatch):
    strategy = _make_strategy()

    row = SimpleNamespace(id="chunk-1", rank=0.75)
    monkeypatch.setattr(
        "search.strategies.llm_combined_strategy.Chunk.raw",
        MagicMock(return_value=[row]),
    )

    result = strategy._code_keyword_search("auth", 5, "repo-1", "main")
    assert result == [{"chunk_id": "chunk-1", "score": 0.75}]


@pytest.mark.unit
def test_code_keyword_search_no_repo_no_branch(monkeypatch):
    """When repo_id and branch are None, no extra conditions."""
    strategy = _make_strategy()
    monkeypatch.setattr(
        "search.strategies.llm_combined_strategy.Chunk.raw",
        MagicMock(return_value=[]),
    )
    result = strategy._code_keyword_search("auth", 5, None, None)
    assert result == []


@pytest.mark.unit
def test_code_keyword_search_with_repo_only(monkeypatch):
    strategy = _make_strategy()
    monkeypatch.setattr(
        "search.strategies.llm_combined_strategy.Chunk.raw",
        MagicMock(return_value=[]),
    )
    result = strategy._code_keyword_search("auth", 5, "repo-1", None)
    assert result == []


# ---------------------------------------------------------------------------
# Tests for _wiki_keyword_search
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_wiki_keyword_search_returns_rows(monkeypatch):
    strategy = _make_strategy()

    row = SimpleNamespace(id="page-1", rank=0.6)
    monkeypatch.setattr(
        "search.strategies.llm_combined_strategy.WikiPage.raw",
        MagicMock(return_value=[row]),
    )

    result = strategy._wiki_keyword_search("auth", 5, "repo-1", "main")
    assert result == [{"chunk_id": "page-1", "score": 0.6}]


@pytest.mark.unit
def test_wiki_keyword_search_no_repo_no_branch(monkeypatch):
    strategy = _make_strategy()
    monkeypatch.setattr(
        "search.strategies.llm_combined_strategy.WikiPage.raw",
        MagicMock(return_value=[]),
    )
    result = strategy._wiki_keyword_search("auth", 5, None, None)
    assert result == []


@pytest.mark.unit
def test_wiki_keyword_search_with_branch_only(monkeypatch):
    strategy = _make_strategy()
    monkeypatch.setattr(
        "search.strategies.llm_combined_strategy.WikiPage.raw",
        MagicMock(return_value=[]),
    )
    result = strategy._wiki_keyword_search("auth", 5, None, "main")
    assert result == []


# ---------------------------------------------------------------------------
# Tests for _load_code_snippets
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_code_snippets_empty():
    strategy = _make_strategy()
    result = strategy._load_code_snippets([], {})
    assert result == []


@pytest.mark.unit
def test_load_code_snippets_skips_missing(monkeypatch):
    strategy = _make_strategy()
    select_mock = MagicMock()
    select_mock.where.return_value = []  # no chunks found
    monkeypatch.setattr(
        "search.strategies.llm_combined_strategy.Chunk.select",
        MagicMock(return_value=select_mock),
    )
    result = strategy._load_code_snippets(["missing-id"], {"missing-id": 0.9})
    assert result == []


@pytest.mark.unit
def test_load_code_snippets_returns_snippets(monkeypatch):
    strategy = _make_strategy()
    chunk = SimpleNamespace(
        id="c1", content="def foo():", file_path="foo.py", start_line=1, end_line=5
    )
    select_mock = MagicMock()
    select_mock.where.return_value = [chunk]
    monkeypatch.setattr(
        "search.strategies.llm_combined_strategy.Chunk.select",
        MagicMock(return_value=select_mock),
    )
    result = strategy._load_code_snippets(["c1"], {"c1": 0.9})
    assert len(result) == 1
    assert result[0].context_source == SearchContextSource.code
    assert result[0].content == "def foo():"
    assert result[0].file_path == "foo.py"
    assert result[0].score == 0.9


# ---------------------------------------------------------------------------
# Tests for _load_wiki_snippets
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_wiki_snippets_empty():
    strategy = _make_strategy()
    result = strategy._load_wiki_snippets([], {})
    assert result == []


@pytest.mark.unit
def test_load_wiki_snippets_skips_missing(monkeypatch):
    strategy = _make_strategy()
    select_mock = MagicMock()
    select_mock.where.return_value = []
    monkeypatch.setattr(
        "search.strategies.llm_combined_strategy.WikiPage.select",
        MagicMock(return_value=select_mock),
    )
    result = strategy._load_wiki_snippets(["missing-page"], {"missing-page": 0.5})
    assert result == []


@pytest.mark.unit
def test_load_wiki_snippets_returns_snippets(monkeypatch):
    strategy = _make_strategy()
    page = SimpleNamespace(
        id="p1", content="Auth overview", title="Auth", slug="auth", section_path="security"
    )
    select_mock = MagicMock()
    select_mock.where.return_value = [page]
    monkeypatch.setattr(
        "search.strategies.llm_combined_strategy.WikiPage.select",
        MagicMock(return_value=select_mock),
    )
    result = strategy._load_wiki_snippets(["p1"], {"p1": 0.7})
    assert len(result) == 1
    assert result[0].context_source == SearchContextSource.wiki
    assert result[0].content == "Auth overview"
    assert result[0].page_title == "Auth"
    assert result[0].score == 0.7


# ---------------------------------------------------------------------------
# Tests for _rerank
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rerank_empty_candidates():
    strategy = _make_strategy()
    result = await strategy._rerank("query", [], 5)
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rerank_returns_reranked_candidates():
    strategy = _make_strategy()
    candidates = [
        CombinedSnippet(
            context_source=SearchContextSource.code,
            content=f"content {i}",
            score=float(i),
            file_path=f"file{i}.py",
            start_line=i,
            end_line=i + 1,
        )
        for i in range(3)
    ]
    ranked_result = [SimpleNamespace(index=2, relevance_score=0.99)]
    strategy.reranker.rerank = AsyncMock(return_value=ranked_result)

    result = await strategy._rerank("query", candidates, 1)
    assert len(result) == 1
    assert result[0].score == 0.99
    assert result[0].content == "content 2"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rerank_falls_back_on_exception():
    strategy = _make_strategy()
    candidates = [
        CombinedSnippet(
            context_source=SearchContextSource.code,
            content="x",
            score=0.5,
            file_path="x.py",
            start_line=1,
            end_line=2,
        )
        for _ in range(5)
    ]
    strategy.reranker.rerank = AsyncMock(side_effect=RuntimeError("reranker down"))
    result = await strategy._rerank("query", candidates, 3)
    # Returns top_n from candidates without reranking
    assert len(result) == 3


# ---------------------------------------------------------------------------
# Tests for _filter_vector_results
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_filter_vector_results_empty():
    strategy = _make_strategy()
    assert strategy._filter_vector_results([]) == []


@pytest.mark.unit
def test_filter_vector_results_no_indexed_file_keeps_legacy(monkeypatch):
    """When file_key not in active_publish_by_file and publish_id=legacy, keep result."""
    strategy = _make_strategy()
    monkeypatch.setattr(
        strategy, "_get_active_publish_map", MagicMock(return_value={})
    )
    result = [
        {"chunk_id": "c1", "repository_id": "r1", "branch": "main", "file_path": "a.py", "publish_id": "legacy", "score": 0.9}
    ]
    filtered = strategy._filter_vector_results(result)
    assert [r["chunk_id"] for r in filtered] == ["c1"]


@pytest.mark.unit
def test_filter_vector_results_no_indexed_file_drops_non_legacy(monkeypatch):
    """When file_key not in active_publish_by_file and publish_id != legacy, drop."""
    strategy = _make_strategy()
    monkeypatch.setattr(
        strategy, "_get_active_publish_map", MagicMock(return_value={})
    )
    result = [
        {"chunk_id": "c1", "repository_id": "r1", "branch": "main", "file_path": "a.py", "publish_id": "batch-123", "score": 0.9}
    ]
    filtered = strategy._filter_vector_results(result)
    assert filtered == []


@pytest.mark.unit
def test_filter_vector_results_active_publish_matches(monkeypatch):
    """When publish_id matches active_publish_id, keep result."""
    strategy = _make_strategy()
    monkeypatch.setattr(
        strategy,
        "_get_active_publish_map",
        MagicMock(return_value={("r1", "main", "a.py"): "batch-123"}),
    )
    result = [
        {"chunk_id": "c1", "repository_id": "r1", "branch": "main", "file_path": "a.py", "publish_id": "batch-123", "score": 0.9},
        {"chunk_id": "c2", "repository_id": "r1", "branch": "main", "file_path": "a.py", "publish_id": "old-batch", "score": 0.5},
    ]
    filtered = strategy._filter_vector_results(result)
    assert [r["chunk_id"] for r in filtered] == ["c1"]


@pytest.mark.unit
def test_filter_vector_results_active_publish_none_drops_all(monkeypatch):
    """When active_publish_id is None, no publish_id can match, drop all."""
    strategy = _make_strategy()
    monkeypatch.setattr(
        strategy,
        "_get_active_publish_map",
        MagicMock(return_value={("r1", "main", "a.py"): None}),
    )
    result = [
        {"chunk_id": "c1", "repository_id": "r1", "branch": "main", "file_path": "a.py", "publish_id": "batch-123", "score": 0.9},
    ]
    filtered = strategy._filter_vector_results(result)
    assert filtered == []


@pytest.mark.unit
def test_filter_vector_results_missing_publish_id_defaults_legacy(monkeypatch):
    """When result has no publish_id, it defaults to 'legacy'."""
    strategy = _make_strategy()
    monkeypatch.setattr(
        strategy, "_get_active_publish_map", MagicMock(return_value={})
    )
    result = [
        {"chunk_id": "c1", "repository_id": "r1", "branch": "main", "file_path": "a.py", "score": 0.9}
    ]
    filtered = strategy._filter_vector_results(result)
    # No publish_id → defaults to "legacy", key not in map → keep if legacy
    assert [r["chunk_id"] for r in filtered] == ["c1"]


# ---------------------------------------------------------------------------
# Tests for _get_active_publish_map
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_active_publish_map_empty():
    strategy = _make_strategy()
    result = strategy._get_active_publish_map([])
    assert result == {}


@pytest.mark.unit
def test_get_active_publish_map_with_object_rows(monkeypatch):
    strategy = _make_strategy()
    rows = [
        SimpleNamespace(repository_id="r1", branch_name="main", file_path="a.py", active_publish_id="batch-1"),
        SimpleNamespace(repository_id="r1", branch_name="main", file_path="b.py", active_publish_id=None),
    ]
    select_mock = MagicMock()
    select_mock.where.return_value = rows
    monkeypatch.setattr(
        "search.strategies.llm_combined_strategy.IndexedFile.select",
        MagicMock(return_value=select_mock),
    )

    result = strategy._get_active_publish_map([("r1", "main", "a.py"), ("r1", "main", "b.py")])
    assert result == {
        ("r1", "main", "a.py"): "batch-1",
        ("r1", "main", "b.py"): None,
    }


@pytest.mark.unit
def test_get_active_publish_map_with_tuple_rows(monkeypatch):
    """Cover the hasattr(rows, 'tuples') branch."""
    strategy = _make_strategy()
    tuple_rows = [("r1", "main", "a.py", "batch-1")]

    class _RowsWithTuples:
        def tuples(self):
            return tuple_rows

    select_mock = MagicMock()
    select_mock.where.return_value = _RowsWithTuples()
    monkeypatch.setattr(
        "search.strategies.llm_combined_strategy.IndexedFile.select",
        MagicMock(return_value=select_mock),
    )

    result = strategy._get_active_publish_map([("r1", "main", "a.py")])
    assert result == {("r1", "main", "a.py"): "batch-1"}


# ---------------------------------------------------------------------------
# Integration test for the full search() method
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_full_flow_returns_combined_result(monkeypatch):
    """Test the full search() flow with all sub-operations mocked."""
    strategy = _make_strategy()

    # Resolve repo id
    monkeypatch.setattr(strategy, "_resolve_repo_id", MagicMock(return_value="repo-uuid"))

    # No vector results
    monkeypatch.setattr(strategy, "_code_vector_search", AsyncMock(return_value=[]))
    monkeypatch.setattr(strategy, "_wiki_vector_search", AsyncMock(return_value=[]))

    # No keyword results
    monkeypatch.setattr(strategy, "_code_keyword_search", MagicMock(return_value=[]))
    monkeypatch.setattr(strategy, "_wiki_keyword_search", MagicMock(return_value=[]))

    # No snippets loaded
    monkeypatch.setattr(strategy, "_load_code_snippets", MagicMock(return_value=[]))
    monkeypatch.setattr(strategy, "_load_wiki_snippets", MagicMock(return_value=[]))

    # Rerank returns empty
    monkeypatch.setattr(strategy, "_rerank", AsyncMock(return_value=[]))

    result = await strategy.search(_make_request())
    assert isinstance(result, CombinedSearchResult)
    assert result.query == "find auth code"
    assert result.total_results == 0
    assert result.snippets == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_uses_llm_query_when_keywords_generated(monkeypatch):
    """When LLM generates keywords, they're used for the keyword searches."""
    strategy = _make_strategy()
    monkeypatch.setattr(strategy, "_resolve_repo_id", MagicMock(return_value=None))
    monkeypatch.setattr(strategy, "_code_vector_search", AsyncMock(return_value=[]))
    monkeypatch.setattr(strategy, "_wiki_vector_search", AsyncMock(return_value=[]))

    code_kw = MagicMock(return_value=[])
    wiki_kw = MagicMock(return_value=[])
    monkeypatch.setattr(strategy, "_code_keyword_search", code_kw)
    monkeypatch.setattr(strategy, "_wiki_keyword_search", wiki_kw)
    monkeypatch.setattr(strategy, "_load_code_snippets", MagicMock(return_value=[]))
    monkeypatch.setattr(strategy, "_load_wiki_snippets", MagicMock(return_value=[]))
    monkeypatch.setattr(strategy, "_rerank", AsyncMock(return_value=[]))

    # LLM returns keywords
    strategy.llm.complete_json.return_value = {"keywords": ["auth", "token"]}

    await strategy.search(_make_request(query="authentication"))

    # _code_keyword_search called twice (original query + llm query)
    assert code_kw.call_count == 2
    calls = [c[0][0] for c in code_kw.call_args_list]
    assert "authentication" in calls
    assert "auth token" in calls


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_with_snippets_and_reranking(monkeypatch):
    """Full flow with actual snippets - covers load and rerank paths."""
    strategy = _make_strategy()
    monkeypatch.setattr(strategy, "_resolve_repo_id", MagicMock(return_value="r1"))
    monkeypatch.setattr(strategy, "_code_vector_search", AsyncMock(return_value=[]))
    monkeypatch.setattr(strategy, "_wiki_vector_search", AsyncMock(return_value=[]))
    monkeypatch.setattr(strategy, "_code_keyword_search", MagicMock(return_value=[{"chunk_id": "c1", "score": 0.8}]))
    monkeypatch.setattr(strategy, "_wiki_keyword_search", MagicMock(return_value=[]))

    code_snippet = CombinedSnippet(
        context_source=SearchContextSource.code,
        content="auth code",
        score=0.8,
        file_path="auth.py",
        start_line=1,
        end_line=5,
    )
    monkeypatch.setattr(strategy, "_load_code_snippets", MagicMock(return_value=[code_snippet]))
    monkeypatch.setattr(strategy, "_load_wiki_snippets", MagicMock(return_value=[]))

    strategy.reranker.rerank = AsyncMock(return_value=[SimpleNamespace(index=0, relevance_score=0.95)])

    result = await strategy.search(_make_request())
    assert result.total_results == 1
    assert len(result.snippets) == 1
    assert result.snippets[0].score == 0.95
