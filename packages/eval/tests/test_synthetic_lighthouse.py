from __future__ import annotations

import json

import pytest
from httpx import Client, MockTransport, Request, Response

from eval.synthetic import prepare_synthetic_workspace
from eval.synthetic.lighthouse import (
    build_synthetic_grep_messages,
    grep_synthetic_code,
    search_synthetic_ast,
    search_synthetic_combined,
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
def test_search_synthetic_code_includes_embedding_overrides(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(task_count=1, seed=3, workspace_root=tmp_path)
    task = workspace.tasks[0].task

    def handler(request: Request) -> Response:
        payload = json.loads(request.content)
        assert payload["embedding_strategy"] == "openai"
        assert payload["embedding_model"] == "text-embedding-3-large"
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
            embedding_strategy="openai",
            embedding_model="text-embedding-3-large",
        )

    assert result.total_results == 1


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
def test_search_synthetic_ast_builds_search_request_for_ast_repo_variant(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(task_count=1, seed=3, workspace_root=tmp_path)
    task = workspace.tasks[0].task

    def handler(request: Request) -> Response:
        assert request.url.path == "/search"
        payload = json.loads(request.content)
        assert payload["github_repo_id"] == 1000000001
        assert payload["branch"] == "main"
        assert task.visible_api_names[0] in payload["query"]
        return Response(
            200,
            json={
                "query": payload["query"],
                "total_results": 1,
                "snippets": [
                    {
                        "file_path": "providerlib/cache.py",
                        "start_line": 10,
                        "end_line": 30,
                        "content": "def build_cache_key(...): ...",
                        "language": "python",
                        "score": 0.88,
                        "reason": "ast chunk",
                    }
                ],
            },
        )

    with Client(transport=MockTransport(handler)) as client:
        result = search_synthetic_ast(
            client=client,
            search_service_url="http://search.test",
            workspace=workspace,
            task=task,
            top_k=4,
        )

    assert result.total_results == 1
    assert result.snippets[0].file_path == "providerlib/cache.py"


@pytest.mark.unit
def test_search_synthetic_combined_fuses_code_wiki_and_ast(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(task_count=1, seed=3, workspace_root=tmp_path)
    task = workspace.tasks[0].task

    def handler(request: Request) -> Response:
        payload = json.loads(request.content)
        repo_id = payload["github_repo_id"]
        if repo_id == 900000001 and payload.get("context_source") == "wiki":
            return Response(
                200,
                json={
                    "query": payload["query"],
                    "total_results": 1,
                    "snippets": [
                        {
                            "page_title": "Cache Keys",
                            "slug": "cache-keys",
                            "section_path": "Reference > Cache",
                            "content_snippet": "Cache keys are lowercased, trimmed, and versioned.",
                            "score": 0.84,
                        }
                    ],
                },
            )
        if repo_id == 900000001:
            return Response(
                200,
                json={
                    "query": payload["query"],
                    "total_results": 1,
                    "snippets": [
                        {
                            "file_path": "providerlib/cache.py",
                            "start_line": 1,
                            "end_line": 3,
                            "content": "def build_cache_key(...): ...",
                            "language": "python",
                            "score": 0.91,
                        }
                    ],
                },
            )
        return Response(
            200,
            json={
                "query": payload["query"],
                "total_results": 1,
                "snippets": [
                    {
                        "file_path": "providerlib/cache.py",
                        "start_line": 10,
                        "end_line": 20,
                        "content": "class CacheKeyBuilder: ...",
                        "language": "python",
                        "score": 0.89,
                    }
                ],
            },
        )

    with Client(transport=MockTransport(handler)) as client:
        result = search_synthetic_combined(
            client=client,
            search_service_url="http://search.test",
            workspace=workspace,
            task=task,
            top_k=6,
        )

    assert result.total_results == 3
    assert {snippet.context_source.value for snippet in result.snippets} == {
        "code",
        "wiki",
        "ast",
    }


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


@pytest.mark.unit
def test_grep_synthetic_code_uses_task_context_terms_and_returns_snippets(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = prepare_synthetic_workspace(task_count=1, seed=3, workspace_root=tmp_path)
    task = workspace.tasks[0].task
    anchor_symbol = task.expected_relevant_symbols[0]
    repo_root = workspace.search_repo_path
    target_file = repo_root / "providerlib" / "metrics.py"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(
        "\n".join(
            [
                "def normalize_percentage(value: int) -> int:",
                "    return max(0, min(100, int(value)))",
                "",
                "def clamp_percentage(value: int) -> int:",
                "    return normalize_percentage(value)",
                f"# {anchor_symbol}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "eval.synthetic.lighthouse._rg_files_for_term",
        lambda **kwargs: (target_file,),
    )

    snippets = grep_synthetic_code(
        repo_root=repo_root,
        task=task,
        top_k=2,
    )

    assert len(snippets) == 1
    assert snippets[0].file_path == "providerlib/metrics.py"
    assert anchor_symbol in snippets[0].content
    assert snippets[0].reason is not None
    assert "grep match" in snippets[0].reason


@pytest.mark.unit
def test_build_synthetic_grep_messages_returns_prompt_per_task(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = prepare_synthetic_workspace(task_count=2, seed=3, workspace_root=tmp_path)
    monkeypatch.setattr(
        "eval.synthetic.lighthouse.grep_synthetic_code",
        lambda **kwargs: [],
    )

    messages = build_synthetic_grep_messages(workspace=workspace, top_k=3)

    assert set(messages) == {prepared.task.task_id for prepared in workspace.tasks}
    for prepared in workspace.tasks:
        assert "Retrieved provider-library code context from Lighthouse:" in messages[
            prepared.task.task_id
        ]
