from __future__ import annotations


TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
FALSE_VALUES = {"0", "false", "no", "off", "disabled"}


def parse_retry_header(header: str | None) -> int:
    """Parse a Retry-After style value and keep a one-second minimum."""
    if header is None or not header.strip():
        return 1
    return max(1, int(header.strip()))


def parse_feature_flag(value: str | None) -> bool:
    """Parse common string representations for on and off feature flags."""
    if value is None:
        return False
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"Unsupported feature flag value: {value!r}")
