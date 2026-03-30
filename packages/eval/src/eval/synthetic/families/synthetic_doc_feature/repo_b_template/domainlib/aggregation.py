from __future__ import annotations


def sum_field(records: list[dict[str, str]], field: str) -> float:
    """Sum numeric values of a field across all records.

    Behavior:
    - Non-numeric values are treated as 0.0 (no error raised).
    - Missing fields are treated as 0.0.
    - Returns 0.0 for an empty list.

    Composition pattern:
    - Use after load_records() and optional filter_records().
    - To compute an average, combine with count: sum_field() / len(records).
    """
    total = 0.0
    for r in records:
        try:
            total += float(r.get(field, "0"))
        except (ValueError, TypeError):
            pass
    return total


def group_by(records: list[dict[str, str]], key_field: str) -> dict[str, list[dict[str, str]]]:
    """Group records by the value of key_field.

    Behavior:
    - Grouping is case-insensitive; the FIRST-SEEN casing is used as the group key.
    - Records missing key_field are grouped under "(ungrouped)".
    - Each group preserves the original record order.

    Composition pattern:
    - Use after load_records(). Then iterate over groups and apply sum_field() or
      aggregate() to each group independently.
    """
    groups: dict[str, list[dict[str, str]]] = {}
    seen_lower: dict[str, str] = {}
    for r in records:
        raw = r.get(key_field, "").strip()
        if not raw:
            group_key = "(ungrouped)"
        else:
            lower = raw.lower()
            if lower not in seen_lower:
                seen_lower[lower] = raw
            group_key = seen_lower[lower]
        groups.setdefault(group_key, []).append(r)
    return groups
