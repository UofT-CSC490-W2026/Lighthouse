from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from db import DatabaseManager
from fastapi import FastAPI
from shared.config import MILVUS_COLLECTION_NAME
from shared.schemas.search import SearchRequest, SearchResult
from vectordb import MilvusClient

from search.config import SearchSettings
from search.strategies.hybrid_strategy import EmbeddingClient, HybridSearchStrategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = SearchSettings()

    db_manager = DatabaseManager(settings.postgres_dsn)
    db_manager.connect()
    app.state.db_manager = db_manager

    milvus = MilvusClient(
        uri=settings.milvus_uri,
        collection_name=MILVUS_COLLECTION_NAME,
    )
    app.state.milvus = milvus

    embedder = EmbeddingClient(api_key=settings.openai_api_key)
    app.state.strategy = HybridSearchStrategy(
        db_manager=db_manager,
        milvus=milvus,
        embedder=embedder,
    )

    logger.info("Search service initialized")
    yield

    milvus.close()
    db_manager.close()


app = FastAPI(title="Lighthouse Search Service", lifespan=lifespan)


@app.post("/search", response_model=SearchResult)
async def search(request: SearchRequest) -> SearchResult:
    strategy: HybridSearchStrategy = app.state.strategy
    return await strategy.search(request)


@app.get("/health")
async def health():
    return {"status": "ok"}
