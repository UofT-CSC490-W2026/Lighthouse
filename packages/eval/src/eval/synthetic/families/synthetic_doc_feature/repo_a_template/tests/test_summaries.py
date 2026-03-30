from __future__ import annotations

from consumer_app.summaries import total_summary, filtered_summary

CSV_DATA = "name,dept,salary\nAlice,eng,100\nBob,eng,120\nCarol,sales,90\nDave,sales,110\nEve,eng,130"


def test_total_summary():
    result = total_summary(CSV_DATA, "salary", "All Salaries")
    assert result == "All Salaries: total=550.0, count=5, avg=110.0"


def test_total_summary_empty_csv():
    result = total_summary("name,dept,salary\n", "salary", "Empty")
    assert result == "Empty: total=0.0, count=0, avg=N/A"


def test_filtered_summary_eng():
    result = filtered_summary(CSV_DATA, "dept", "eng", "salary", "Eng Salaries")
    assert result == "Eng Salaries: total=350.0, count=3, avg=116.67"


def test_filtered_summary_sales():
    result = filtered_summary(CSV_DATA, "dept", "sales", "salary", "Sales Salaries")
    assert result == "Sales Salaries: total=200.0, count=2, avg=100.0"


def test_filtered_summary_no_match():
    result = filtered_summary(CSV_DATA, "dept", "hr", "salary", "HR Salaries")
    assert result == "HR Salaries: total=0.0, count=0, avg=N/A"


def test_filtered_summary_case_insensitive():
    result = filtered_summary(CSV_DATA, "dept", "ENG", "salary", "Eng Upper")
    assert result == "Eng Upper: total=350.0, count=3, avg=116.67"
