from __future__ import annotations

import openai
from shared.config import EMBEDDING_MODEL


class EmbeddingService:
    """Wrapper around OpenAI embeddings API."""

    BATCH_SIZE = 2048

    def __init__(
        self, api_key: str, model: str = EMBEDDING_MODEL
    ) -> None:
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Handles chunking into API-sized batches."""
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            response = self.client.embeddings.create(input=batch, model=self.model)
            for item in response.data:
                all_embeddings.append(item.embedding)

        return all_embeddings

    def embed_single(self, text: str) -> list[float]:
        """Embed a single text string."""
        return self.embed_batch([text])[0]
