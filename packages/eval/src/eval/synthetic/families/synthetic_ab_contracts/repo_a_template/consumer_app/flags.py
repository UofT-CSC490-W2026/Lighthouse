from __future__ import annotations

from providerlib.http import parse_feature_flag


def is_beta_enabled(raw: str | None) -> bool:
    return parse_feature_flag(raw)
