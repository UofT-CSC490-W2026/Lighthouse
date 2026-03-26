"""Prompt construction and response parsing for code generation."""

from __future__ import annotations

import re

from lighthouse_eval.candidates.base import (
    CandidateEdit,
    Completion,
    FileRewrite,
    MultiFileRewrite,
    UnifiedPatch,
)
from lighthouse_eval.context.base import ContextSnippet
from lighthouse_eval.datasets.schema import OutputFormat, Task

_FORMAT_INSTRUCTIONS: dict[OutputFormat, str] = {
    OutputFormat.file: (
        "Respond with ONLY the complete file content.  "
        "Do not include markdown fences, commentary, or explanations."
    ),
    OutputFormat.multi_file: (
        "Respond with one or more files.  For EACH file use the exact format:\n"
        "===== path/to/file.py =====\n<file content>\n\n"
        "Do not include markdown fences or explanations."
    ),
    OutputFormat.patch: (
        "Respond with ONLY a unified diff (patch) that can be applied with "
        "`git apply`.  Do not include commentary or markdown fences."
    ),
    OutputFormat.completion: (
        "Respond with ONLY the code that should be appended at the cursor "
        "position.  Do not repeat existing code, add markdown fences, or "
        "explanations."
    ),
}


def _format_context_block(snippets: list[ContextSnippet]) -> str:
    if not snippets:
        return ""
    parts: list[str] = ["", "### Retrieved context", ""]
    for i, s in enumerate(snippets, 1):
        header = f"--- snippet {i}: {s.file_path}"
        if s.start_line is not None:
            header += f" (L{s.start_line}"
            if s.end_line is not None:
                header += f"-L{s.end_line}"
            header += ")"
        header += " ---"
        parts.append(header)
        parts.append(s.content)
        parts.append("")
    return "\n".join(parts)


def build_system_message(task: Task) -> str:
    """Return the system message for the LLM call."""
    return (
        "You are an expert software engineer.  "
        "Follow the user's instructions precisely and produce ONLY the "
        "requested output with no extra commentary."
    )


def build_user_message(
    task: Task, context: list[ContextSnippet] | None = None
) -> str:
    """Assemble the user prompt from the task and optional context."""
    parts: list[str] = []

    parts.append(f"### Task\n\n{task.description}")

    if task.target_files:
        files_str = ", ".join(f"`{f}`" for f in task.target_files)
        parts.append(f"\n### Target file(s): {files_str}")

    parts.append("\nLanguage: Python")

    if context:
        parts.append(_format_context_block(context))

    fmt_instruction = _FORMAT_INSTRUCTIONS.get(task.output_format, "")
    if fmt_instruction:
        parts.append(f"\n### Output format\n\n{fmt_instruction}")

    return "\n".join(parts)


_FENCE_RE = re.compile(r"^```[\w]*\n?", re.MULTILINE)
_FENCE_CLOSE_RE = re.compile(r"\n?```\s*$", re.MULTILINE)
_MULTI_FILE_RE = re.compile(r"=====\s*(.+?)\s*=====")


def _strip_markdown_fences(text: str) -> str:
    text = _FENCE_RE.sub("", text)
    text = _FENCE_CLOSE_RE.sub("", text)
    return text.strip()


def _parse_multi_file(text: str) -> dict[str, str]:
    """Parse the ``===== path =====`` multi-file format."""
    parts = _MULTI_FILE_RE.split(text)
    if len(parts) < 3:
        return {}
    files: dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        path = parts[i].strip()
        content = parts[i + 1].strip() + "\n"
        files[path] = content
    return files


def parse_response(raw: str, task: Task) -> CandidateEdit:
    """Convert raw LLM text into the CandidateEdit variant expected by the task."""
    text = _strip_markdown_fences(raw)

    if task.output_format == OutputFormat.completion:
        return Completion(text=text)

    if task.output_format == OutputFormat.patch:
        return UnifiedPatch(diff=text)

    if task.output_format == OutputFormat.multi_file:
        files = _parse_multi_file(text)
        if not files and task.target_files:
            return MultiFileRewrite(files={task.target_files[0]: text})
        return MultiFileRewrite(files=files)

    filename = task.target_files[0] if task.target_files else "solution.py"
    return FileRewrite(filename=filename, content=text)
