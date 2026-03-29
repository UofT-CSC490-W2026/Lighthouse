from __future__ import annotations

from consumer_app.usernames import canonical_username


def test_canonical_username_uses_provider_normalization() -> None:
    assert canonical_username("  Jane   DOE  ") == "jane doe"
