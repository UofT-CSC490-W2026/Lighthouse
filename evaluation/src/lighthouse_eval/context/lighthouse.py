from __future__ import annotations

import logging

import httpx

from lighthouse_eval.context.base import ContextSnippet
from lighthouse_eval.datasets.schema import Task
from shared.schemas.search import HybridRequest, SearchMethod

log = logging.getLogger(__name__)


class LighthouseProvider:
    """Retrieve context from the Lighthouse search service.

    Calls ``POST {search_service_url}/search`` with a list of typed
    ``SearchRequest`` envelopes.  Each entry specifies a ``method`` and its
    corresponding typed ``payload``.

    The ``methods`` parameter selects which search strategies run server-side.
    This enables comparing different retrieval approaches in evaluations::

        context_providers:
          - "lighthouse"              # default (hybrid)
          - "lighthouse:hybrid"       # explicit hybrid
          - "lighthouse:hybrid,..."   # multiple, fused via RRF server-side

    When the search service is not yet running, this returns an empty list and
    logs a warning so that evaluation can still proceed (useful for dry-runs
    and framework testing).
    """

    name: str

    def __init__(
        self,
        *,
        search_service_url: str = "http://localhost:8002",
        top_k: int = 10,
        timeout: float = 30.0,
        methods: list[str] | None = None,
    ) -> None:
        self.search_service_url = search_service_url.rstrip("/")
        self.top_k = top_k
        self.timeout = timeout
        self.methods: list[SearchMethod] = (
            [SearchMethod(m) for m in methods] if methods else [SearchMethod.hybrid]
        )
        self.name = "lighthouse:" + ",".join(m.value for m in self.methods)

    async def get_context(self, task: Task) -> list[ContextSnippet]:
        repo_id: int | None = task.metadata.get("github_repo_id")
        branch: str = task.metadata.get("branch", "main")

        if repo_id is None:
            log.warning("Task %s has no github_repo_id in metadata — skipping search.", task.id)
            return []

        requests = [
            HybridRequest(
                query=task.description,
                github_repo_id=repo_id,
                branch=branch,
                top_k=self.top_k,
            ).model_dump()
            for method in self.methods
            if method == SearchMethod.hybrid
        ]

        if not requests:
            log.warning("No supported methods in %s — skipping search.", self.methods)
            return []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.search_service_url}/search",
                    json=requests,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            log.error(
                "Search service returned %s: %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            return []
        except httpx.RequestError as exc:
            log.warning("Search service unavailable (%s), returning empty context.", exc)
            return []

        return [
            ContextSnippet(
                file_path=s.get("file_path", ""),
                content=s.get("content", ""),
                start_line=s.get("start_line"),
                end_line=s.get("end_line"),
                language=s.get("language"),
                score=s.get("score", 0.0),
                reason=s.get("reason"),
            )
            for s in data.get("snippets", [])
        ]
