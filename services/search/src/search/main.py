from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from db import DatabaseManager
from fastapi import Depends, FastAPI, HTTPException
from embedding import EmbeddingProvider, EmbeddingStrategy, get_embedding_provider
from shared.auth import verify_internal_token
from shared.config import (
    DEFAULT_EMBEDDING_STRATEGY,
    MILVUS_COLLECTION_NAME,
    WIKI_MILVUS_COLLECTION_NAME,
    default_embedding_model,
)
from shared.schemas.search import (
    CombinedSearchResult,
    CombinedSnippet,
    SearchContextSource,
    SearchRequest,
    SearchResult,
    WikiSearchRequest,
    WikiSearchResult,
)
from vectordb import MilvusClient

from llm import OpenAILLMProvider
from search.config import SearchSettings
from search.reranker.cohere_reranker import CohereReranker
from search.strategies.hybrid_strategy import BranchNotIndexedError, HybridSearchStrategy
from search.strategies.llm_combined_strategy import LLMCombinedSearchStrategy
from search.strategies.search_strategy import SearchStrategy
from search.strategies.wiki_search_strategy import HybridWikiSearchStrategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _build_embedder(
    settings: SearchSettings,
    embedder: EmbeddingProvider | None,
) -> EmbeddingProvider:
    if embedder is not None:
        return embedder

    normalized_strategy = settings.embedding_strategy.strip().lower()
    if not normalized_strategy:
        normalized_strategy = DEFAULT_EMBEDDING_STRATEGY
    strategy = EmbeddingStrategy(normalized_strategy)

    provider_kwargs: dict[str, object] = {
        "model": settings.embedding_model or default_embedding_model(strategy.value),
    }
    if strategy is EmbeddingStrategy.OPENAI:
        provider_kwargs["api_key"] = settings.openai_api_key

    return get_embedding_provider(strategy, **provider_kwargs)


def create_app(
    settings: SearchSettings | None = None,
    embedder: EmbeddingProvider | None = None,
) -> FastAPI:
    """Factory to create the FastAPI app with optional dependency overrides."""
    _settings = settings
    _embedder = embedder

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s = _settings or SearchSettings()
        app.state.settings = s

        db_manager = DatabaseManager(s.postgres_dsn)
        db_manager.connect()

        milvus = MilvusClient(
            uri=s.milvus_uri,
            collection_name=MILVUS_COLLECTION_NAME,
        )

        emb = _build_embedder(s, _embedder)

        wiki_milvus = MilvusClient(
            uri=s.milvus_uri,
            collection_name=WIKI_MILVUS_COLLECTION_NAME,
        )

        app.state.strategy = HybridSearchStrategy(
            db_manager=db_manager,
            milvus=milvus,
            embedder=emb,
        )
        app.state.wiki_strategy = HybridWikiSearchStrategy(
            db_manager=db_manager,
            milvus=wiki_milvus,
            embedder=emb,
        )

        llm_provider = OpenAILLMProvider(api_key=s.openai_api_key, model=s.llm_model)
        reranker = CohereReranker(api_key=s.cohere_api_key, model=s.rerank_model)
        app.state.llm_combined_strategy = LLMCombinedSearchStrategy(
            db_manager=db_manager,
            milvus_code=milvus,
            milvus_wiki=wiki_milvus,
            embedder=emb,
            llm=llm_provider,
            reranker=reranker,
            llm_reasoning_effort=s.llm_reasoning_effort,
        )

        logger.info("Search service initialized")
        yield

        wiki_milvus.close()
        milvus.close()
        db_manager.close()

    return FastAPI(title="Lighthouse Search Service", lifespan=lifespan)


app = create_app(settings=SearchSettings())


async def _search_impl(
    request: SearchRequest,
) -> SearchResult | WikiSearchResult | CombinedSearchResult:
    requested_sources = request.requested_context_sources()
    if len(requested_sources) == 1 and requested_sources[0] is SearchContextSource.llm_combined:
        llm_strategy: LLMCombinedSearchStrategy = app.state.llm_combined_strategy
        return await llm_strategy.search(request)

    if len(requested_sources) == 1 and requested_sources[0] is SearchContextSource.wiki:
        wiki_search: SearchStrategy[WikiSearchRequest, WikiSearchResult] = app.state.wiki_strategy
        wiki_request = WikiSearchRequest.model_validate(request.model_dump(mode="json"))
        return await wiki_search.search(wiki_request)

    if len(requested_sources) == 1 and requested_sources[0] is SearchContextSource.code:
        code_search: SearchStrategy[SearchRequest, SearchResult] = app.state.strategy
        return await code_search.search(request)

    return await _search_combined(request, requested_sources)


async def _search_combined(
    request: SearchRequest,
    requested_sources: tuple[SearchContextSource, ...],
) -> CombinedSearchResult:
    tasks: list[asyncio.Future[SearchResult | WikiSearchResult] | asyncio.Task[SearchResult | WikiSearchResult]] = []
    for source in requested_sources:
        if source is SearchContextSource.code:
            code_request = SearchRequest.model_validate(
                request.model_copy(
                    update={
                        "context_source": SearchContextSource.code,
                        "context_sources": None,
                    }
                ).model_dump(mode="json")
            )
            tasks.append(asyncio.create_task(app.state.strategy.search(code_request)))
        elif source is SearchContextSource.wiki:
            wiki_request = WikiSearchRequest.model_validate(
                request.model_copy(
                    update={
                        "context_source": SearchContextSource.wiki,
                        "context_sources": None,
                        "top_k": min(request.top_k, 50),
                    }
                ).model_dump(mode="json")
            )
            tasks.append(asyncio.create_task(app.state.wiki_strategy.search(wiki_request)))

    results = await asyncio.gather(*tasks)
    ranked_lists: list[list[CombinedSnippet]] = []
    for source, result in zip(requested_sources, results, strict=True):
        if source is SearchContextSource.code:
            ranked_lists.append(_normalize_code_result(result))
        else:
            ranked_lists.append(_normalize_wiki_result(result))

    fused = _rrf_fuse_combined(ranked_lists)
    return CombinedSearchResult(
        snippets=fused[: request.top_k],
        query=request.query,
        total_results=len(fused),
    )


def _normalize_code_result(result: SearchResult | WikiSearchResult) -> list[CombinedSnippet]:
    validated = SearchResult.model_validate(result.model_dump(mode="json"))
    return [
        CombinedSnippet(
            context_source=SearchContextSource.code,
            content=snippet.content,
            score=snippet.score,
            file_path=snippet.file_path,
            start_line=snippet.start_line,
            end_line=snippet.end_line,
            reason=snippet.reason,
        )
        for snippet in validated.snippets
    ]


def _normalize_wiki_result(result: SearchResult | WikiSearchResult) -> list[CombinedSnippet]:
    validated = WikiSearchResult.model_validate(result.model_dump(mode="json"))
    return [
        CombinedSnippet(
            context_source=SearchContextSource.wiki,
            content=snippet.content_snippet,
            score=snippet.score,
            page_title=snippet.page_title,
            slug=snippet.slug,
            section_path=snippet.section_path,
        )
        for snippet in validated.snippets
    ]


def _rrf_fuse_combined(
    ranked_lists: list[list[CombinedSnippet]],
    *,
    k: int = 60,
) -> list[CombinedSnippet]:
    scores: dict[str, float] = {}
    snippet_map: dict[str, CombinedSnippet] = {}

    for ranked in ranked_lists:
        for rank, snippet in enumerate(ranked):
            key = _combined_snippet_key(snippet)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            snippet_map.setdefault(key, snippet)

    return [
        snippet_map[key].model_copy(update={"score": scores[key]})
        for key in sorted(scores, key=lambda item: scores[item], reverse=True)
    ]


def _combined_snippet_key(snippet: CombinedSnippet) -> str:
    if snippet.context_source is SearchContextSource.code:
        return (
            f"code:{snippet.file_path or ''}:"
            f"{snippet.start_line or 0}:{snippet.end_line or 0}"
        )
    return (
        f"wiki:{snippet.slug or ''}:"
        f"{snippet.section_path or ''}:{snippet.page_title or ''}"
    )


@app.post(
    "/search",
    response_model=SearchResult | WikiSearchResult | CombinedSearchResult,
    dependencies=[Depends(verify_internal_token)],
)
async def search(request: SearchRequest) -> SearchResult | WikiSearchResult | CombinedSearchResult:
    try:
        return await _search_impl(request)
    except BranchNotIndexedError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "BRANCH_UNAVAILABLE",
                "message": str(exc),
                "recoverable": True,
                "context": {
                    "requested_branch": exc.branch,
                    "indexed_branches": exc.indexed_branches,
                },
            },
        ) from exc

@app.post("/search/wiki", response_model=WikiSearchResult, dependencies=[Depends(verify_internal_token)])
async def search_wiki(request: WikiSearchRequest) -> WikiSearchResult:
    try:
        result = await _search_impl(request)
        return WikiSearchResult.model_validate(result.model_dump(mode="json"))
    except BranchNotIndexedError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "BRANCH_UNAVAILABLE",
                "message": str(exc),
                "recoverable": True,
                "context": {
                    "requested_branch": exc.branch,
                    "indexed_branches": exc.indexed_branches,
                },
            },
        ) from exc


@app.get("/health")
async def health():
    return {"status": "ok"}
