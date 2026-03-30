from __future__ import annotations

from domainlib.pipeline import load_records
from domainlib.aggregation import group_by, sum_field
from domainlib.output import format_table, format_summary


def grouped_totals(csv_data: str, group_field: str, value_field: str) -> str:
    records = load_records(csv_data)
    groups = group_by(records, group_field)
    totals = {}
    for key, group_records in groups.items():
        totals[key] = sum_field(group_records, value_field)
    return format_table(totals, title="Group Totals")


def grouped_summaries(csv_data: str, group_field: str, value_field: str) -> str:
    records = load_records(csv_data)
    groups = group_by(records, group_field)
    lines = []
    for key in sorted(groups.keys()):
        group_records = groups[key]
        total = sum_field(group_records, value_field)
        lines.append(format_summary(key, total, len(group_records)))
    return "\n".join(lines)
