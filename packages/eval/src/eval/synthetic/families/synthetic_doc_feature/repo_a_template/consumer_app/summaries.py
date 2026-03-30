from __future__ import annotations

from domainlib.pipeline import load_records, filter_records
from domainlib.aggregation import sum_field, group_by
from domainlib.output import format_summary


def total_summary(csv_data: str, value_field: str, label: str) -> str:
    records = load_records(csv_data)
    total = sum_field(records, value_field)
    return format_summary(label, total, len(records))


def filtered_summary(csv_data: str, filter_field: str, filter_value: str, value_field: str, label: str) -> str:
    records = load_records(csv_data)
    filtered = filter_records(records, filter_field, filter_value)
    total = sum_field(filtered, value_field)
    return format_summary(label, total, len(filtered))
