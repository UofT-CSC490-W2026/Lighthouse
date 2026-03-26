from __future__ import annotations

from temporalio import activity

from ...embedding import EmbeddingStrategy, get_embedding_provider
from ...utilities.services import ChunkService
from .helpers import get_settings, make_db
from .inputs import EmbedBatchInput


@activity.defn
async def embed_chunk_batch(input: EmbedBatchInput) -> str:
    """Embed a batch of staging chunks and write vectors back."""
    settings = get_settings()
    db = make_db(settings)
    embedder = get_embedding_provider(
        EmbeddingStrategy(input.embedding_strategy),
        api_key=settings.openai_api_key,
    )
    try:
        svc = ChunkService(db)
        chunks = svc.read_staging_batch(input.batch_id, input.offset, input.limit)
        if not chunks:
            return "no_chunks"
        texts = [c.content for c in chunks]
        embeddings = embedder.embed_batch(texts)
        svc.write_staging_embeddings(input.batch_id, input.offset, embeddings)
        return f"embedded_{len(chunks)}"
    finally:
        db.close()
