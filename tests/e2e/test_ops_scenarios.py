"""Functional scenario tests for the Ops dashboard.

One test per menu section. Pure HTTP via requests, no browser.
Same server fixture as test_smoke.py.

Failing test = that Ops section will be empty or error on load.
"""

from __future__ import annotations

import time

import requests
import pytest

TIMEOUT = 15


_test_counter = {"n": 0}
_BATCH_SIZE = 4
_BATCH_PAUSE_S = 5  # seconds to let uvicorn recover between batches


@pytest.fixture(autouse=True)
def pace():
    """Pause between tests; after every BATCH_SIZE tests pause longer to let
    the uvicorn subprocess recover before the next group."""
    _test_counter["n"] += 1
    if _test_counter["n"] > 1 and (_test_counter["n"] - 1) % _BATCH_SIZE == 0:
        time.sleep(_BATCH_PAUSE_S)
    else:
        time.sleep(1)
    yield


# ---------------------------------------------------------------------------
# UC-O01  Overview
# ---------------------------------------------------------------------------

def test_ops_overview_health(base_url):
    """overview.js: GET /health — server liveness on Overview."""
    r = requests.get(f"{base_url}/health", timeout=TIMEOUT)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_ops_overview_metrics(base_url):
    """overview.js: GET /metrics — Prometheus metrics on Overview."""
    r = requests.get(f"{base_url}/metrics", timeout=TIMEOUT)
    assert r.status_code == 200


def test_ops_overview_step_log(base_url):
    """overview.js: GET /api/v1/step-log — pipeline step list on Overview."""
    r = requests.get(f"{base_url}/api/v1/step-log", timeout=TIMEOUT)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_ops_overview_mcp_calls(base_url):
    """overview.js: GET /api/v1/mcp-calls — MCP call count on Overview."""
    r = requests.get(f"{base_url}/api/v1/mcp-calls", timeout=TIMEOUT)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_ops_overview_data_prep_status(base_url):
    """overview.js: GET /api/v1/data-prep/status — data prep status card."""
    r = requests.get(f"{base_url}/api/v1/data-prep/status", timeout=TIMEOUT)
    assert r.status_code == 200, f"data-prep/status missing — Overview data prep card will be empty: {r.status_code}"


def test_ops_overview_progress(base_url):
    """overview.js / sidebar.js: GET /progress — pipeline progress bar."""
    r = requests.get(f"{base_url}/progress", timeout=TIMEOUT)
    assert r.status_code == 200, f"/progress missing — Overview progress bar will be empty: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-O02  Monitoring
# ---------------------------------------------------------------------------

def test_ops_monitoring_metrics_summary(base_url):
    """monitoring.js: GET /api/v1/metrics/summary — API counters panel."""
    r = requests.get(f"{base_url}/api/v1/metrics/summary", timeout=TIMEOUT)
    assert r.status_code == 200
    body = r.json()
    assert "api_requests" in body
    assert "pipeline" in body


def test_ops_monitoring_step_log(base_url):
    """monitoring.js: GET /api/v1/step-log — step timing table."""
    r = requests.get(f"{base_url}/api/v1/step-log", timeout=TIMEOUT)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# UC-O03  CI/CD
# ---------------------------------------------------------------------------

def test_ops_cicd_step_log(base_url):
    """cicd.js: GET /api/v1/step-log — CI/CD pipeline step log."""
    r = requests.get(f"{base_url}/api/v1/step-log", timeout=TIMEOUT)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# UC-O04  Deploy
# ---------------------------------------------------------------------------

def test_ops_deploy_health(base_url):
    """deploy.js: GET /health — deployment health status."""
    r = requests.get(f"{base_url}/health", timeout=TIMEOUT)
    assert r.status_code == 200


def test_ops_deploy_training_history(base_url):
    """deploy.js: GET /api/v1/training-history — model version list for deploy."""
    r = requests.get(f"{base_url}/api/v1/training-history", timeout=TIMEOUT)
    assert r.status_code == 200, f"training-history missing — Deploy model list will be empty: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-O05  Observability
# ---------------------------------------------------------------------------

def test_ops_observability_drift(base_url):
    """observability.js: GET /api/v1/drift — drift health checks."""
    r = requests.get(f"{base_url}/api/v1/drift", timeout=TIMEOUT)
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body
    assert "checks" in body


def test_ops_observability_mcp_calls(base_url):
    """observability.js: GET /api/v1/mcp-calls — MCP tool call log."""
    r = requests.get(f"{base_url}/api/v1/mcp-calls", timeout=TIMEOUT)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# UC-O06  Chat / AI Monitor
# ---------------------------------------------------------------------------

def test_ops_chat_monitor(base_url):
    """chat.js: GET /api/v1/chat/monitor — chat session monitor."""
    r = requests.get(f"{base_url}/api/v1/chat/monitor", timeout=TIMEOUT)
    assert r.status_code == 200, f"chat/monitor missing — Ops Chat section will be empty: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-O07  Daily Ops
# ---------------------------------------------------------------------------

def test_ops_daily_status(base_url):
    """daily-ops.js: GET /api/v1/portfolio/man-daily-status — daily manoeuvre status."""
    r = requests.get(f"{base_url}/api/v1/portfolio/man-daily-status", timeout=TIMEOUT)
    assert r.status_code == 200, f"portfolio/man-daily-status missing — Daily Ops will be empty: {r.status_code}"


def test_ops_daily_snapshot(base_url):
    """daily-ops.js: POST /api/v1/portfolio/man-daily-snapshot — record daily snapshot."""
    r = requests.post(f"{base_url}/api/v1/portfolio/man-daily-snapshot", json={}, timeout=TIMEOUT)
    assert r.status_code in (200, 201, 422), f"man-daily-snapshot missing: {r.status_code}"
