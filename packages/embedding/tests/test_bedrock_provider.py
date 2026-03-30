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


@pytest.mark.unit
@patch("embedding.bedrock_provider.boto3.client")
def test_embed_with_region_name(mock_boto_client):
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client
    mock_client.invoke_model.return_value = _make_invoke_response([0.1, 0.2])

    provider = BedrockEmbeddingProvider(region_name="us-west-2")
    result = provider.embed_batch(["hello"])

    assert result == [[0.1, 0.2]]
    mock_boto_client.assert_called_once_with("bedrock-runtime", region_name="us-west-2")


@pytest.mark.unit
@patch("embedding.bedrock_provider.boto3.client")
def test_embed_body_is_none_raises(mock_boto_client):
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client
    mock_client.invoke_model.return_value = {"body": None}

    provider = BedrockEmbeddingProvider()
    with pytest.raises(RuntimeError, match="did not include a body"):
        provider.embed_batch(["hello"])


@pytest.mark.unit
@patch("embedding.bedrock_provider.boto3.client")
def test_embed_body_as_string(mock_boto_client):
    """Body can arrive as a raw JSON string (not bytes)."""
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client
    payload = json.dumps({"embedding": [0.5, 0.6]})
    mock_client.invoke_model.return_value = {"body": payload}

    provider = BedrockEmbeddingProvider()
    result = provider.embed_batch(["hello"])
    assert result == [[0.5, 0.6]]


@pytest.mark.unit
@patch("embedding.bedrock_provider.boto3.client")
def test_embed_body_unsupported_type_raises(mock_boto_client):
    """Body that is not bytes, str, or readable should raise RuntimeError."""
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client
    mock_client.invoke_model.return_value = {"body": 12345}

    provider = BedrockEmbeddingProvider()
    with pytest.raises(RuntimeError, match="must be bytes, str, or a readable stream"):
        provider.embed_batch(["hello"])


@pytest.mark.unit
@patch("embedding.bedrock_provider.boto3.client")
def test_is_token_limit_error_with_client_error(mock_boto_client):
    from botocore.exceptions import ClientError

    mock_boto_client.return_value = MagicMock()
    provider = BedrockEmbeddingProvider()

    exc = ClientError(
        {"Error": {"Code": "ValidationException", "Message": "Too many input tokens."}},
        "InvokeModel",
    )
    assert provider._is_token_limit_error(exc) is True


@pytest.mark.unit
@patch("embedding.bedrock_provider.boto3.client")
def test_shorten_text_returns_unchanged_when_too_short(mock_boto_client):
    mock_boto_client.return_value = MagicMock()
    provider = BedrockEmbeddingProvider()

    short_text = "x" * 100  # less than _MIN_RETRY_TEXT_LENGTH (256)
    result = provider._shorten_text(short_text)
    assert result == short_text


@pytest.mark.unit
@patch("embedding.bedrock_provider.boto3.client")
def test_shorten_text_truncates_when_target_very_small(mock_boto_client):
    """When target_length is tiny (< marker size + 2), should just truncate."""
    mock_boto_client.return_value = MagicMock()
    provider = BedrockEmbeddingProvider()

    # Override _TRUNCATION_RATIO to produce a very small target
    original_ratio = provider._TRUNCATION_RATIO
    provider._TRUNCATION_RATIO = 0.001  # target will be near _MIN_RETRY_TEXT_LENGTH
    text = "a" * 260  # just above minimum
    result = provider._shorten_text(text)
    provider._TRUNCATION_RATIO = original_ratio

    assert len(result) < len(text)


@pytest.mark.unit
@patch("embedding.bedrock_provider.boto3.client")
def test_embed_exhausts_max_retries_raises(mock_boto_client):
    """After _MAX_TRUNCATION_ATTEMPTS with continuing token limit errors, raise."""
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client

    # Always fail with token limit error
    mock_client.invoke_model.side_effect = RuntimeError(
        "Too many input tokens. Max input tokens: 8192"
    )

    provider = BedrockEmbeddingProvider()
    text = "x" * 5000
    with pytest.raises(RuntimeError, match="repeated shortening attempts"):
        provider.embed_batch([text])
