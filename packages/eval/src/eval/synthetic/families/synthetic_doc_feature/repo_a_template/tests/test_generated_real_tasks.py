from __future__ import annotations

from consumer_app.exports import grouped_summaries, grouped_totals
from consumer_app.reports import category_report, filtered_category_report
from consumer_app.summaries import filtered_summary, total_summary

CSV_DATA = 'name,dept,salary\nAlice,eng,100\nBob,eng,120\nCarol,sales,90\nDave,sales,110\nEve,eng,130'
CSV_UNSORTED = 'name,dept,salary\nCarol,sales,90\nAlice,eng,100\nBob,eng,120\nDave,sales,110\nEve,eng,130'


def test_task_011_category_report_respects_field() -> None:
    assert category_report(CSV_DATA, "dept") == "Category Report:\n  eng: 3\n  sales: 2"

def test_task_012_category_report_title() -> None:
    assert category_report(CSV_DATA, 'dept').startswith('Category Report:')

def test_task_013_filtered_report_applies_filter() -> None:
    assert (
        filtered_category_report(CSV_DATA, "dept", "sales", "name")
        == "Filtered Report:\n  Carol: 1\n  Dave: 1"
    )

def test_task_014_filtered_report_filter_arg_order() -> None:
    assert (
        filtered_category_report(CSV_DATA, "dept", "eng", "name")
        == "Filtered Report:\n  Alice: 1\n  Bob: 1\n  Eve: 1"
    )

def test_task_015_filtered_report_title() -> None:
    assert filtered_category_report(CSV_DATA, 'dept', 'eng', 'name').startswith('Filtered Report:')

def test_task_016_total_summary_value_field() -> None:
    assert total_summary(CSV_DATA, 'salary', 'All Salaries') == 'All Salaries: total=550.0, count=5, avg=110.0'

def test_task_017_total_summary_count() -> None:
    assert total_summary(CSV_DATA, 'salary', 'All Salaries') == 'All Salaries: total=550.0, count=5, avg=110.0'

def test_task_018_filtered_summary_filters() -> None:
    assert filtered_summary(CSV_DATA, 'dept', 'sales', 'salary', 'Sales Salaries') == 'Sales Salaries: total=200.0, count=2, avg=100.0'

def test_task_019_filtered_summary_count() -> None:
    assert filtered_summary(CSV_DATA, 'dept', 'eng', 'salary', 'Eng Salaries') == 'Eng Salaries: total=350.0, count=3, avg=116.67'

def test_task_020_filtered_summary_label() -> None:
    assert filtered_summary(CSV_DATA, 'dept', 'eng', 'salary', 'Eng Salaries').startswith('Eng Salaries:')

def test_task_021_grouped_totals_per_group() -> None:
    assert grouped_totals(CSV_DATA, "dept", "salary") == "Group Totals:\n  eng: 350.0\n  sales: 200.0"

def test_task_022_grouped_totals_title() -> None:
    assert grouped_totals(CSV_DATA, 'dept', 'salary').startswith('Group Totals:')

def test_task_023_grouped_totals_group_field() -> None:
    assert 'eng: 350.0' in grouped_totals(CSV_DATA, 'dept', 'salary')

def test_task_024_grouped_summaries_sorted_output() -> None:
    assert grouped_summaries(CSV_UNSORTED, 'dept', 'salary') == 'eng: total=350.0, count=3, avg=116.67\nsales: total=200.0, count=2, avg=100.0'

def test_task_025_grouped_summaries_group_totals() -> None:
    assert grouped_summaries(CSV_DATA, 'dept', 'salary') == 'eng: total=350.0, count=3, avg=116.67\nsales: total=200.0, count=2, avg=100.0'

def test_task_026_grouped_summaries_joiner() -> None:
    assert '\n\n' not in grouped_summaries(CSV_DATA, 'dept', 'salary')

def test_task_027_category_report_preserve_case() -> None:
    assert 'Alice: 1' in category_report(CSV_DATA, 'name')

def test_task_028_total_summary_no_extra_rows() -> None:
    assert total_summary(CSV_DATA, 'salary', 'All Salaries') == 'All Salaries: total=550.0, count=5, avg=110.0'

def test_task_029_grouped_summaries_label_key() -> None:
    assert grouped_summaries(CSV_DATA, 'dept', 'salary').startswith('eng: total=')

def test_task_030_filtered_report_category_field() -> None:
    assert (
        filtered_category_report(CSV_DATA, "dept", "eng", "name")
        == "Filtered Report:\n  Alice: 1\n  Bob: 1\n  Eve: 1"
    )

