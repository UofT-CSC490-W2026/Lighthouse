from __future__ import annotations

import pytest

from consumer_app.emails import primary_contact


def test_primary_contact_uses_provider_email_cleanup() -> None:
    emails = ["  TEAM@Example.com  ", "backup@example.com"]
    assert primary_contact(emails) == "team@example.com"


# BEGIN GENERATED CONTRACT CASES
@pytest.mark.parametrize(
    ('emails', 'expected'),
    [
        pytest.param(['', 'support@example.com'], 'support@example.com', id='skips-empty-first-emails'),
pytest.param(['   ', 'ops@example.com'], 'ops@example.com', id='skips-whitespace-only-first-emails'),
pytest.param(['ADMIN@Example.com', 'backup@example.com'], 'admin@example.com', id='lowercases-uppercase-primary-emails'),
pytest.param(['  MIXED@Example.com  ', 'backup@example.com'], 'mixed@example.com', id='trims-surrounding-spaces-on-primary-emails'),
pytest.param(['', '  TEAM@EXAMPLE.COM '], 'team@example.com', id='skips-blank-values-before-valid-emails'),
pytest.param(['\t', 'Second@Example.com'], 'second@example.com', id='skips-tab-only-values-before-valid-emails'),
pytest.param(['First@Example.com', 'backup@example.com'], 'first@example.com', id='lowercases-first-valid-mixed-case-emails'),
pytest.param(['  first@example.com  ', 'backup@example.com'], 'first@example.com', id='trims-first-valid-lowercase-emails'),
pytest.param(['', '', 'third@example.com'], 'third@example.com', id='skips-multiple-blank-values-before-valid-emails'),
    ],
)
def test_primary_contact_contract_cases(emails, expected) -> None:
    assert primary_contact(emails) == expected
# END GENERATED CONTRACT CASES
