from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from db import DatabaseManager
from shared.schemas.search import (
    CodeSnippet,
    CombinedSearchResult,
    HybridRequest,
    SearchContextSource,
    SearchRequest,
    SearchResult,
    WikiSearchRequest,
    WikiSearchResult,
    WikiSnippet,
)
from search.config import SearchSettings
from search.main import _build_embedder, create_app, health, search, search_wiki
from search.strategies.hybrid_strategy import BranchNotIndexedError, HybridSearchStrategy
from search.strategies.llm_combined_strategy import KEYWORD_SYSTEM_PROMPT, LLMCombinedSearchStrategy
from vectordb import MilvusClient


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_app_lifespan_initializes_and_closes(monkeypatch):
    settings = SearchSettings(
        postgres_dsn="postgres://example",
        milvus_uri="http://milvus",
        openai_api_key="key",
        llm_reasoning_effort="none",
    )
    db_manager = MagicMock()
    milvus = MagicMock()
    wiki_milvus = MagicMock()
    embedder = MagicMock()
    strategy = MagicMock()
    wiki_strategy = MagicMock()
    llm_provider = MagicMock()
    reranker = MagicMock()
    llm_combined_strategy = MagicMock()

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
    openai_provider_cls = MagicMock(return_value=llm_provider)
    monkeypatch.setattr("search.main.OpenAILLMProvider", openai_provider_cls)
    cohere_reranker_cls = MagicMock(return_value=reranker)
    monkeypatch.setattr("search.main.CohereReranker", cohere_reranker_cls)
    llm_strategy_cls = MagicMock(return_value=llm_combined_strategy)
    monkeypatch.setattr("search.main.LLMCombinedSearchStrategy", llm_strategy_cls)

    app = create_app(settings=settings, embedder=embedder)

    async with app.router.lifespan_context(app):
        assert app.state.strategy is strategy
        assert app.state.llm_combined_strategy is llm_combined_strategy

    db_manager.connect.assert_called_once_with()
    db_manager.close.assert_called_once_with()
    milvus.close.assert_called_once_with()
    wiki_milvus.close.assert_called_once_with()
    openai_provider_cls.assert_called_once_with(api_key="key", model="gpt-5.4-nano")
    llm_strategy_cls.assert_called_once_with(
        db_manager=db_manager,
        milvus_code=milvus,
        milvus_wiki=wiki_milvus,
        embedder=embedder,
        llm=llm_provider,
        reranker=reranker,
        llm_reasoning_effort="none",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_endpoint_uses_app_strategy(monkeypatch):
    strategy = SimpleNamespace(search=AsyncMock(return_value=SearchResult(snippets=[], query="q", total_results=0)))
    monkeypatch.setattr(
        "search.main.app",
        SimpleNamespace(state=SimpleNamespace(strategy=strategy, wiki_strategy=MagicMock())),
    )

    result = await search(SearchRequest(query="q", github_repo_id=1))

    assert result.query == "q"
    strategy.search.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_endpoint_dispatches_wiki_requests(monkeypatch):
    strategy = MagicMock()
    wiki_strategy = SimpleNamespace(
        search=AsyncMock(return_value=WikiSearchResult(snippets=[], query="q", total_results=0))
    )
    monkeypatch.setattr(
        "search.main.app",
        SimpleNamespace(state=SimpleNamespace(strategy=strategy, wiki_strategy=wiki_strategy)),
    )

    result = await search(WikiSearchRequest(query="q", github_repo_id=1))

    assert result.query == "q"
    wiki_strategy.search.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_endpoint_returns_structured_branch_error(monkeypatch):
    strategy = SimpleNamespace(search=AsyncMock(side_effect=BranchNotIndexedError("dev", indexed_branches=["main"])))
    monkeypatch.setattr(
        "search.main.app",
        SimpleNamespace(state=SimpleNamespace(strategy=strategy, wiki_strategy=MagicMock())),
    )

    with pytest.raises(HTTPException) as exc_info:
        await search(SearchRequest(query="q", github_repo_id=1, branch="dev"))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "BRANCH_UNAVAILABLE"
    assert exc_info.value.detail["context"]["requested_branch"] == "dev"
    assert exc_info.value.detail["context"]["indexed_branches"] == ["main"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_endpoint_fuses_code_and_wiki_requests(monkeypatch):
    strategy = SimpleNamespace(
        search=AsyncMock(
            return_value=SearchResult(
                snippets=[
                    CodeSnippet(
                        file_path="providerlib/cache.py",
                        start_line=1,
                        end_line=2,
                        content="def build_cache_key(...): ...",
                        score=0.8,
                    )
                ],
                query="q",
                total_results=1,
            )
        )
    )
    wiki_strategy = SimpleNamespace(
        search=AsyncMock(
            return_value=WikiSearchResult(
                snippets=[
                    WikiSnippet(
                        page_title="Cache Keys",
                        slug="cache-keys",
                        section_path="Reference > Cache",
                        content_snippet="Cache keys are lowercased and versioned.",
                        score=0.7,
                    )
                ],
                query="q",
                total_results=1,
            )
        )
    )
    monkeypatch.setattr(
        "search.main.app",
        SimpleNamespace(state=SimpleNamespace(strategy=strategy, wiki_strategy=wiki_strategy)),
    )

    result = await search(
        SearchRequest(
            query="q",
            github_repo_id=1,
            context_sources=(
                SearchContextSource.code,
                SearchContextSource.wiki,
            ),
        )
    )
    combined = cast(CombinedSearchResult, result)

    assert combined.query == "q"
    assert len(combined.snippets) == 2
    assert {snippet.context_source for snippet in combined.snippets} == {
        SearchContextSource.code,
        SearchContextSource.wiki,
    }
    strategy.search.assert_awaited_once()
    wiki_strategy.search.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_endpoint():
    assert await health() == {"status": "ok"}


@pytest.mark.unit
def test_build_embedder_falls_back_to_default_when_empty(monkeypatch):
    """When embedding_strategy is empty, DEFAULT_EMBEDDING_STRATEGY is used."""
    fake_provider = MagicMock()
    get_provider = MagicMock(return_value=fake_provider)
    monkeypatch.setattr("search.main.get_embedding_provider", get_provider)

    settings = SearchSettings(
        postgres_dsn="postgres://example",
        milvus_uri="http://milvus",
        embedding_strategy="",  # empty → fallback
        embedding_model="text-embedding-3-large",
        openai_api_key="key",
    )

    result = _build_embedder(settings, embedder=None)
    assert result is fake_provider
    # Should have used DEFAULT_EMBEDDING_STRATEGY (openai)
    strategy = get_provider.call_args.args[0]
    assert str(strategy) == "openai"
    call_kwargs = get_provider.call_args.kwargs
    assert "api_key" in call_kwargs


@pytest.mark.unit
def test_build_embedder_uses_configured_strategy(monkeypatch):
    fake_provider = MagicMock()
    get_provider = MagicMock(return_value=fake_provider)
    monkeypatch.setattr("search.main.get_embedding_provider", get_provider)

    settings = SearchSettings(
        postgres_dsn="postgres://example",
        milvus_uri="http://milvus",
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

    db_manager = cast(object, SimpleNamespace(connection_context=connection_context))
    embedder = MagicMock()
    embedder.embed_single.side_effect = RuntimeError("boom")
    milvus = cast(object, MagicMock())
    strategy = HybridSearchStrategy(
        db_manager=cast("DatabaseManager", db_manager),
        milvus=cast("MilvusClient", milvus),
        embedder=embedder,
    )

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

    result = await strategy.search(HybridRequest(query="q", github_repo_id=99, top_k=1))

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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_endpoint_dispatches_to_llm_combined_strategy(monkeypatch):
    from shared.schemas.search import CombinedSearchResult, CombinedSnippet, SearchContextSource

    llm_combined_strategy = SimpleNamespace(
        search=AsyncMock(
            return_value=CombinedSearchResult(
                snippets=[],
                query="q",
                total_results=0,
            )
        )
    )
    monkeypatch.setattr(
        "search.main.app",
        SimpleNamespace(
            state=SimpleNamespace(
                strategy=MagicMock(),
                wiki_strategy=MagicMock(),
                llm_combined_strategy=llm_combined_strategy,
            )
        ),
    )

    result = await search(
        SearchRequest(
            query="q",
            github_repo_id=1,
            context_sources=(SearchContextSource.llm_combined,),
        )
    )
    assert result.query == "q"
    llm_combined_strategy.search.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_wiki_endpoint_returns_result(monkeypatch):
    from search.main import search_wiki
    from shared.schemas.search import WikiSearchRequest, WikiSearchResult

    wiki_strategy = SimpleNamespace(
        search=AsyncMock(
            return_value=WikiSearchResult(snippets=[], query="q", total_results=0)
        )
    )
    monkeypatch.setattr(
        "search.main.app",
        SimpleNamespace(
            state=SimpleNamespace(
                strategy=MagicMock(),
                wiki_strategy=wiki_strategy,
                llm_combined_strategy=MagicMock(),
            )
        ),
    )

    result = await search_wiki(WikiSearchRequest(query="q", github_repo_id=1))
    assert result.query == "q"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_wiki_endpoint_raises_on_branch_not_indexed(monkeypatch):
    from search.main import search_wiki
    from search.strategies.hybrid_strategy import BranchNotIndexedError
    from shared.schemas.search import WikiSearchRequest
    from fastapi import HTTPException

    wiki_strategy = SimpleNamespace(
        search=AsyncMock(side_effect=BranchNotIndexedError("dev", indexed_branches=["main"]))
    )
    monkeypatch.setattr(
        "search.main.app",
        SimpleNamespace(
            state=SimpleNamespace(
                strategy=MagicMock(),
                wiki_strategy=wiki_strategy,
                llm_combined_strategy=MagicMock(),
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await search_wiki(WikiSearchRequest(query="q", github_repo_id=1, branch="dev"))
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "BRANCH_UNAVAILABLE"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_combined_strategy_passes_reasoning_effort_to_llm():
    llm = MagicMock()
    llm.complete_json.return_value = {"keywords": ["search", "rank"]}
    strategy = LLMCombinedSearchStrategy(
        db_manager=MagicMock(),
        milvus_code=MagicMock(),
        milvus_wiki=MagicMock(),
        embedder=MagicMock(),
        llm=llm,
        reranker=MagicMock(),
        llm_reasoning_effort="none",
    )

    keywords = await strategy._generate_keywords("ranking bug")

    assert keywords == ["search", "rank"]
    llm.complete_json.assert_called_once_with(
        [
            {"role": "system", "content": KEYWORD_SYSTEM_PROMPT},
            {"role": "user", "content": "ranking bug"},
        ],
        reasoning_effort="none",
    )
