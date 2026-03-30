from __future__ import annotations

from consumer_app.exports import grouped_totals, grouped_summaries

CSV_DATA = "name,dept,salary\nAlice,eng,100\nBob,eng,120\nCarol,sales,90\nDave,sales,110\nEve,eng,130"


def test_grouped_totals_by_dept():
    result = grouped_totals(CSV_DATA, "dept", "salary")
    assert result == "Group Totals:\n  eng: 350.0\n  sales: 200.0"


def test_grouped_totals_empty_csv():
    result = grouped_totals("name,dept,salary\n", "dept", "salary")
    assert result == "Group Totals: (empty)"


def test_grouped_summaries_by_dept():
    result = grouped_summaries(CSV_DATA, "dept", "salary")
    expected = "eng: total=350.0, count=3, avg=116.67\nsales: total=200.0, count=2, avg=100.0"
    assert result == expected


def test_grouped_summaries_empty_csv():
    result = grouped_summaries("name,dept,salary\n", "dept", "salary")
    assert result == ""


def test_grouped_totals_by_name():
    result = grouped_totals(CSV_DATA, "name", "salary")
    assert "Alice: 100.0" in result
    assert "Bob: 120.0" in result
    assert "Eve: 130.0" in result


def test_grouped_summaries_single_group():
    csv = "name,dept,salary\nAlice,eng,100\nBob,eng,120"
    result = grouped_summaries(csv, "dept", "salary")
    assert result == "eng: total=220.0, count=2, avg=110.0"
