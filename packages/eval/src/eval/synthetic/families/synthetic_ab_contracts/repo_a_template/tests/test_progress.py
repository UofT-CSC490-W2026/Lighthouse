from __future__ import annotations

from consumer_app.progress import render_progress_badge


def test_render_progress_badge_uses_whole_percentages() -> None:
    assert render_progress_badge(42.4) == "42% complete"
    assert render_progress_badge(111) == "100% complete"
