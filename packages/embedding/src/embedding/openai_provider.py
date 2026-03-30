from __future__ import annotations

import openai

from .base_provider import EmbeddingProvider

OPENAI_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-large"


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by the OpenAI embeddings API."""

    BATCH_SIZE = 2048

    def __init__(
        self,
        api_key: str | None = None,
        model: str = OPENAI_DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        self.client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()
        self.model = model

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            response = self.client.embeddings.create(input=batch, model=self.model)
            for item in response.data:
                all_embeddings.append(item.embedding)

        return all_embeddings
