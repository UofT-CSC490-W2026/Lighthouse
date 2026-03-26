from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from db import DatabaseManager
from fastapi import FastAPI
from shared.config import MILVUS_COLLECTION_NAME
from shared.schemas.search import SearchMethod, SearchRequest, SearchResult
from vectordb import MilvusClient

from embedding import OpenAIEmbeddingProvider
from search.config import SearchSettings
from search.registry import StrategyRegistry
from search.strategies.hybrid_strategy import HybridSearchStrategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = SearchSettings()

    db_manager = DatabaseManager(settings.postgres_dsn)
    db_manager.connect()

    milvus = MilvusClient(
        uri=settings.milvus_uri,
        collection_name=MILVUS_COLLECTION_NAME,
    )

    embedder = OpenAIEmbeddingProvider(api_key=settings.openai_api_key)

    registry = StrategyRegistry()
    registry.register(
        SearchMethod.hybrid,
        HybridSearchStrategy(db_manager=db_manager, milvus=milvus, embedder=embedder),
    )

    app.state.registry = registry

    logger.info("Search service initialized — available methods: %s", registry.available())
    yield

    milvus.close()
    db_manager.close()


app = FastAPI(title="Lighthouse Search Service", lifespan=lifespan)


@app.post("/search", response_model=SearchResult)
async def search(requests: list[SearchRequest]) -> SearchResult:
    return await app.state.registry.search(requests)


@app.get("/search/methods")
async def list_methods():
    """List available search methods."""
    registry: StrategyRegistry = app.state.registry
    return {"methods": registry.available()}


@app.get("/health")
async def health():
    return {"status": "ok"}
