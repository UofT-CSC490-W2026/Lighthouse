from __future__ import annotations

from typing import cast

from temporalio import activity
from shared.config import default_embedding_dimension, default_embedding_model

from ...embedding import EmbeddingStrategy, get_embedding_provider
from ...utilities.services import ChunkService
from .helpers import get_settings, make_db
from .inputs import EmbedBatchInput


@activity.defn
async def embed_chunk_batch(input: EmbedBatchInput) -> str:
    """Embed a batch of staging chunks and write vectors back."""
    settings = get_settings()
    db = make_db(settings)
    strategy = EmbeddingStrategy(input.embedding_strategy.strip().lower())
    provider_kwargs: dict[str, object] = {
        "model": settings.embedding_model or default_embedding_model(strategy.value),
    }
    if strategy == EmbeddingStrategy.BEDROCK:
        provider_kwargs["dimensions"] = (
            settings.embedding_dimension or default_embedding_dimension(strategy.value)
        )
    elif settings.openai_api_key:
        provider_kwargs["api_key"] = settings.openai_api_key

    embedder = get_embedding_provider(
        strategy,
        **provider_kwargs,
    )
    try:
        svc = ChunkService(db)
        chunks = svc.read_staging_batch(input.batch_id, input.offset, input.limit)
        if not chunks:
            return "no_chunks"
        texts = [cast(str, c.content) for c in chunks]
        embeddings = embedder.embed_batch(texts)
        svc.write_staging_embeddings(input.batch_id, input.offset, embeddings)
        return f"embedded_{len(chunks)}"
    finally:
        db.close()
