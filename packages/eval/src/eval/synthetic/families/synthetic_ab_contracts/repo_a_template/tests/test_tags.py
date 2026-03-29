from __future__ import annotations

from consumer_app.tags import normalized_tag_line


def test_normalized_tag_line_preserves_provider_order() -> None:
    tags = ["Zeta Users", "Alpha Squad", "zeta users"]
    assert normalized_tag_line(tags) == "zeta-users, alpha-squad"
