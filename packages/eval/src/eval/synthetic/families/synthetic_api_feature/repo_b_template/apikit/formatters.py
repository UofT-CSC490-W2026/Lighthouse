from __future__ import annotations


def format_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    parts: list[str] = []
    if h:
        parts.append(f"{h}h")
    if h or m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def format_file_size(bytes_count: int) -> str:
    if bytes_count < 1024:
        return f"{bytes_count} B"
    value = bytes_count / 1024
    if value < 1024:
        return f"{value:.1f} KB"
    value /= 1024
    if value < 1024:
        return f"{value:.1f} MB"
    value /= 1024
    return f"{value:.1f} GB"


def pluralize(word: str, count: int) -> str:
    return word if count == 1 else word + "s"
