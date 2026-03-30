from __future__ import annotations


_STATUS_COLORS = {
    "queued": "slate",
    "running": "blue",
    "succeeded": "green",
    "failed": "red",
}


def status_to_color(status: str) -> str:
    """Map a status string to a stable badge color name."""
    normalized = status.strip().lower()
    return _STATUS_COLORS.get(normalized, "gray")
