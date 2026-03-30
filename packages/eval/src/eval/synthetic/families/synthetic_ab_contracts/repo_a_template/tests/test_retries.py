from __future__ import annotations

import pytest

from consumer_app.retries import describe_retry_delay


def test_describe_retry_delay_uses_provider_defaults() -> None:
    assert describe_retry_delay(None) == "retry in 1 second"
    assert describe_retry_delay("   ") == "retry in 1 second"
    assert describe_retry_delay("3") == "retry in 3 seconds"


# BEGIN GENERATED CONTRACT CASES
@pytest.mark.parametrize(
    ('header', 'expected'),
    [
        pytest.param('', 'retry in 1 second', id='defaults-empty-headers-to-one-second'),
pytest.param('   ', 'retry in 1 second', id='defaults-blank-headers-to-one-second'),
pytest.param('\t', 'retry in 1 second', id='defaults-tab-headers-to-one-second'),
pytest.param('\n', 'retry in 1 second', id='defaults-newline-headers-to-one-second'),
pytest.param('0', 'retry in 1 second', id='clamps-zero-retry-values-to-one-second'),
pytest.param('+0', 'retry in 1 second', id='clamps-signed-zero-retry-values-to-one-second'),
pytest.param('-3', 'retry in 1 second', id='clamps-negative-retry-values-to-one-second'),
pytest.param(' 0 ', 'retry in 1 second', id='clamps-zero-with-whitespace-to-one-second'),
pytest.param(' -9 ', 'retry in 1 second', id='clamps-negative-with-whitespace-to-one-second'),
    ],
)
def test_describe_retry_delay_contract_cases(header, expected) -> None:
    assert describe_retry_delay(header) == expected
# END GENERATED CONTRACT CASES
