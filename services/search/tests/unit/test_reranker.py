from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from search.reranker import BaseReranker, CohereReranker, RankedDocument
from search.reranker.base_reranker import RankedDocument as DirectRankedDocument
from search.reranker.cohere_reranker import COHERE_DEFAULT_RERANK_MODEL


class StubReranker(BaseReranker):
    async def rerank(
        self, query: str, documents: list[str], top_n: int | None = None
    ) -> list[RankedDocument]:
        return [RankedDocument(index=0, relevance_score=1.0)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_base_reranker_contract():
    reranker = StubReranker()

    result = await reranker.rerank("query", ["doc"])

    assert result == [RankedDocument(index=0, relevance_score=1.0)]


@pytest.mark.unit
def test_ranked_document_export():
    ranked = RankedDocument(index=2, relevance_score=0.75)

    assert ranked == DirectRankedDocument(index=2, relevance_score=0.75)


@pytest.mark.unit
@patch("search.reranker.cohere_reranker.cohere.AsyncClientV2")
def test_cohere_reranker_initializes_async_client_with_default_model(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    reranker = CohereReranker(api_key="cohere-key")

    assert reranker.client is mock_client
    assert reranker.model == COHERE_DEFAULT_RERANK_MODEL
    mock_client_cls.assert_called_once_with(api_key="cohere-key")


@pytest.mark.unit
@patch("search.reranker.cohere_reranker.cohere.AsyncClientV2")
def test_cohere_reranker_honors_model_override(mock_client_cls):
    mock_client_cls.return_value = MagicMock()

    reranker = CohereReranker(api_key="cohere-key", model="rerank-custom")

    assert reranker.model == "rerank-custom"


@pytest.mark.unit
@pytest.mark.asyncio
@patch("search.reranker.cohere_reranker.cohere.AsyncClientV2")
async def test_cohere_reranker_returns_empty_for_no_documents(mock_client_cls):
    mock_client = MagicMock()
    mock_client.rerank = AsyncMock()
    mock_client_cls.return_value = mock_client
    reranker = CohereReranker(api_key="cohere-key")

    result = await reranker.rerank("query", [])

    assert result == []
    mock_client.rerank.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
@patch("search.reranker.cohere_reranker.cohere.AsyncClientV2")
async def test_cohere_reranker_maps_results_and_forwards_request(mock_client_cls):
    mock_client = MagicMock()
    mock_client.rerank = AsyncMock(
        return_value=SimpleNamespace(
            results=[
                SimpleNamespace(index=1, relevance_score=0.98),
                SimpleNamespace(index=0, relevance_score=0.42),
            ]
        )
    )
    mock_client_cls.return_value = mock_client
    reranker = CohereReranker(api_key="cohere-key", model="rerank-v3.5")

    result = await reranker.rerank("needle", ["doc-a", "doc-b"], top_n=1)

    assert result == [
        RankedDocument(index=1, relevance_score=0.98),
        RankedDocument(index=0, relevance_score=0.42),
    ]
    mock_client.rerank.assert_awaited_once_with(
        model="rerank-v3.5",
        query="needle",
        documents=["doc-a", "doc-b"],
        top_n=1,
    )
