from unittest.mock import MagicMock, patch

import pytest

from embedding.openai_provider import OpenAIEmbeddingProvider


def _make_embedding_response(embeddings: list[list[float]]):
    """Build a mock OpenAI embeddings response."""
    response = MagicMock()
    data = []
    for emb in embeddings:
        item = MagicMock()
        item.embedding = emb
        data.append(item)
    response.data = data
    return response


@pytest.mark.unit
@patch("embedding.openai_provider.openai.OpenAI")
def test_embed_batch_single_batch(mock_openai_cls):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.embeddings.create.return_value = _make_embedding_response(
        [[0.1, 0.2], [0.3, 0.4]]
    )

    provider = OpenAIEmbeddingProvider(api_key="fake")
    result = provider.embed_batch(["hello", "world"])

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    mock_client.embeddings.create.assert_called_once()


@pytest.mark.unit
@patch("embedding.openai_provider.openai.OpenAI")
def test_embed_batch_multiple_batches(mock_openai_cls):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client

    texts = [f"text-{i}" for i in range(3000)]
    batch1_embeddings = [[float(i)] for i in range(2048)]
    batch2_embeddings = [[float(i)] for i in range(2048, 3000)]

    mock_client.embeddings.create.side_effect = [
        _make_embedding_response(batch1_embeddings),
        _make_embedding_response(batch2_embeddings),
    ]

    provider = OpenAIEmbeddingProvider(api_key="fake")
    result = provider.embed_batch(texts)

    assert len(result) == 3000
    assert mock_client.embeddings.create.call_count == 2

    first_call_input = mock_client.embeddings.create.call_args_list[0].kwargs["input"]
    second_call_input = mock_client.embeddings.create.call_args_list[1].kwargs["input"]
    assert len(first_call_input) == 2048
    assert len(second_call_input) == 952


@pytest.mark.unit
@patch("embedding.openai_provider.openai.OpenAI")
def test_embed_batch_empty(mock_openai_cls):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client

    provider = OpenAIEmbeddingProvider(api_key="fake")
    result = provider.embed_batch([])

    assert result == []
    mock_client.embeddings.create.assert_not_called()


@pytest.mark.unit
@patch("embedding.openai_provider.openai.OpenAI")
def test_embed_single(mock_openai_cls):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.embeddings.create.return_value = _make_embedding_response(
        [[0.5, 0.6]]
    )

    provider = OpenAIEmbeddingProvider(api_key="fake")
    result = provider.embed_single("hello")

    assert result == [0.5, 0.6]
    mock_client.embeddings.create.assert_called_once()


@pytest.mark.unit
@patch("embedding.openai_provider.openai.OpenAI")
def test_embed_batch_preserves_order(mock_openai_cls):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client

    expected = [[float(i), float(i + 1)] for i in range(5)]
    mock_client.embeddings.create.return_value = _make_embedding_response(expected)

    provider = OpenAIEmbeddingProvider(api_key="fake")
    result = provider.embed_batch([f"text-{i}" for i in range(5)])

    assert result == expected
