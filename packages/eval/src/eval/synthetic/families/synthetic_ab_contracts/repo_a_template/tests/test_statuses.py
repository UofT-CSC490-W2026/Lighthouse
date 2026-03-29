from __future__ import annotations

from consumer_app.statuses import badge_color


def test_badge_color_uses_provider_mapping() -> None:
    assert badge_color("Queued") == "slate"
    assert badge_color("FAILED") == "red"
    assert badge_color("unknown") == "gray"
