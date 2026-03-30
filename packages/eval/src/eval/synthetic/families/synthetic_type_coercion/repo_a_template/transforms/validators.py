from __future__ import annotations


def validate_percentage(value: float) -> float:
    """Validate value is between 0 and 100 inclusive. Raise ValueError otherwise."""
    if not isinstance(value, (int, float)):
        raise TypeError(f"Expected numeric value, got {type(value).__name__}")
    if value < 0 or value > 100:
        raise ValueError(f"Percentage must be between 0 and 100, got {value}")
    return float(value)


def validate_non_empty(text: str) -> str:
    """Validate that text is non-empty after stripping whitespace."""
    stripped = text.strip()
    if not stripped:
        raise ValueError("Text must not be empty or whitespace-only")
    return stripped
