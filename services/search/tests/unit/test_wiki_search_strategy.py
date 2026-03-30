"""Tests for HybridWikiSearchStrategy covering missing lines."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from search.strategies.wiki_search_strategy import HybridWikiSearchStrategy
from shared.schemas.search import WikiSearchRequest


def _make_strategy():
    @contextmanager
    def connection_context():
        yield

    db_manager = SimpleNamespace(connection_context=connection_context)
    milvus = MagicMock()
    embedder = MagicMock()
    embedder.embed_single.return_value = [0.1] * 8
    return HybridWikiSearchStrategy(db_manager=db_manager, milvus=milvus, embedder=embedder)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_search_returns_empty_when_no_results(monkeypatch):
    """When vector and keyword searches both produce no results, return empty."""
    strategy = _make_strategy()

    monkeypatch.setattr(
        "search.strategies.wiki_search_strategy.Repository.get_or_none",
        MagicMock(return_value=None),
    )
    strategy.milvus.search.return_value = []
    monkeypatch.setattr(strategy, "_keyword_search", MagicMock(return_value=[]))

    result = await strategy.search(WikiSearchRequest(query="q", github_repo_id=1))

    assert result.total_results == 0
    assert result.snippets == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_search_vector_exception_falls_back_to_keyword(monkeypatch):
    """When vector search throws, keyword results are still used."""
    strategy = _make_strategy()

    monkeypatch.setattr(
        "search.strategies.wiki_search_strategy.Repository.get_or_none",
        MagicMock(return_value=None),
    )
    strategy.milvus.search.side_effect = RuntimeError("milvus down")
    monkeypatch.setattr(
        strategy,
        "_keyword_search",
        MagicMock(return_value=[{"chunk_id": "page-1", "score": 0.5}]),
    )

    # page_map will return None for this id since we can't query DB
    page_select = MagicMock()
    page_select.where.return_value = []
    monkeypatch.setattr(
        "search.strategies.wiki_search_strategy.WikiPage.select",
        MagicMock(return_value=page_select),
    )

    result = await strategy.search(WikiSearchRequest(query="q", github_repo_id=1))

    # Total results is 1 (from keyword), but page not found in DB so no snippets
    assert result.total_results == 1
    assert result.snippets == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_search_skips_missing_pages(monkeypatch):
    """When a page_id is in the fused results but not in the DB, it is skipped."""
    strategy = _make_strategy()

    monkeypatch.setattr(
        "search.strategies.wiki_search_strategy.Repository.get_or_none",
        MagicMock(return_value=None),
    )
    strategy.milvus.search.return_value = []
    monkeypatch.setattr(
        strategy,
        "_keyword_search",
        MagicMock(return_value=[{"chunk_id": "missing-id", "score": 0.9}]),
    )

    # page_map returns empty — page not found
    page_select = MagicMock()
    page_select.where.return_value = []
    monkeypatch.setattr(
        "search.strategies.wiki_search_strategy.WikiPage.select",
        MagicMock(return_value=page_select),
    )

    result = await strategy.search(WikiSearchRequest(query="q", github_repo_id=1))
    assert result.snippets == []


@pytest.mark.unit
def test_rrf_fusion_deduplicates_and_sums_scores():
    """A chunk_id appearing in both lists gets higher score."""
    vector_results = [{"chunk_id": "a", "score": 0.9}, {"chunk_id": "b", "score": 0.8}]
    keyword_results = [{"chunk_id": "a", "score": 0.7}, {"chunk_id": "c", "score": 0.6}]

    fused = HybridWikiSearchStrategy._rrf_fusion(vector_results, keyword_results, k=60)
    ids = [r["chunk_id"] for r in fused]

    # "a" should appear first (highest combined score), and only once
    assert ids[0] == "a"
    assert ids.count("a") == 1
    assert set(ids) == {"a", "b", "c"}
