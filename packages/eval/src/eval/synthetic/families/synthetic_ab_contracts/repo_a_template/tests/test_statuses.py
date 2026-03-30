from __future__ import annotations

import pytest

from consumer_app.statuses import badge_color


def test_badge_color_uses_provider_mapping() -> None:
    assert badge_color("Queued") == "slate"
    assert badge_color("FAILED") == "red"
    assert badge_color("unknown") == "gray"


# BEGIN GENERATED CONTRACT CASES
@pytest.mark.parametrize(
    ('status', 'expected'),
    [
        pytest.param('queued', 'slate', id='maps-lowercase-queued-statuses'),
pytest.param('running', 'blue', id='maps-lowercase-running-statuses'),
pytest.param('succeeded', 'green', id='maps-lowercase-succeeded-statuses'),
pytest.param('Failed', 'red', id='maps-titlecase-failed-statuses'),
pytest.param('Queued', 'slate', id='normalizes-titlecase-queued-statuses'),
pytest.param('Running', 'blue', id='normalizes-titlecase-running-statuses'),
pytest.param('SUCCEEDED', 'green', id='normalizes-uppercase-succeeded-statuses'),
pytest.param(' unknown ', 'gray', id='returns-gray-for-unknown-statuses'),
pytest.param(' canceled ', 'gray', id='returns-gray-for-unmapped-statuses-after-trimming'),
    ],
)
def test_badge_color_contract_cases(status, expected) -> None:
    assert badge_color(status) == expected
# END GENERATED CONTRACT CASES
