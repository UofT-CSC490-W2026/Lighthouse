from __future__ import annotations

import json

import pytest
from httpx import Client, MockTransport, Request, Response

from eval.synthetic import prepare_synthetic_workspace
from eval.synthetic.lighthouse import (
    search_synthetic_code,
    search_synthetic_code_and_wiki,
    search_synthetic_wiki,
)


@pytest.mark.unit
def test_search_synthetic_code_builds_search_request_for_shared_repo(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(task_count=1, seed=3, workspace_root=tmp_path)
    task = workspace.tasks[0].task

    def handler(request: Request) -> Response:
        assert request.url.path == "/search"
        payload = json.loads(request.content)
        assert payload["github_repo_id"] == 900000001
        assert payload["branch"] == "main"
        assert task.visible_api_names[0] in payload["query"]
        return Response(
            200,
            json={
                "query": payload["query"],
                "total_results": 1,
                "snippets": [
                    {
                        "file_path": "providerlib/metrics.py",
                        "start_line": 1,
                        "end_line": 4,
                        "content": "def clamp_percentage(value):\n    return 100\n",
                        "language": "python",
                        "score": 0.91,
                        "reason": "contract implementation",
                    }
                ],
            },
        )

    with Client(transport=MockTransport(handler)) as client:
        result = search_synthetic_code(
            client=client,
            search_service_url="http://search.test",
            workspace=workspace,
            task=task,
            top_k=4,
        )

    assert result.total_results == 1
    assert result.snippets[0].file_path == "providerlib/metrics.py"


@pytest.mark.unit
def test_search_synthetic_wiki_builds_search_request_for_shared_repo(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(task_count=1, seed=3, workspace_root=tmp_path)
    task = workspace.tasks[0].task

    def handler(request: Request) -> Response:
        assert request.url.path == "/search"
        payload = json.loads(request.content)
        assert payload["github_repo_id"] == 900000001
        assert payload["branch"] == "main"
        assert payload["context_source"] == "wiki"
        assert task.test_context in payload["query"]
        return Response(
            200,
            json={
                "query": payload["query"],
                "total_results": 1,
                "snippets": [
                    {
                        "page_title": "Metrics",
                        "slug": "metrics",
                        "section_path": "Reference > Percentages",
                        "content_snippet": "Percentages are whole values.",
                        "score": 0.87,
                    }
                ],
            },
        )

    with Client(transport=MockTransport(handler)) as client:
        result = search_synthetic_wiki(
            client=client,
            search_service_url="http://search.test",
            workspace=workspace,
            task=task,
            top_k=3,
        )

    assert result.total_results == 1
    assert result.snippets[0].page_title == "Metrics"


@pytest.mark.unit
def test_search_synthetic_code_and_wiki_builds_combined_search_request(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(task_count=1, seed=3, workspace_root=tmp_path)
    task = workspace.tasks[0].task

    def handler(request: Request) -> Response:
        assert request.url.path == "/search"
        payload = json.loads(request.content)
        assert payload["github_repo_id"] == 900000001
        assert payload["branch"] == "main"
        assert payload["context_sources"] == ["code", "wiki"]
        assert task.visible_api_names[0] in payload["query"]
        return Response(
            200,
            json={
                "query": payload["query"],
                "total_results": 2,
                "snippets": [
                    {
                        "context_source": "code",
                        "content": "def build_cache_key(namespace, identifier, *, version='v1'): ...",
                        "file_path": "providerlib/cache.py",
                        "start_line": 1,
                        "end_line": 3,
                        "score": 0.91,
                    },
                    {
                        "context_source": "wiki",
                        "content": "Cache keys are lowercased, trimmed, and versioned.",
                        "page_title": "Cache Keys",
                        "slug": "cache-keys",
                        "section_path": "Reference > Cache",
                        "score": 0.84,
                    },
                ],
            },
        )

    with Client(transport=MockTransport(handler)) as client:
        result = search_synthetic_code_and_wiki(
            client=client,
            search_service_url="http://search.test",
            workspace=workspace,
            task=task,
            top_k=4,
        )

    assert result.total_results == 2
    assert {snippet.context_source for snippet in result.snippets} == {"code", "wiki"}


@pytest.mark.unit
def test_search_synthetic_code_surfaces_migration_hint_on_server_error(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(task_count=1, seed=3, workspace_root=tmp_path)
    task = workspace.tasks[0].task

    def handler(request: Request) -> Response:
        return Response(500, text="Internal Server Error")

    with Client(transport=MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="out-of-date database schema"):
            search_synthetic_code(
                client=client,
                search_service_url="http://search.test",
                workspace=workspace,
                task=task,
                top_k=4,
            )
