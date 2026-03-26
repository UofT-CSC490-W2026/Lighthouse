import pytest

from vectordb.client import MilvusClient


# ── _build_filter_expr ────────────────────────────────────────────


@pytest.mark.unit
def test_empty_filters():
    assert MilvusClient._build_filter_expr(None) == ""


@pytest.mark.unit
def test_empty_dict():
    assert MilvusClient._build_filter_expr({}) == ""


@pytest.mark.unit
def test_simple_equality():
    assert MilvusClient._build_filter_expr({"repo": "abc"}) == 'repo == "abc"'


@pytest.mark.unit
def test_operator_gt():
    assert MilvusClient._build_filter_expr({"score": {"gt": 0.5}}) == "score > 0.5"


@pytest.mark.unit
def test_operator_lt():
    assert MilvusClient._build_filter_expr({"score": {"lt": 0.5}}) == "score < 0.5"


@pytest.mark.unit
def test_operator_gte():
    assert MilvusClient._build_filter_expr({"score": {"gte": 5}}) == "score >= 5"


@pytest.mark.unit
def test_operator_lte():
    assert MilvusClient._build_filter_expr({"score": {"lte": 5}}) == "score <= 5"


@pytest.mark.unit
def test_operator_eq():
    assert MilvusClient._build_filter_expr({"score": {"eq": 5}}) == "score == 5"


@pytest.mark.unit
def test_operator_ne():
    assert MilvusClient._build_filter_expr({"score": {"ne": 5}}) == "score != 5"


@pytest.mark.unit
def test_in_operator():
    result = MilvusClient._build_filter_expr({"id": {"in": ["a", "b"]}})
    assert result == 'id in ["a", "b"]'


@pytest.mark.unit
def test_in_non_sequence_raises():
    with pytest.raises(TypeError):
        MilvusClient._build_filter_expr({"id": {"in": "abc"}})


@pytest.mark.unit
def test_multiple_conditions_and():
    result = MilvusClient._build_filter_expr({"repo": "abc", "branch": "main"})
    assert result == 'repo == "abc" and branch == "main"'


@pytest.mark.unit
def test_unsupported_operator_raises():
    with pytest.raises(ValueError):
        MilvusClient._build_filter_expr({"x": {"badop": 1}})


# ── _format_filter_value ─────────────────────────────────────────


@pytest.mark.unit
def test_format_value_bool():
    assert MilvusClient._format_filter_value(True) == "true"


@pytest.mark.unit
def test_format_value_int():
    assert MilvusClient._format_filter_value(42) == "42"


@pytest.mark.unit
def test_format_value_float():
    assert MilvusClient._format_filter_value(0.5) == "0.5"


@pytest.mark.unit
def test_format_value_string_escapes():
    assert MilvusClient._format_filter_value('he"llo') == '"he\\"llo"'


@pytest.mark.unit
def test_format_value_unsupported_type():
    with pytest.raises(TypeError):
        MilvusClient._format_filter_value([1, 2])
