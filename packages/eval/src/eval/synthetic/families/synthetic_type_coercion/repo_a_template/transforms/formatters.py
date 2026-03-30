from __future__ import annotations


def format_percentage(value: float, decimals: int = 1) -> str:
    """Format a ratio (0.0-1.0) as a percentage string."""
    return f"{value * 100:.{decimals}f}%"


def format_bytes(size: int) -> str:
    """Format byte count as human-readable string."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"
