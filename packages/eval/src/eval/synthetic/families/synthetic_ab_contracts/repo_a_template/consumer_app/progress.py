from __future__ import annotations

from providerlib.metrics import clamp_percentage


def render_progress_badge(progress: float | int) -> str:
    value = clamp_percentage(progress)
    return f"{value}% complete"
