from __future__ import annotations

from providerlib.metrics import seconds_to_timeout_ms


def client_timeout_ms(seconds: float | int | None) -> int:
    return seconds_to_timeout_ms(seconds)
