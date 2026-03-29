from __future__ import annotations

from consumer_app.timeouts import client_timeout_ms


def test_client_timeout_ms_uses_provider_units() -> None:
    assert client_timeout_ms(1.5) == 1500
    assert client_timeout_ms(None) == 0
