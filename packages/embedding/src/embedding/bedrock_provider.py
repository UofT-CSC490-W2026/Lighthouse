from __future__ import annotations

import json
import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError
from shared.config import BEDROCK_EMBEDDING_DIMENSION, BEDROCK_EMBEDDING_MODEL

from .base_provider import EmbeddingProvider

logger = logging.getLogger(__name__)


class BedrockEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by AWS Bedrock."""

    _TOKEN_LIMIT_ERROR_FRAGMENT = "too many input tokens"
    _TRUNCATION_RATIO = 0.75
    _MIN_RETRY_TEXT_LENGTH = 256
    _TRUNCATION_MARKER = "\n...\n"
    _MAX_TRUNCATION_ATTEMPTS = 8

    def __init__(
        self,
        *,
        model: str = BEDROCK_EMBEDDING_MODEL,
        dimensions: int = BEDROCK_EMBEDDING_DIMENSION,
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
        candidate_text = text
        last_error: Exception | None = None

        for _ in range(self._MAX_TRUNCATION_ATTEMPTS):
            try:
                return self._invoke_embedding(candidate_text)
            except Exception as exc:
                if not self._is_token_limit_error(exc):
                    raise
                shortened = self._shorten_text(candidate_text)
                if shortened == candidate_text:
                    raise RuntimeError(
                        "Bedrock embedding input exceeded the model token limit and "
                        "could not be shortened further."
                    ) from exc
                logger.warning(
                    "Bedrock embedding input exceeded token limit; retrying with "
                    "shortened text (%d -> %d chars)",
                    len(candidate_text),
                    len(shortened),
                )
                candidate_text = shortened
                last_error = exc

        raise RuntimeError(
            "Bedrock embedding input exceeded the model token limit after repeated "
            "shortening attempts."
        ) from last_error

    def _invoke_embedding(self, text: str) -> list[float]:
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

    def _is_token_limit_error(self, exc: Exception) -> bool:
        if isinstance(exc, ClientError):
            error = exc.response.get("Error", {})
            message = str(error.get("Message", ""))
        else:
            message = str(exc)
        return self._TOKEN_LIMIT_ERROR_FRAGMENT in message.lower()

    def _shorten_text(self, text: str) -> str:
        if len(text) <= self._MIN_RETRY_TEXT_LENGTH:
            return text

        target_length = max(
            int(len(text) * self._TRUNCATION_RATIO),
            self._MIN_RETRY_TEXT_LENGTH,
        )
        target_length = min(target_length, len(text) - 1)

        if target_length <= len(self._TRUNCATION_MARKER) + 2:
            return text[:target_length]

        head_length = (target_length - len(self._TRUNCATION_MARKER)) // 2
        tail_length = target_length - len(self._TRUNCATION_MARKER) - head_length
        if head_length < 1 or tail_length < 1:
            return text[:target_length]
        return (
            text[:head_length]
            + self._TRUNCATION_MARKER
            + text[-tail_length:]
        )
