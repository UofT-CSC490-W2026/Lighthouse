from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.schemas.search import SearchRequest, SearchResult
from search.main import _build_embedder, create_app, health, search
from search.strategies.hybrid_strategy import HybridSearchStrategy


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
    wiki_milvus = MagicMock()
    embedder = MagicMock()
    strategy = MagicMock()
    wiki_strategy = MagicMock()

    monkeypatch.setattr("search.main.DatabaseManager", MagicMock(return_value=db_manager))
    monkeypatch.setattr(
        "search.main.MilvusClient",
        MagicMock(side_effect=[milvus, wiki_milvus]),
    )
    monkeypatch.setattr(
        "search.main.HybridSearchStrategy",
        MagicMock(return_value=strategy),
    )
    monkeypatch.setattr(
        "search.main.HybridWikiSearchStrategy",
        MagicMock(return_value=wiki_strategy),
    )

    app = create_app(settings=settings, embedder=embedder)

    async with app.router.lifespan_context(app):
        assert app.state.strategy is strategy

    db_manager.connect.assert_called_once_with()
    db_manager.close.assert_called_once_with()
    milvus.close.assert_called_once_with()
    wiki_milvus.close.assert_called_once_with()


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
async def test_health_endpoint():
    assert await health() == {"status": "ok"}


@pytest.mark.unit
def test_build_embedder_uses_configured_strategy(monkeypatch):
    fake_provider = MagicMock()
    get_provider = MagicMock(return_value=fake_provider)
    monkeypatch.setattr("search.main.get_embedding_provider", get_provider)

    settings = SimpleNamespace(
        embedding_strategy="bedrock",
        embedding_model="amazon.titan-embed-text-v2:0",
        openai_api_key="",
    )

    result = _build_embedder(settings, embedder=None)

    assert result is fake_provider
    get_provider.assert_called_once()
    strategy = get_provider.call_args.args[0]
    kwargs = get_provider.call_args.kwargs
    assert str(strategy) == "bedrock"
    assert kwargs["model"] == "amazon.titan-embed-text-v2:0"
    assert "api_key" not in kwargs


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
