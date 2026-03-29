from __future__ import annotations

from consumer_app.flags import is_beta_enabled


def test_is_beta_enabled_uses_feature_flag_parser() -> None:
    assert is_beta_enabled("on") is True
    assert is_beta_enabled("off") is False
    assert is_beta_enabled(None) is False
