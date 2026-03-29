from __future__ import annotations

import pytest
from httpx import Client, MockTransport, Request, Response

from eval.lighthouse import RepoRegistryEntry
from eval.slice import SWEBenchTask
from eval.wiki import get_wiki_status, search_lighthouse_wiki


@pytest.mark.unit
def test_get_wiki_status_returns_none_for_missing_generation() -> None:
    def handler(_: Request) -> Response:
        return Response(404, json={"detail": "not found"})

    with Client(transport=MockTransport(handler)) as client:
        status = get_wiki_status(
            client=client,
            ingestion_url="http://ingestion.test",
            github_repo_id=123,
            branch="main",
        )

    assert status is None


@pytest.mark.unit
def test_search_lighthouse_wiki_parses_search_response() -> None:
    def handler(request: Request) -> Response:
        assert request.url.path == "/search/wiki"
        return Response(
            200,
            json={
                "query": "Fix the bug",
                "total_results": 1,
                "snippets": [
                    {
                        "page_title": "Page One",
                        "slug": "page-one",
                        "section_path": "Overview",
                        "content_snippet": "Helpful context",
                        "score": 0.87,
                    }
                ],
            },
        )

    task = SWEBenchTask(
        instance_id="example__repo-1",
        repo="example/repo",
        base_commit="deadbeef",
        version="1.0",
        problem_statement="Fix the bug",
    )
    repo_entry = RepoRegistryEntry(github_repo_id=42, branch="main")

    with Client(transport=MockTransport(handler)) as client:
        result = search_lighthouse_wiki(
            client=client,
            search_service_url="http://search.test",
            task=task,
            repo_entry=repo_entry,
            top_k=3,
        )

    assert result.total_results == 1
    assert len(result.snippets) == 1
    assert result.snippets[0].page_title == "Page One"
