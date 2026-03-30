from __future__ import annotations


def load_records(raw: str) -> list[dict[str, str]]:
    """Parse a CSV-like string into a list of record dicts.

    Behavior:
    - The first line is the header row (comma-separated field names).
    - Subsequent lines are data rows.
    - Empty lines are skipped.
    - Returns an empty list if there are no data rows.
    - Field names and values are stripped of leading/trailing whitespace.

    Composition pattern:
    - Typically used as the first step in a pipeline: load_records() -> filter_records() -> aggregate().
    """
    lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]
    if not lines:
        return []
    headers = [h.strip() for h in lines[0].split(",")]
    records = []
    for line in lines[1:]:
        values = [v.strip() for v in line.split(",")]
        records.append(dict(zip(headers, values)))
    return records


def filter_records(records: list[dict[str, str]], field: str, value: str) -> list[dict[str, str]]:
    """Filter records where field equals value (case-insensitive comparison).

    Behavior:
    - Comparison is case-insensitive on both the record value and the filter value.
    - Records missing the field are excluded.
    - Returns an empty list if no records match.

    Composition pattern:
    - Typically called after load_records() and before aggregate().
    - Multiple filter_records() calls can be chained for AND logic.
    """
    return [
        r for r in records
        if r.get(field, "").strip().lower() == value.strip().lower()
    ]


def aggregate(records: list[dict[str, str]], field: str) -> dict[str, int]:
    """Count occurrences of each distinct value in the given field.

    Behavior:
    - Values are compared case-insensitively; the FIRST-SEEN casing is used as the key.
    - Records missing the field are counted under the key "(missing)".
    - Returns an empty dict when the input list is empty.

    Composition pattern:
    - Typically the final transformation step: load_records() -> filter_records() -> aggregate().
    - The result is passed to format_table() for display.
    """
    counts: dict[str, int] = {}
    seen_lower: dict[str, str] = {}
    for r in records:
        raw_value = r.get(field, "").strip()
        if not raw_value:
            key = "(missing)"
        else:
            lower = raw_value.lower()
            if lower not in seen_lower:
                seen_lower[lower] = raw_value
            key = seen_lower[lower]
        counts[key] = counts.get(key, 0) + 1
    return counts
