from __future__ import annotations

import pytest

from consumer_app.timeouts import client_timeout_ms


def test_client_timeout_ms_uses_provider_units() -> None:
    assert client_timeout_ms(1.5) == 1500
    assert client_timeout_ms(None) == 0


# BEGIN GENERATED CONTRACT CASES
@pytest.mark.parametrize(
    ('seconds', 'expected'),
    [
        pytest.param(1, 1000, id='converts-one-second-values-to-milliseconds'),
pytest.param(0.5, 500, id='converts-half-second-values-to-milliseconds'),
pytest.param(2.25, 2250, id='converts-fractional-seconds-with-rounding'),
pytest.param(10, 10000, id='converts-ten-second-values-to-milliseconds'),
pytest.param(0.001, 1, id='converts-millisecond-scale-fractions-correctly'),
pytest.param(3.333, 3333, id='converts-repeating-fractions-to-milliseconds'),
pytest.param(2.6, 2600, id='converts-decimal-seconds-with-rounding'),
pytest.param(0.25, 250, id='converts-quarter-second-values-to-milliseconds'),
pytest.param(7.75, 7750, id='converts-large-fractional-values-to-milliseconds'),
    ],
)
def test_client_timeout_ms_contract_cases(seconds, expected) -> None:
    assert client_timeout_ms(seconds) == expected
# END GENERATED CONTRACT CASES
