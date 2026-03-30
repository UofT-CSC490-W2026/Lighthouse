from __future__ import annotations

import pytest

from consumer_app.progress import render_progress_badge


def test_render_progress_badge_uses_whole_percentages() -> None:
    assert render_progress_badge(42.4) == "42% complete"
    assert render_progress_badge(111) == "100% complete"


# BEGIN GENERATED CONTRACT CASES
@pytest.mark.parametrize(
    ('progress', 'expected'),
    [
        pytest.param(-5, '0% complete', id='clamps-negative-values-to-zero'),
pytest.param(250, '100% complete', id='clamps-large-values-to-hundred'),
pytest.param(42.6, '43% complete', id='rounds-up-fractional-progress'),
pytest.param(0.4, '0% complete', id='rounds-down-small-fractions'),
pytest.param(0.6, '1% complete', id='rounds-up-small-fractions'),
pytest.param(0, '0% complete', id='preserves-zero-progress'),
pytest.param(7, '7% complete', id='keeps-integer-progress-values'),
pytest.param(100, '100% complete', id='handles-exact-hundred'),
pytest.param(15.2, '15% complete', id='rounds-teen-fractions'),
    ],
)
def test_render_progress_badge_contract_cases(progress, expected) -> None:
    assert render_progress_badge(progress) == expected
# END GENERATED CONTRACT CASES
