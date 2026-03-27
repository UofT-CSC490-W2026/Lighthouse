from __future__ import annotations

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
