from __future__ import annotations

from pathlib import Path

from shared.schemas.search import CodeSnippet, CombinedSnippet, SearchContextSource, WikiSnippet

from .workspace import FEATURE_TASK_TYPES, PreparedSyntheticTask, SyntheticTask


def build_synthetic_system_message(task_type: str = "") -> str:
    if task_type in FEATURE_TASK_TYPES:
        return (
            "You are an expert Python engineer implementing a feature from a test specification. "
            "Respond with ONLY a git unified diff patch that can be applied with `git apply`. "
            "Do not include markdown fences, commentary, or explanations. "
            "Use paths relative to the repository root."
        )
    return (
        "You are an expert Python engineer repairing a synthetic benchmark task. "
        "Respond with ONLY a git unified diff patch that can be applied with `git apply`. "
        "Do not include markdown fences, commentary, or explanations. "
        "Use paths relative to the repository root."
    )


def build_synthetic_baseline_user_message(prepared_task: PreparedSyntheticTask) -> str:
    task = prepared_task.task
    is_dual_repo = bool(task.repo_b_name)
    parts = _base_prompt_parts(task)
    parts.extend(_consumer_context_parts(prepared_task))
    if is_dual_repo:
        parts.extend(
            [
                "Available context:",
                "- The provider library is indexed separately but its source is not shown here.",
                "- Use only the task description, failing test context, and visible API names.",
                "",
            ]
        )
    else:
        parts.extend(
            [
                "Available context:",
                "- Use the task description, failing test context, and the source files shown above.",
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


def build_synthetic_ast_lighthouse_user_message(
    prepared_task: PreparedSyntheticTask,
    snippets: list[CodeSnippet],
) -> str:
    task = prepared_task.task
    parts = _base_prompt_parts(task)
    parts.extend(_consumer_context_parts(prepared_task))
    parts.extend(
        [
            "Retrieved provider-library AST-chunked code context from Lighthouse:",
        ]
    )

    if not snippets:
        parts.extend(
            [
                "- No provider-library AST snippets were retrieved for this task.",
                "",
            ]
        )
    else:
        for index, snippet in enumerate(snippets, start=1):
            parts.extend(
                [
                    f"AST snippet {index}:",
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


def build_synthetic_combined_lighthouse_user_message(
    prepared_task: PreparedSyntheticTask,
    snippets: list[CombinedSnippet],
) -> str:
    task = prepared_task.task
    parts = _base_prompt_parts(task)
    parts.extend(_consumer_context_parts(prepared_task))
    parts.extend(
        [
            "Retrieved fused provider-library context from Lighthouse:",
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
            elif snippet.context_source is SearchContextSource.ast:
                parts.extend(
                    [
                        f"Combined snippet {index} [ast]:",
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
    parts = [task.title, task.problem_statement]

    if task.visible_api_names:
        parts.append(f"Relevant APIs: {', '.join(task.visible_api_names)}")
    if task.test_context:
        parts.append(f"Failing test context: {task.test_context}")
    if task.expected_relevant_symbols:
        parts.append(f"Likely relevant symbols: {', '.join(task.expected_relevant_symbols)}")

    return "\n".join(parts).strip()


def _base_prompt_parts(task: SyntheticTask) -> list[str]:
    is_dual_repo = bool(task.repo_b_name)
    is_feature = task.task_type in FEATURE_TASK_TYPES

    pytest_targets = ", ".join(task.pytest_targets)
    edit_files = ", ".join(task.consumer_edit_files) if task.consumer_edit_files else "none"
    test_files = ", ".join(task.consumer_test_files) if task.consumer_test_files else "none"
    patch_example = task.consumer_edit_files[0] if task.consumer_edit_files else "src/module.py"

    if is_feature:
        heading = "Synthetic feature implementation task"
    else:
        heading = "Synthetic repair task"

    parts: list[str] = [
        heading,
        "",
        f"Task ID: {task.task_id}",
        f"Task type: {task.task_type}",
    ]

    if is_dual_repo:
        parts.extend([
            f"Consumer repository: {task.repo_a_name}",
            f"Indexed provider repository: {task.repo_b_name}",
        ])
    else:
        parts.append(f"Repository: {task.repo_a_name}")

    parts.extend([
        "",
        "Problem statement:",
        task.problem_statement.strip(),
        "",
    ])

    if task.visible_api_names:
        visible_api_names = ", ".join(task.visible_api_names)
        if is_dual_repo:
            parts.append(f"Visible provider APIs: {visible_api_names}")
        else:
            parts.append(f"Relevant APIs: {visible_api_names}")

    parts.extend([
        f"Source files to edit: {edit_files}",
        f"Test files: {test_files}",
        f"Failing pytest targets: {pytest_targets}",
    ])

    if task.test_context:
        parts.extend([
            "Failing test context:",
            task.test_context.strip(),
        ])

    parts.append("")

    constraints: list[str] = ["Constraints:"]
    if is_dual_repo:
        constraints.extend([
            "- Edit only the consumer repository.",
            "- Do not modify the provider library.",
        ])
    if is_feature:
        constraints.append("- Implement the feature so all failing tests pass.")
    else:
        constraints.append("- Keep the patch minimal and focused on the reported defect.")
    constraints.extend([
        "- Patch paths must be relative to the repository root.",
        f"- Use diff headers like `a/{patch_example}` and `b/{patch_example}`.",
        "",
    ])
    parts.extend(constraints)
    return parts


def _output_requirements() -> list[str]:
    return [
        "Output requirements:",
        "- Return ONLY a unified diff patch.",
        "- Use standard unified diff patch headers with `a/...` and `b/...` paths.",
        "- Do not include explanations.",
    ]


def _consumer_context_parts(prepared_task: PreparedSyntheticTask) -> list[str]:
    task = prepared_task.task
    is_dual_repo = bool(task.repo_b_name)
    is_feature = task.task_type in FEATURE_TASK_TYPES

    if is_feature:
        label = "Current repository context"
        description = "The following files are from the current repository state."
    elif is_dual_repo:
        label = "Current consumer repository context"
        description = "The following files are from the current buggy consumer repository state."
    else:
        label = "Current repository context"
        description = "The following files are from the current buggy repository state."

    parts = [
        f"{label}:",
        f"- {description}",
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
