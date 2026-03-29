from __future__ import annotations

from consumer_app.ratios import ratio_or_label


def test_ratio_or_label_respects_default_label() -> None:
    assert ratio_or_label(4, 2) == "2.00"
    assert ratio_or_label(4, 0, default="n/a") == "n/a"
