from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from db import DatabaseManager
from fastapi import FastAPI
from shared.config import MILVUS_COLLECTION_NAME
from shared.schemas.search import SearchMethod, SearchRequest, SearchResult
from vectordb import MilvusClient

from search.config import SearchSettings
from embedding import EmbeddingProvider, OpenAIEmbeddingProvider
from search.registry import StrategyRegistry
from search.strategies.hybrid_strategy import HybridSearchStrategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

        db_manager = DatabaseManager(s.postgres_dsn)
        db_manager.connect()

        milvus = MilvusClient(
            uri=s.milvus_uri,
            collection_name=MILVUS_COLLECTION_NAME,
        )

        emb = _embedder or OpenAIEmbeddingProvider(api_key=s.openai_api_key)

        registry = StrategyRegistry()
        registry.register(
            SearchMethod.hybrid,
            HybridSearchStrategy(db_manager=db_manager, milvus=milvus, embedder=emb),
        )

        app.state.registry = registry

        logger.info("Search service initialized — available methods: %s", registry.available())
        yield

        milvus.close()
        db_manager.close()

    return FastAPI(title="Lighthouse Search Service", lifespan=lifespan)


app = create_app()


@app.post("/search", response_model=SearchResult)
async def search(requests: list[SearchRequest]) -> SearchResult:
    return await app.state.registry.search(requests)


@app.get("/search/methods")
async def list_methods():
    registry: StrategyRegistry = app.state.registry
    return {"methods": registry.available()}


@app.get("/health")
async def health():
    return {"status": "ok"}
