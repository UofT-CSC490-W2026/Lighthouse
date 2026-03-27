from __future__ import annotations

import json
from typing import Any

import boto3
from shared.config import EMBEDDING_DIMENSION, EMBEDDING_MODEL

from .base_provider import EmbeddingProvider


class BedrockEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by AWS Bedrock."""

    def __init__(
        self,
        *,
        model: str = EMBEDDING_MODEL,
        dimensions: int = EMBEDDING_DIMENSION,
        normalize: bool | None = None,
        region_name: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self.normalize = normalize

        if client is None:
            client_kwargs: dict[str, Any] = {}
            if region_name:
                client_kwargs["region_name"] = region_name
            client = boto3.client("bedrock-runtime", **client_kwargs)
        self.client = client

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        # Bedrock text embedding requests are issued per input string.
        return [self._embed_text(text) for text in texts]

    def _embed_text(self, text: str) -> list[float]:
        payload: dict[str, Any] = {
            "inputText": text,
            "dimensions": self.dimensions,
        }
        if self.normalize is not None:
            payload["normalize"] = self.normalize

        response = self.client.invoke_model(
            modelId=self.model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload),
        )
        body = response.get("body")
        if body is None:
            raise RuntimeError("Bedrock embedding response did not include a body.")

        raw_payload: Any
        if hasattr(body, "read"):
            raw_payload = body.read()
        else:
            raw_payload = body

        if isinstance(raw_payload, bytes | bytearray):
            decoded = raw_payload.decode("utf-8")
        elif isinstance(raw_payload, str):
            decoded = raw_payload
        else:
            raise RuntimeError(
                "Bedrock embedding response body must be bytes, str, or a readable stream."
            )

        parsed = json.loads(decoded)
        embedding = parsed.get("embedding")
        if not isinstance(embedding, list):
            raise RuntimeError("Bedrock embedding response did not include an embedding vector.")

        return [float(value) for value in embedding]
