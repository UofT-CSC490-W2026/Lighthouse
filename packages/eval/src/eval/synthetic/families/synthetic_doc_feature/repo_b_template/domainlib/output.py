from __future__ import annotations


def format_table(data: dict[str, int | float], title: str = "Results") -> str:
    """Format a dict as a simple text table.

    Behavior:
    - First line is the title followed by a colon.
    - Each subsequent line is "  key: value".
    - Keys are sorted alphabetically.
    - Returns just the title line with "(empty)" when the dict is empty.

    Composition pattern:
    - Typically the final step: aggregate() -> format_table().
    - Can also be used with sum_field() results wrapped in a dict.
    """
    if not data:
        return f"{title}: (empty)"
    lines = [f"{title}:"]
    for key in sorted(data.keys()):
        lines.append(f"  {key}: {data[key]}")
    return "\n".join(lines)


def format_summary(label: str, total: float, count: int) -> str:
    """Format a summary line with total, count, and average.

    Behavior:
    - Format: "label: total=X, count=Y, avg=Z"
    - Average is rounded to 2 decimal places.
    - When count is 0, average is shown as "N/A".

    Composition pattern:
    - Use after computing sum_field() and len() of the filtered records.
    - Combine multiple format_summary() results with newlines for a full report.
    """
    if count == 0:
        avg_str = "N/A"
    else:
        avg_str = f"{round(total / count, 2)}"
    return f"{label}: total={total}, count={count}, avg={avg_str}"
