from __future__ import annotations

from providerlib.http import parse_retry_header


def describe_retry_delay(header: str | None) -> str:
    seconds = parse_retry_header(header)
    suffix = "second" if seconds == 1 else "seconds"
    return f"retry in {seconds} {suffix}"
