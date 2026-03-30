from __future__ import annotations

from providerlib.cache import build_cache_key


def session_cache_key(user_id: str) -> str:
    return build_cache_key("session", user_id)
