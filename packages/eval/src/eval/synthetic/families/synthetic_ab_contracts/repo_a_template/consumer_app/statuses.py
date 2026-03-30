from __future__ import annotations

from providerlib.ui import status_to_color


def badge_color(status: str) -> str:
    return status_to_color(status)
