from __future__ import annotations

import pytest
from shared.schemas.search import CodeSnippet, WikiSnippet

from eval.synthetic import load_synthetic_family, prepare_synthetic_workspace
from eval.synthetic.prompts import (
    build_synthetic_baseline_user_message,
    build_synthetic_code_lighthouse_user_message,
    build_synthetic_search_query,
    build_synthetic_wiki_lighthouse_user_message,
)


@pytest.mark.unit
def test_synthetic_baseline_prompt_avoids_relevant_file_and_patch_leakage(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(task_count=1, seed=490, workspace_root=tmp_path)
    prepared = workspace.tasks[0]
    task = prepared.task

    prompt = build_synthetic_baseline_user_message(prepared)

    assert f"Task ID: {task.task_id}" in prompt
    assert f"Task type: {task.task_type}" in prompt
    assert f"Visible provider APIs: {', '.join(task.visible_api_names)}" in prompt
    assert (
        f"Consumer source files to edit for this task: {', '.join(task.consumer_edit_files)}"
        in prompt
    )
    assert (
        f"Consumer test files for this task: {', '.join(task.consumer_test_files)}"
        in prompt
    )
    first_edit_file = task.consumer_edit_files[0]
    assert (
        f"Use diff headers like `a/{first_edit_file}` and `b/{first_edit_file}`." in prompt
    )
    assert f"File: {first_edit_file}" in prompt
    assert f"File: {task.consumer_test_files[0]}" in prompt
    assert "providerlib/metrics.py" not in prompt
    assert str(task.gold_patch_path.name) not in prompt
    assert str(task.buggy_patch_path.name) not in prompt


@pytest.mark.unit
def test_synthetic_code_prompt_includes_retrieved_snippet_content(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(task_count=1, seed=490, workspace_root=tmp_path)
    prepared = workspace.tasks[0]
    task = prepared.task
    snippets = [
        CodeSnippet(
            file_path="providerlib/metrics.py",
            start_line=1,
            end_line=4,
            content="def clamp_percentage(value):\n    return 100\n",
            language="python",
            score=0.91,
            reason="API contract implementation",
        )
    ]

    prompt = build_synthetic_code_lighthouse_user_message(prepared, snippets)

    assert "Retrieved provider-library code context from Lighthouse:" in prompt
    assert "Current consumer repository context:" in prompt
    assert "File: providerlib/metrics.py" in prompt
    assert "Reason: API contract implementation" in prompt
    assert "def clamp_percentage(value):" in prompt


@pytest.mark.unit
def test_synthetic_wiki_prompt_includes_retrieved_wiki_snippet(tmp_path) -> None:
    workspace = prepare_synthetic_workspace(task_count=1, seed=490, workspace_root=tmp_path)
    prepared = workspace.tasks[0]
    task = prepared.task
    snippets = [
        WikiSnippet(
            page_title="Metrics",
            slug="metrics",
            section_path="Reference > Percentages",
            content_snippet="Percentages are already whole values between 0 and 100.",
            score=0.88,
        )
    ]

    prompt = build_synthetic_wiki_lighthouse_user_message(prepared, snippets)

    assert "Retrieved provider-library wiki context from Lighthouse:" in prompt
    assert "Page: Metrics" in prompt
    assert "Slug: metrics" in prompt
    assert "Percentages are already whole values between 0 and 100." in prompt


@pytest.mark.unit
def test_synthetic_search_query_uses_visible_api_and_test_context() -> None:
    task = load_synthetic_family().tasks[0]

    query = build_synthetic_search_query(task)

    assert task.problem_statement in query
    assert "Visible APIs: providerlib.metrics.clamp_percentage" in query
    assert task.test_context in query
