from __future__ import annotations

import pytest

from consumer_app.usernames import canonical_username


def test_canonical_username_uses_provider_normalization() -> None:
    assert canonical_username("  Jane   DOE  ") == "jane doe"


# BEGIN GENERATED CONTRACT CASES
@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        pytest.param('Mary   Jane', 'mary jane', id='collapses-double-spaces-in-usernames'),
pytest.param('  ONE   TWO  ', 'one two', id='collapses-leading-and-internal-spaces'),
pytest.param('\tTabbed\tUser\t', 'tabbed user', id='collapses-tabs-in-usernames'),
pytest.param('Line\nBreak', 'line break', id='collapses-newlines-in-usernames'),
pytest.param('Mix\t of\nWhitespace', 'mix of whitespace', id='collapses-mixed-whitespace'),
pytest.param('Double   middle', 'double middle', id='preserves-single-space-separators'),
pytest.param('Already   lower   case', 'already lower case', id='normalizes-multiword-usernames'),
pytest.param('  spaced    out   user ', 'spaced out user', id='strips-and-collapses-surrounding-whitespace'),
pytest.param('One   Two   Three   Four', 'one two three four', id='collapses-four-word-usernames'),
    ],
)
def test_canonical_username_contract_cases(raw, expected) -> None:
    assert canonical_username(raw) == expected
# END GENERATED CONTRACT CASES
