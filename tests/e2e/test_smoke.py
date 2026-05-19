"""Smoke tests — pure HTTP checks using ``requests``.

These tests verify that the server starts correctly and all critical
endpoints respond with the expected status codes and payload shapes.
No browser is involved; they run fast and give early failure signal.

All tests depend on the ``base_url`` fixture defined in conftest.py,
which in turn depends on the ``server`` fixture that starts uvicorn.
"""

from __future__ import annotations

import requests
import pytest


# ---------------------------------------------------------------------------
# Health & readiness
# ---------------------------------------------------------------------------

def test_health_ok(base_url: str) -> None:
    """/health must return 200 with status: ok."""
    resp = requests.get(f"{base_url}/health", timeout=5)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    body = resp.json()
    assert body.get("status") == "ok", f"Unexpected body: {body}"


def test_readyz_ok(base_url: str) -> None:
    """/readyz must return 200 with status: ready."""
    resp = requests.get(f"{base_url}/readyz", timeout=5)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    body = resp.json()
    assert body.get("status") == "ready", f"Unexpected body: {body}"


# ---------------------------------------------------------------------------
# OpenAPI docs
# ---------------------------------------------------------------------------

def test_docs_ok(base_url: str) -> None:
    """/docs (Swagger UI) must return 200."""
    resp = requests.get(f"{base_url}/docs", timeout=5)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"


# ---------------------------------------------------------------------------
# Dashboard HTML pages
# ---------------------------------------------------------------------------

def test_dashboard_rita_ok(base_url: str) -> None:
    """/dashboard/rita.html must return 200 and contain 'RITA'."""
    resp = requests.get(f"{base_url}/dashboard/rita.html", timeout=15)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "RITA" in resp.text, "Response body does not contain 'RITA'"


def test_dashboard_fno_ok(base_url: str) -> None:
    """/dashboard/fno.html must return 200 and contain 'RIIA'."""
    resp = requests.get(f"{base_url}/dashboard/fno.html", timeout=15)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "RIIA" in resp.text, "Response body does not contain 'RIIA'"


def test_dashboard_ops_ok(base_url: str) -> None:
    """/dashboard/ops.html must return 200 and contain 'RIIA'."""
    resp = requests.get(f"{base_url}/dashboard/ops.html", timeout=15)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "RIIA" in resp.text, "Response body does not contain 'RIIA'"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def test_metrics_ok(base_url: str) -> None:
    """/metrics (Prometheus) must return 200."""
    resp = requests.get(f"{base_url}/metrics", timeout=15)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
