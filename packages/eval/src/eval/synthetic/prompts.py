from __future__ import annotations

from pathlib import Path

from shared.schemas.search import CodeSnippet, CombinedSnippet, SearchContextSource, WikiSnippet

from .workspace import PreparedSyntheticTask, SyntheticTask


def build_synthetic_system_message() -> str:
    return (
        "You are an expert Python engineer repairing a synthetic benchmark task. "
        "Edit only the consumer repository. Respond with ONLY a git unified diff "
        "patch that can be applied with `git apply`. Do not include markdown fences, "
        "commentary, or explanations. Use paths relative to the consumer repository root."
    )


def build_synthetic_baseline_user_message(prepared_task: PreparedSyntheticTask) -> str:
    parts = _base_prompt_parts(prepared_task.task)
    parts.extend(_consumer_context_parts(prepared_task))
    parts.extend(
        [
            "Available context:",
            "- The provider library is indexed separately but its source is not shown here.",
            "- Use only the task description, failing test context, and visible API names.",
            "",
        ]
    )
    parts.extend(_output_requirements())
    return "\n".join(parts)


def build_synthetic_code_lighthouse_user_message(
    prepared_task: PreparedSyntheticTask,
    snippets: list[CodeSnippet],
) -> str:
    task = prepared_task.task
    parts = _base_prompt_parts(task)
    parts.extend(_consumer_context_parts(prepared_task))
    parts.extend(
        [
            "Retrieved provider-library code context from Lighthouse:",
        ]
    )

    if not snippets:
        parts.extend(
            [
                "- No provider-library code snippets were retrieved for this task.",
                "",
            ]
        )
    else:
        for index, snippet in enumerate(snippets, start=1):
            parts.extend(
                [
                    f"Snippet {index}:",
                    f"- File: {snippet.file_path}",
                    f"- Lines: {snippet.start_line}-{snippet.end_line}",
                ]
            )
            if snippet.reason:
                parts.append(f"- Reason: {snippet.reason}")
            parts.extend(
                [
                    "",
                    snippet.content.rstrip(),
                    "",
                ]
            )

    parts.extend(_output_requirements())
    return "\n".join(parts)


def build_synthetic_wiki_lighthouse_user_message(
    prepared_task: PreparedSyntheticTask,
    snippets: list[WikiSnippet],
) -> str:
    task = prepared_task.task
    parts = _base_prompt_parts(task)
    parts.extend(_consumer_context_parts(prepared_task))
    parts.extend(
        [
            "Retrieved provider-library wiki context from Lighthouse:",
        ]
    )

    if not snippets:
        parts.extend(
            [
                "- No provider-library wiki snippets were retrieved for this task.",
                "",
            ]
        )
    else:
        for index, snippet in enumerate(snippets, start=1):
            parts.extend(
                [
                    f"Wiki snippet {index}:",
                    f"- Page: {snippet.page_title}",
                    f"- Slug: {snippet.slug}",
                    f"- Section path: {snippet.section_path}",
                    "",
                    snippet.content_snippet.rstrip(),
                    "",
                ]
            )

    parts.extend(_output_requirements())
    return "\n".join(parts)


def build_synthetic_combined_lighthouse_user_message(
    prepared_task: PreparedSyntheticTask,
    snippets: list[CombinedSnippet],
) -> str:
    task = prepared_task.task
    parts = _base_prompt_parts(task)
    parts.extend(_consumer_context_parts(prepared_task))
    parts.extend(
        [
            "Retrieved fused provider-library context from Lighthouse (code + wiki):",
        ]
    )

    if not snippets:
        parts.extend(
            [
                "- No provider-library snippets were retrieved for this task.",
                "",
            ]
        )
    else:
        for index, snippet in enumerate(snippets, start=1):
            if snippet.context_source is SearchContextSource.code:
                parts.extend(
                    [
                        f"Combined snippet {index} [code]:",
                        f"- File: {snippet.file_path or 'unknown'}",
                        f"- Lines: {snippet.start_line or 0}-{snippet.end_line or 0}",
                    ]
                )
                if snippet.reason:
                    parts.append(f"- Reason: {snippet.reason}")
            else:
                parts.extend(
                    [
                        f"Combined snippet {index} [wiki]:",
                        f"- Page: {snippet.page_title or 'unknown'}",
                        f"- Slug: {snippet.slug or 'unknown'}",
                        f"- Section path: {snippet.section_path or 'unknown'}",
                    ]
                )
            parts.extend(
                [
                    "",
                    snippet.content.rstrip(),
                    "",
                ]
            )

    parts.extend(_output_requirements())
    return "\n".join(parts)


def build_synthetic_search_query(task: SyntheticTask) -> str:
    api_names = ", ".join(task.visible_api_names) if task.visible_api_names else "none"
    relevant_symbols = (
        ", ".join(task.expected_relevant_symbols)
        if task.expected_relevant_symbols
        else "none"
    )
    return "\n".join(
        [
            task.title,
            task.problem_statement,
            f"Visible APIs: {api_names}",
            f"Failing test context: {task.test_context}",
            f"Likely provider symbols: {relevant_symbols}",
        ]
    ).strip()


def _base_prompt_parts(task: SyntheticTask) -> list[str]:
    visible_api_names = ", ".join(task.visible_api_names) if task.visible_api_names else "none"
    pytest_targets = ", ".join(task.pytest_targets)
    consumer_edit_files = ", ".join(task.consumer_edit_files) if task.consumer_edit_files else "none"
    consumer_test_files = ", ".join(task.consumer_test_files) if task.consumer_test_files else "none"
    patch_example = task.consumer_edit_files[0] if task.consumer_edit_files else "consumer_app/module.py"
    return [
        "Synthetic repair task",
        "",
        f"Task ID: {task.task_id}",
        f"Task type: {task.task_type}",
        f"Consumer repository: {task.repo_a_name}",
        f"Indexed provider repository: {task.repo_b_name}",
        "",
        "Problem statement:",
        task.problem_statement.strip(),
        "",
        f"Visible provider APIs: {visible_api_names}",
        f"Consumer source files to edit for this task: {consumer_edit_files}",
        f"Consumer test files for this task: {consumer_test_files}",
        f"Failing pytest targets: {pytest_targets}",
        "Failing test context:",
        task.test_context.strip(),
        "",
        "Constraints:",
        "- Edit only the consumer repository.",
        "- Do not modify the provider library.",
        "- Keep the patch minimal and focused on the reported contract mismatch.",
        "- Patch paths must be relative to the consumer repository root.",
        f"- Use diff headers like `a/{patch_example}` and `b/{patch_example}`.",
        "",
    ]


def _output_requirements() -> list[str]:
    return [
        "Output requirements:",
        "- Return ONLY a unified diff patch.",
        "- Use standard unified diff patch headers with `a/...` and `b/...` paths.",
        "- The patch must apply to the consumer repository only.",
        "- Do not include explanations.",
    ]


def _consumer_context_parts(prepared_task: PreparedSyntheticTask) -> list[str]:
    task = prepared_task.task
    parts = [
        "Current consumer repository context:",
        "- The following files are from the current buggy consumer repository state.",
        "",
    ]
    for relative_path in _consumer_context_files(task):
        file_path = prepared_task.repo_a_path / relative_path
        parts.extend(
            [
                f"File: {relative_path}",
                "",
                _read_context_file(file_path),
                "",
            ]
        )
    return parts


def _consumer_context_files(task: SyntheticTask) -> tuple[str, ...]:
    ordered: list[str] = []
    for relative_path in (*task.consumer_edit_files, *task.consumer_test_files):
        if relative_path not in ordered:
            ordered.append(relative_path)
    return tuple(ordered)


def _read_context_file(path: Path) -> str:
    return path.read_text(encoding="utf-8").rstrip()
