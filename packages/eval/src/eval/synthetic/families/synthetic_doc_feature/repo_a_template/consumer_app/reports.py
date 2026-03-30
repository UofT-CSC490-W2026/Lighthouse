from __future__ import annotations

from domainlib.pipeline import load_records, filter_records, aggregate
from domainlib.output import format_table


def category_report(csv_data: str, category_field: str) -> str:
    records = load_records(csv_data)
    counts = aggregate(records, category_field)
    return format_table(counts, title="Category Report")


def filtered_category_report(csv_data: str, filter_field: str, filter_value: str, category_field: str) -> str:
    records = load_records(csv_data)
    filtered = filter_records(records, filter_field, filter_value)
    counts = aggregate(filtered, category_field)
    return format_table(counts, title="Filtered Report")
