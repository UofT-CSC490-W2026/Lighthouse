import pytest

from vectordb.client import MilvusClient


@pytest.mark.unit
def test_build_filter_expr_wraps_multiple_conditions_for_one_field():
    expr = MilvusClient._build_filter_expr(
        {"score": {"gte": 1, "lte": 3}, "branch": "main"}
    )

    assert expr == '(score >= 1 and score <= 3) and branch == "main"'
