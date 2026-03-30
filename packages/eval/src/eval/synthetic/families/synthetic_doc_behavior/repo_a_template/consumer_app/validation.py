from __future__ import annotations

from doclib.numbers import clamp_to_range, safe_divide


def compute_score_ratio(score: float, max_score: float) -> float:
    """Return score / max_score, defaulting to 0.0 when max_score is zero."""
    return safe_divide(score, max_score)


def bounded_progress(value: float) -> float:
    """Clamp a progress value to 0-100."""
    return clamp_to_range(value, 0.0, 100.0)
