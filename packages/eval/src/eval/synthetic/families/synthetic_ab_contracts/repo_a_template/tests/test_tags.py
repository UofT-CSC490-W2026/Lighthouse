from __future__ import annotations

import pytest

from consumer_app.tags import normalized_tag_line


def test_normalized_tag_line_preserves_provider_order() -> None:
    tags = ["Zeta Users", "Alpha Squad", "zeta users"]
    assert normalized_tag_line(tags) == "zeta-users, alpha-squad"


# BEGIN GENERATED CONTRACT CASES
@pytest.mark.parametrize(
    ('tags', 'expected'),
    [
        pytest.param(['Beta Team', 'Alpha Team'], 'beta-team, alpha-team', id='preserves-beta-before-alpha-order'),
pytest.param(['Gamma', 'Beta', 'Alpha'], 'gamma, beta, alpha', id='preserves-input-order-across-three-tags'),
pytest.param(['Ops', 'Alpha', 'ops', 'beta'], 'ops, alpha, beta', id='keeps-first-seen-order-when-duplicates-appear'),
pytest.param(['Zulu', 'Echo', 'Delta'], 'zulu, echo, delta', id='preserves-zulu-echo-delta-order'),
pytest.param(['Two Words', 'One Word', 'two words'], 'two-words, one-word', id='preserves-first-seen-multiword-order'),
pytest.param(['Kappa', 'alpha', 'Beta'], 'kappa, alpha, beta', id='preserves-provider-order-for-mixed-case-tags'),
pytest.param(['Late', 'Early', 'Middle'], 'late, early, middle', id='preserves-late-early-middle-order'),
pytest.param(['Zed', 'Able', 'zed', 'Baker'], 'zed, able, baker', id='keeps-duplicates-collapsed-without-resorting'),
pytest.param(['Road Runner', 'Acme Corp', 'road runner'], 'road-runner, acme-corp', id='preserves-multiword-provider-order'),
    ],
)
def test_normalized_tag_line_contract_cases(tags, expected) -> None:
    assert normalized_tag_line(tags) == expected
# END GENERATED CONTRACT CASES
