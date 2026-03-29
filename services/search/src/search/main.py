from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from db import DatabaseManager
from fastapi import Depends, FastAPI
from embedding import (
    EmbeddingProvider,
    EmbeddingStrategy,
    OpenAIEmbeddingProvider,
    get_embedding_provider,
)
from shared.auth import verify_internal_token
from shared.config import (
    DEFAULT_EMBEDDING_STRATEGY,
    MILVUS_COLLECTION_NAME,
    WIKI_MILVUS_COLLECTION_NAME,
    default_embedding_model,
)
from shared.schemas.search import SearchRequest, SearchResult, WikiSearchRequest, WikiSearchResult
from vectordb import MilvusClient

from search.config import SearchSettings
from search.strategies.hybrid_strategy import HybridSearchStrategy
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

        logger.info("Search service initialized")
        yield

        wiki_milvus.close()
        milvus.close()
        db_manager.close()

    return FastAPI(title="Lighthouse Search Service", lifespan=lifespan)


app = create_app(settings=SearchSettings())


@app.post("/search", response_model=SearchResult, dependencies=[Depends(verify_internal_token)])
async def search(request: SearchRequest) -> SearchResult:
    strategy: SearchStrategy[SearchRequest, SearchResult] = app.state.strategy
    return await strategy.search(request)


@app.post("/search/wiki", response_model=WikiSearchResult, dependencies=[Depends(verify_internal_token)])
async def search_wiki(request: WikiSearchRequest) -> WikiSearchResult:
    strategy: SearchStrategy[WikiSearchRequest, WikiSearchResult] = app.state.wiki_strategy
    return await strategy.search(request)


@app.get("/health")
async def health():
    return {"status": "ok"}
