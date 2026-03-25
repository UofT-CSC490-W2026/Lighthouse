import pytest

from vectordb.client import MilvusClient


def test_build_filter_expr_with_implicit_equality() -> None:
    expr = MilvusClient._build_filter_expr(
        {"repository_id": "repo-1", "branch": 'feature/"quoted"'}
    )

    assert expr == 'repository_id == "repo-1" and branch == "feature/\\"quoted\\""'


def test_build_filter_expr_with_multiple_operators() -> None:
    expr = MilvusClient._build_filter_expr(
        {
            "repository_id": {"in": ["repo-1", "repo-2"]},
            "score": {"gte": 0.5, "lt": 0.9},
            "branch": {"like": "release/%"},
        }
    )

    assert (
        expr == 'repository_id in ["repo-1", "repo-2"] and '
        '(score >= 0.5 and score < 0.9) and '
        'branch like "release/%"'
    )


def test_build_filter_expr_with_bool_and_numeric_values() -> None:
    expr = MilvusClient._build_filter_expr(
        {"is_public": True, "rank": {"==": 3}}
    )

    assert expr == "is_public == true and rank == 3"


def test_build_filter_expr_rejects_invalid_in_value() -> None:
    with pytest.raises(TypeError, match="expects a sequence"):
        MilvusClient._build_filter_expr({"repository_id": {"in": "repo-1"}})


def test_build_filter_expr_rejects_unsupported_operator() -> None:
    with pytest.raises(ValueError, match="Unsupported filter operator"):
        MilvusClient._build_filter_expr({"repository_id": {"contains": "repo"}})
