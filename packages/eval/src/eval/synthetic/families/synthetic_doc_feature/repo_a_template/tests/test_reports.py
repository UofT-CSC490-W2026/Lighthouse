from __future__ import annotations

from consumer_app.reports import category_report, filtered_category_report

CSV_DATA = "name,dept,salary\nAlice,eng,100\nBob,eng,120\nCarol,sales,90\nDave,sales,110\nEve,eng,130"


def test_category_report_by_dept():
    result = category_report(CSV_DATA, "dept")
    assert result == "Category Report:\n  eng: 3\n  sales: 2"


def test_category_report_by_name():
    result = category_report(CSV_DATA, "name")
    assert result == (
        "Category Report:\n  Alice: 1\n  Bob: 1\n  Carol: 1\n  Dave: 1\n  Eve: 1"
    )


def test_category_report_empty_csv():
    result = category_report("name,dept,salary\n", "dept")
    assert result == "Category Report: (empty)"


def test_filtered_category_report_eng_names():
    result = filtered_category_report(CSV_DATA, "dept", "eng", "name")
    assert result == "Filtered Report:\n  Alice: 1\n  Bob: 1\n  Eve: 1"


def test_filtered_category_report_sales_names():
    result = filtered_category_report(CSV_DATA, "dept", "sales", "name")
    assert result == "Filtered Report:\n  Carol: 1\n  Dave: 1"


def test_filtered_category_report_no_match():
    result = filtered_category_report(CSV_DATA, "dept", "hr", "name")
    assert result == "Filtered Report: (empty)"


def test_filtered_category_report_case_insensitive():
    result = filtered_category_report(CSV_DATA, "dept", "ENG", "name")
    assert result == "Filtered Report:\n  Alice: 1\n  Bob: 1\n  Eve: 1"
