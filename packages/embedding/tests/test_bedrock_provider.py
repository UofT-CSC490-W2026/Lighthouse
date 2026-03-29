from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from embedding.bedrock_provider import BedrockEmbeddingProvider


def _make_invoke_response(embedding: list[float]) -> dict[str, io.BytesIO]:
    payload = json.dumps({"embedding": embedding}).encode("utf-8")
    return {"body": io.BytesIO(payload)}


@pytest.mark.unit
@patch("embedding.bedrock_provider.boto3.client")
def test_embed_batch_single_text(mock_boto_client):
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client
    mock_client.invoke_model.return_value = _make_invoke_response([0.1, 0.2, 0.3])

    provider = BedrockEmbeddingProvider()
    result = provider.embed_batch(["hello"])

    assert result == [[0.1, 0.2, 0.3]]
    mock_client.invoke_model.assert_called_once()


@pytest.mark.unit
@patch("embedding.bedrock_provider.boto3.client")
def test_embed_batch_multiple_texts_preserves_order(mock_boto_client):
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client
    mock_client.invoke_model.side_effect = [
        _make_invoke_response([1.0, 0.0]),
        _make_invoke_response([0.0, 1.0]),
    ]

    provider = BedrockEmbeddingProvider()
    result = provider.embed_batch(["first", "second"])

    assert result == [[1.0, 0.0], [0.0, 1.0]]
    assert mock_client.invoke_model.call_count == 2


@pytest.mark.unit
@patch("embedding.bedrock_provider.boto3.client")
def test_embed_batch_empty_short_circuits(mock_boto_client):
    provider = BedrockEmbeddingProvider()
    result = provider.embed_batch([])

    assert result == []
    mock_boto_client.assert_called_once()
    mock_boto_client.return_value.invoke_model.assert_not_called()


@pytest.mark.unit
@patch("embedding.bedrock_provider.boto3.client")
def test_embed_batch_passes_model_and_dimensions(mock_boto_client):
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client
    mock_client.invoke_model.return_value = _make_invoke_response([0.5, 0.6])

    provider = BedrockEmbeddingProvider(
        model="amazon.titan-embed-text-v2:0",
        dimensions=512,
        normalize=True,
    )
    provider.embed_batch(["hello"])

    call = mock_client.invoke_model.call_args
    assert call.kwargs["modelId"] == "amazon.titan-embed-text-v2:0"
    payload = json.loads(call.kwargs["body"])
    assert payload["inputText"] == "hello"
    assert payload["dimensions"] == 512
    assert payload["normalize"] is True


@pytest.mark.unit
@patch("embedding.bedrock_provider.boto3.client")
def test_embed_batch_raises_on_missing_embedding(mock_boto_client):
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client
    mock_client.invoke_model.return_value = {"body": io.BytesIO(b"{}")}

    provider = BedrockEmbeddingProvider()

    with pytest.raises(RuntimeError, match="embedding vector"):
        provider.embed_batch(["hello"])


@pytest.mark.unit
@patch("embedding.bedrock_provider.boto3.client")
def test_embed_batch_retries_with_shorter_text_on_token_limit(mock_boto_client):
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client
    mock_client.invoke_model.side_effect = [
        RuntimeError("Too many input tokens. Max input tokens: 8192"),
        _make_invoke_response([0.7, 0.8]),
    ]

    provider = BedrockEmbeddingProvider()
    text = "x" * 1000
    result = provider.embed_batch([text])

    assert result == [[0.7, 0.8]]
    assert mock_client.invoke_model.call_count == 2

    first_payload = json.loads(mock_client.invoke_model.call_args_list[0].kwargs["body"])
    second_payload = json.loads(mock_client.invoke_model.call_args_list[1].kwargs["body"])
    assert len(second_payload["inputText"]) < len(first_payload["inputText"])
