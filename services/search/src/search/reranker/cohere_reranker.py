from __future__ import annotations

from types import SimpleNamespace

try:
    import cohere
except ModuleNotFoundError:  # pragma: no cover - exercised via constructor guard
    cohere = SimpleNamespace(AsyncClientV2=None)

from .base_reranker import BaseReranker, RankedDocument

COHERE_DEFAULT_RERANK_MODEL = "rerank-v4.0-pro"


class CohereReranker(BaseReranker):
    """Reranker backed by Cohere's async v2 rerank API."""

    def __init__(self, api_key: str, model: str = COHERE_DEFAULT_RERANK_MODEL) -> None:
        if cohere.AsyncClientV2 is None:
            raise ModuleNotFoundError(
                "cohere is required to use CohereReranker. Install the optional "
                "search reranker dependency set before enabling Cohere reranking."
            )
        self.client = cohere.AsyncClientV2(api_key=api_key)
        self.model = model

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[RankedDocument]:
        if not documents:
            return []

        response = await self.client.rerank(
            model=self.model,
            query=query,
            documents=documents,
            top_n=top_n,
        )

        return [
            RankedDocument(index=result.index, relevance_score=result.relevance_score)
            for result in response.results
        ]
