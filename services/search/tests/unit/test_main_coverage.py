from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from shared.schemas.search import SearchRequest, SearchResult
from search.main import create_app, health, search
from search.strategies.hybrid_strategy import BranchNotIndexedError, HybridSearchStrategy


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_app_lifespan_initializes_and_closes(monkeypatch):
    settings = SimpleNamespace(
        postgres_dsn="postgres://example",
        milvus_uri="http://milvus",
        openai_api_key="key",
    )
    db_manager = MagicMock()
    milvus = MagicMock()
    embedder = MagicMock()
    strategy = MagicMock()

    monkeypatch.setattr("search.main.DatabaseManager", MagicMock(return_value=db_manager))
    monkeypatch.setattr("search.main.MilvusClient", MagicMock(return_value=milvus))
    monkeypatch.setattr("search.main.HybridSearchStrategy", MagicMock(return_value=strategy))

    app = create_app(settings=settings, embedder=embedder)

    async with app.router.lifespan_context(app):
        assert app.state.strategy is strategy

    db_manager.connect.assert_called_once_with()
    db_manager.close.assert_called_once_with()
    milvus.close.assert_called_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_endpoint_uses_app_strategy(monkeypatch):
    strategy = SimpleNamespace(search=AsyncMock(return_value=SearchResult(snippets=[], query="q", total_results=0)))
    monkeypatch.setattr("search.main.app", SimpleNamespace(state=SimpleNamespace(strategy=strategy)))

    result = await search(SearchRequest(query="q", github_repo_id=1))

    assert result.query == "q"
    strategy.search.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_endpoint_returns_404_for_unindexed_branch(monkeypatch):
    strategy = SimpleNamespace(
        search=AsyncMock(side_effect=BranchNotIndexedError('Branch requested not indexed or does not exist: "dev"'))
    )
    monkeypatch.setattr("search.main.app", SimpleNamespace(state=SimpleNamespace(strategy=strategy)))

    with pytest.raises(HTTPException) as exc_info:
        await search(SearchRequest(query="q", github_repo_id=1, branch="dev"))

    assert exc_info.value.status_code == 404
    assert 'Branch requested not indexed or does not exist: "dev"' in str(exc_info.value.detail)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_endpoint():
    assert await health() == {"status": "ok"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hybrid_strategy_handles_vector_failure_and_missing_chunk(monkeypatch):
    @contextmanager
    def connection_context():
        yield

    db_manager = SimpleNamespace(connection_context=connection_context)
    embedder = MagicMock()
    embedder.embed_single.side_effect = RuntimeError("boom")
    milvus = MagicMock()
    strategy = HybridSearchStrategy(db_manager=db_manager, milvus=milvus, embedder=embedder)

    monkeypatch.setattr("search.strategies.hybrid_strategy.Repository.get_or_none", MagicMock(return_value=None))
    monkeypatch.setattr(strategy, "_keyword_search", MagicMock(return_value=[]))
    monkeypatch.setattr(
        strategy,
        "_rrf_fusion",
        MagicMock(return_value=[{"chunk_id": "missing", "score": 1.0}]),
    )

    select_query = MagicMock()
    select_query.where.return_value = []
    monkeypatch.setattr("search.strategies.hybrid_strategy.Chunk.select", MagicMock(return_value=select_query))

    result = await strategy.search(SearchRequest(query="q", github_repo_id=99, top_k=1))

    assert result.total_results == 1
    assert result.snippets == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hybrid_strategy_raises_when_repo_branch_is_not_indexed(monkeypatch):
    @contextmanager
    def connection_context():
        yield

    db_manager = SimpleNamespace(connection_context=connection_context)
    strategy = HybridSearchStrategy(
        db_manager=db_manager,
        milvus=MagicMock(),
        embedder=MagicMock(),
    )
    repo = SimpleNamespace(id="repo-1")

    monkeypatch.setattr("search.strategies.hybrid_strategy.Repository.get_or_none", MagicMock(return_value=repo))
    monkeypatch.setattr(strategy, "_is_branch_indexed", MagicMock(return_value=False))

    with pytest.raises(BranchNotIndexedError, match='Branch requested not indexed or does not exist: "dev"'):
        await strategy.search(SearchRequest(query="q", github_repo_id=1, branch="dev"))


@pytest.mark.unit
def test_is_branch_indexed_rejects_blank_branch_without_hitting_db():
    strategy = HybridSearchStrategy(
        db_manager=MagicMock(),
        milvus=MagicMock(),
        embedder=MagicMock(),
    )

    assert strategy._is_branch_indexed("repo-1", "   ") is False
