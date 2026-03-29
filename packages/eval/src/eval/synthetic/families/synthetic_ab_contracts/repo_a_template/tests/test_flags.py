from __future__ import annotations

import pytest

from consumer_app.flags import is_beta_enabled


def test_is_beta_enabled_uses_feature_flag_parser() -> None:
    assert is_beta_enabled("on") is True
    assert is_beta_enabled("off") is False
    assert is_beta_enabled(None) is False


# BEGIN GENERATED CONTRACT CASES
@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        pytest.param('OFF', False, id='parses-uppercase-off-values'),
pytest.param('false', False, id='parses-false-literals-as-disabled'),
pytest.param('disabled', False, id='parses-disabled-literals-as-disabled'),
pytest.param('no', False, id='parses-no-literals-as-disabled'),
pytest.param('0', False, id='parses-zero-literals-as-disabled'),
pytest.param('  off  ', False, id='trims-off-values-before-parsing'),
    ],
)
def test_is_beta_enabled_false_contract_cases(raw, expected) -> None:
    assert is_beta_enabled(raw) is expected

@pytest.mark.parametrize(
    'raw',
    [
        pytest.param('maybe', id='rejects-unknown-flag-words'),
pytest.param('   ', id='rejects-blank-flag-values'),
pytest.param('of', id='rejects-partial-flag-tokens'),
    ],
)
def test_is_beta_enabled_invalid_contract_cases(raw) -> None:
    with pytest.raises(ValueError):
        is_beta_enabled(raw)
# END GENERATED CONTRACT CASES
