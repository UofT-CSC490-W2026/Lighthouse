"""Tests for pipeline HTTP health and readiness endpoints."""

from __future__ import annotations

import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from src import server


def test_health_reports_ok_when_worker_startup_is_disabled() -> None:
    """`/health` should return liveness payload when worker startup is disabled."""
    with patch.object(server.settings, "run_worker_on_startup", False):
        with TestClient(server.app) as client:
            response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "pipeline"
    assert body["worker_status"] == "disabled"


def test_ready_reports_ready_when_worker_startup_is_disabled() -> None:
    """`/ready` should report ready when worker startup is intentionally disabled."""
    with patch.object(server.settings, "run_worker_on_startup", False):
        with TestClient(server.app) as client:
            response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["worker_status"] == "disabled"


def test_ready_reports_not_ready_after_worker_startup_failure() -> None:
    """`/ready` should fail when embedded worker startup crashes."""

    async def _failing_worker(*, configure_log: bool = True) -> None:
        _ = configure_log
        raise RuntimeError("worker startup failed")

    with (
        patch.object(server.settings, "run_worker_on_startup", True),
        patch.object(server, "run_worker_service", _failing_worker),
    ):
        with TestClient(server.app) as client:
            response = None
            for _ in range(20):
                response = client.get("/ready")
                if response.status_code == 503:
                    break
                time.sleep(0.01)

    assert response is not None
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["worker_status"] == "failed"
    assert "worker startup failed" in body["error"]
