from __future__ import annotations

import pytest

from consumer_app.ratios import ratio_or_label


def test_ratio_or_label_respects_default_label() -> None:
    assert ratio_or_label(4, 2) == "2.00"
    assert ratio_or_label(4, 0, default="n/a") == "n/a"


# BEGIN GENERATED CONTRACT CASES
@pytest.mark.parametrize(
    ('numerator', 'denominator', 'default', 'expected'),
    [
        pytest.param(1, 0, 'zero', 'zero', id='preserves-zero-fallback-labels'),
pytest.param(9, 0, 'missing', 'missing', id='preserves-missing-fallback-labels'),
pytest.param(5, 0, 'unavailable', 'unavailable', id='preserves-unavailable-fallback-labels'),
pytest.param(3, 0, 'no ratio', 'no ratio', id='preserves-no-ratio-fallback-labels'),
pytest.param(7, 0, '--', '--', id='preserves-dash-fallback-labels'),
pytest.param(12, 0, 'empty', 'empty', id='preserves-empty-fallback-labels'),
pytest.param(100, 0, 'unknown', 'unknown', id='preserves-unknown-fallback-labels'),
pytest.param(2, 0, 'undefined', 'undefined', id='preserves-undefined-fallback-labels'),
pytest.param(42, 0, 'n/a*', 'n/a*', id='preserves-custom-symbolic-fallback-labels'),
    ],
)
def test_ratio_or_label_contract_cases(numerator, denominator, default, expected) -> None:
    assert ratio_or_label(numerator, denominator, default=default) == expected
# END GENERATED CONTRACT CASES
