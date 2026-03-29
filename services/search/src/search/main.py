from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from db import DatabaseManager
from fastapi import Depends, FastAPI
from shared.auth import verify_internal_token
from shared.config import EMBEDDING_MODEL, MILVUS_COLLECTION_NAME
from shared.schemas.search import SearchRequest, SearchResult
from embedding import EmbeddingProvider, OpenAIEmbeddingProvider
from vectordb import MilvusClient

from search.config import SearchSettings
from search.strategies.hybrid_strategy import HybridSearchStrategy
from search.strategies.search_strategy import SearchStrategy

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
        app.state.settings = s

        db_manager = DatabaseManager(s.postgres_dsn)
        db_manager.connect()

        milvus = MilvusClient(
            uri=s.milvus_uri,
            collection_name=MILVUS_COLLECTION_NAME,
        )

        emb = _embedder or OpenAIEmbeddingProvider(api_key=s.openai_api_key)

        app.state.strategy = HybridSearchStrategy(
            db_manager=db_manager,
            milvus=milvus,
            embedder=emb,
        )

        logger.info("Search service initialized")
        yield

        milvus.close()
        db_manager.close()

    return FastAPI(title="Lighthouse Search Service", lifespan=lifespan)


app = create_app(
    settings=SearchSettings(),
    embedder=OpenAIEmbeddingProvider(api_key=SearchSettings().openai_api_key, model=EMBEDDING_MODEL),
)


@app.post("/search", response_model=SearchResult, dependencies=[Depends(verify_internal_token)])
async def search(request: SearchRequest) -> SearchResult:
    strategy: SearchStrategy[SearchRequest, SearchResult] = app.state.strategy
    return await strategy.search(request)


@app.get("/health")
async def health():
    return {"status": "ok"}
