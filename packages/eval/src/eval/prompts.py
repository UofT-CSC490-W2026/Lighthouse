from __future__ import annotations

from shared.schemas.search import CodeSnippet, WikiSnippet

from eval.slice import SWEBenchTask


def build_baseline_system_message() -> str:
    return (
        "You are an expert software engineer working on a SWE-bench bug-fix task. "
        "Respond with ONLY a git unified diff patch that can be applied with "
        "`git apply`. Do not include markdown fences, commentary, or explanations."
    )


def build_baseline_user_message(task: SWEBenchTask) -> str:
    parts = [
        "SWE-bench task",
        "",
        f"Instance ID: {task.instance_id}",
        f"Repository: {task.repo}",
        f"Base commit: {task.base_commit}",
        f"Version: {task.version}",
        "",
        "Problem statement:",
        task.problem_statement.strip(),
        "",
        "Output requirements:",
        "- Return ONLY a unified diff patch.",
        "- Use standard unified diff patch headers with `a/...` and `b/...` paths.",
        "- Keep the patch minimal and focused on fixing the bug.",
        "- Do not include any explanations.",
    ]
    return "\n".join(parts)


def build_lighthouse_user_message(
    task: SWEBenchTask,
    snippets: list[CodeSnippet],
) -> str:
    parts = [
        "SWE-bench task",
        "",
        f"Instance ID: {task.instance_id}",
        f"Repository: {task.repo}",
        f"Base commit: {task.base_commit}",
        f"Version: {task.version}",
        "",
        "Problem statement:",
        task.problem_statement.strip(),
        "",
        "Retrieved code context from Lighthouse:",
    ]

    if not snippets:
        parts.extend(
            [
                "- No code snippets were retrieved for this task.",
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

    parts.extend(
        [
            "Output requirements:",
            "- Return ONLY a unified diff patch.",
            "- Use standard unified diff patch headers with `a/...` and `b/...` paths.",
            "- Use the retrieved code context when it is helpful, but do not assume it is complete.",
            "- Keep the patch minimal and focused on fixing the bug.",
            "- Do not include any explanations.",
        ]
    )
    return "\n".join(parts)


def build_wiki_lighthouse_user_message(
    task: SWEBenchTask,
    snippets: list[WikiSnippet],
) -> str:
    parts = [
        "SWE-bench task",
        "",
        f"Instance ID: {task.instance_id}",
        f"Repository: {task.repo}",
        f"Base commit: {task.base_commit}",
        f"Version: {task.version}",
        "",
        "Problem statement:",
        task.problem_statement.strip(),
        "",
        "Retrieved repository wiki context from Lighthouse:",
    ]

    if not snippets:
        parts.extend(
            [
                "- No wiki snippets were retrieved for this task.",
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

    parts.extend(
        [
            "Output requirements:",
            "- Return ONLY a unified diff patch.",
            "- Use standard unified diff patch headers with `a/...` and `b/...` paths.",
            "- Use the retrieved wiki context when it is helpful, but do not assume it is complete.",
            "- Keep the patch minimal and focused on fixing the bug.",
            "- Do not include any explanations.",
        ]
    )
    return "\n".join(parts)
