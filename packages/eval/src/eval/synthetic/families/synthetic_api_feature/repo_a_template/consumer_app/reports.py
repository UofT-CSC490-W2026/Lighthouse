from __future__ import annotations

from apikit.formatters import format_duration, format_file_size, pluralize
from apikit.transforms import unique_sorted


def task_summary(task_name: str, seconds: int) -> str:
    return f"{task_name}: {format_duration(seconds)}"


def storage_report(files: list[tuple[str, int]]) -> list[str]:
    return [f"{name}: {format_file_size(size)}" for name, size in files]


def tag_line(tags: list[str]) -> str:
    unique = unique_sorted(tags)
    count = len(unique)
    return f"{count} {pluralize('tag', count)}: {', '.join(unique)}"
