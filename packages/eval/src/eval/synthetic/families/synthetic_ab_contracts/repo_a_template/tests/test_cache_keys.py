from __future__ import annotations

import pytest

from consumer_app.cache_keys import session_cache_key


def test_session_cache_key_uses_provider_key_format() -> None:
    assert session_cache_key(" Alice ") == "session:alice:v1"


# BEGIN GENERATED CONTRACT CASES
@pytest.mark.parametrize(
    ('user_id', 'expected'),
    [
        pytest.param('Bob', 'session:bob:v1', id='lowercases-simple-identifiers'),
pytest.param('  CAROL', 'session:carol:v1', id='trims-and-lowercases-uppercase-identifiers'),
pytest.param(' dave ', 'session:dave:v1', id='trims-surrounding-whitespace-from-identifiers'),
pytest.param('Eve Adams', 'session:eve adams:v1', id='preserves-spaces-while-lowercasing-identifiers'),
pytest.param(' FRANK ', 'session:frank:v1', id='trims-uppercase-identifiers-before-versioning'),
pytest.param('Grace', 'session:grace:v1', id='appends-provider-version-for-simple-identifiers'),
pytest.param('Heidi', 'session:heidi:v1', id='appends-provider-version-for-mixed-case-identifiers'),
pytest.param(' IVAN\t', 'session:ivan:v1', id='trims-trailing-whitespace-before-versioning'),
pytest.param('Judy@example.com', 'session:judy@example.com:v1', id='preserves-email-style-identifiers-with-versioning'),
    ],
)
def test_session_cache_key_contract_cases(user_id, expected) -> None:
    assert session_cache_key(user_id) == expected
# END GENERATED CONTRACT CASES
