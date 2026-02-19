"""Unit tests for Milvus-backed dependency context service behavior."""

from __future__ import annotations

import asyncio

from runtime_retrieval import RuntimeChunkHit

from src.services.dependencies import DependencyService
from src.types import GetDependencyContextRequest


class _FakeRetrievalBackend:
    """Simple retrieval backend test double returning predefined hits."""

    def __init__(self, hits: list[RuntimeChunkHit]) -> None:
        self.hits = hits

    async def search(self, **_: object) -> list[RuntimeChunkHit]:
        return self.hits


def _run(coro):
    """Run one async coroutine in a fresh loop for sync pytest tests."""
    return asyncio.run(coro)


def test_dependency_service_maps_hits_and_extracts_version() -> None:
    """Dependency service should populate response fields from retrieval hits."""
    hits = [
        RuntimeChunkHit(
            chunk_id="chunk_dep_001",
            repo_id="octo-org/octo-repo",
            ref="main",
            snapshot_sha="abc123",
            path="requirements.txt",
            chunk_index=0,
            start_char=0,
            end_char=80,
            text="requests==2.32.5\npytest==9.0.2\n",
            text_hash="hash_dep_001",
            score=0.88,
        )
    ]
    service = DependencyService(retrieval_backend=_FakeRetrievalBackend(hits=hits))

    response = _run(
        service.get_dependency_context(
            GetDependencyContextRequest(
                repo_id="octo-org/octo-repo",
                ref="main",
                package="requests",
                api="Session",
            )
        )
    )

    assert response.installed_version == "2.32.5"
    assert response.version_sensitivity is not None
    assert len(response.relevant_docs) == 1
    assert response.relevant_docs[0].location == "requirements.txt:0-80"
    assert "requests" in response.relevant_docs[0].relevance.lower()
