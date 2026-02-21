"""Structured logging helpers for pipeline services."""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

_CORRELATION_KEYS = ("repo_id", "workflow_id", "job_id")


def configure_logging(*, debug: bool) -> None:
    """Configure process-wide logging format and level."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def correlation_from_payload(payload: Mapping[str, Any]) -> dict[str, str | None]:
    """Extract canonical correlation identifiers from an activity/workflow payload."""
    return {
        "repo_id": _coerce_str(payload.get("repo_id")),
        "workflow_id": _coerce_str(payload.get("workflow_id")),
        "job_id": _coerce_str(payload.get("job_id")),
    }


def structured_event(event: str, **fields: Any) -> str:
    """Render one structured log event as compact JSON."""
    payload = {"event": event, **fields}
    for key in _CORRELATION_KEYS:
        payload.setdefault(key, None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _coerce_str(value: Any) -> str | None:
    """Convert a value to a non-empty string or `None`."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
