from __future__ import annotations

from consumer_app.cache_keys import session_cache_key


def test_session_cache_key_uses_provider_key_format() -> None:
    assert session_cache_key(" Alice ") == "session:alice:v1"
