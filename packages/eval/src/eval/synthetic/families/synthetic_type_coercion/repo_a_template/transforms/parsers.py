from __future__ import annotations


def parse_port(text: str) -> int:
    """Parse a port number string. Raise ValueError if not a valid port."""
    value = int(text.strip())
    if value < 0 or value > 65535:
        raise ValueError(f"Port out of range: {value}")
    return value


def safe_float(text: str, default: float = 0.0) -> float:
    """Parse text as float, returning default when text is not a valid number."""
    cleaned = text.strip()
    if not cleaned:
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default
