from __future__ import annotations

from consumer_app.retries import describe_retry_delay


def test_describe_retry_delay_uses_provider_defaults() -> None:
    assert describe_retry_delay(None) == "retry in 1 second"
    assert describe_retry_delay("   ") == "retry in 1 second"
    assert describe_retry_delay("3") == "retry in 3 seconds"
