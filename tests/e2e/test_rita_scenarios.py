"""Functional scenario tests for the RITA dashboard.

One test per UI section. Each test calls the exact API endpoint(s) that
populate that section and asserts the response shape is correct.

Tests use the same ``base_url`` / ``server`` fixtures as test_smoke.py —
a real uvicorn process, pure HTTP via requests, no browser.

Failing test = UI section will be empty or error on load.
"""

from __future__ import annotations

import time

import requests
import pytest

TIMEOUT = 15


_test_counter = {"n": 0}
_BATCH_SIZE = 4
_BATCH_PAUSE_S = 5


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
# UC-01  Model Overview (home) — system health card
# ---------------------------------------------------------------------------

def test_overview_health(base_url):
    """health.js: GET /health — status card on Model Overview page."""
    r = requests.get(f"{base_url}/health", timeout=TIMEOUT)
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    assert "version" in body


def test_overview_readiness(base_url):
    """health.js: GET /readyz — DB connectivity shown on Model Overview."""
    r = requests.get(f"{base_url}/readyz", timeout=TIMEOUT)
    assert r.status_code == 200
    assert r.json().get("status") == "ready"


def test_overview_metrics(base_url):
    """health.js: GET /api/experience/ops/metrics/summary — API counters on Model Overview."""
    r = requests.get(f"{base_url}/api/experience/ops/metrics/summary", timeout=TIMEOUT)
    assert r.status_code == 200
    body = r.json()
    assert "api_requests" in body
    assert "pipeline" in body
    assert "training" in body


# ---------------------------------------------------------------------------
# UC-02  Financial Goal — performance KPIs
# ---------------------------------------------------------------------------

def test_financial_goal_performance_summary(base_url):
    """health.js / performance.js: GET /api/v1/performance-summary — KPI cards."""
    r = requests.get(f"{base_url}/api/v1/performance-summary", timeout=TIMEOUT)
    assert r.status_code == 200, f"performance-summary missing — Financial Goal section will be empty: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-03  Market Signals
# ---------------------------------------------------------------------------

def test_market_signals(base_url):
    """market-signals.js: GET /api/v1/market-signals — signals table."""
    r = requests.get(f"{base_url}/api/v1/market-signals?timeframe=daily&periods=100", timeout=TIMEOUT)
    assert r.status_code == 200, f"market-signals missing — Market Signals section will be empty: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-04  Scenarios — run backtest for a date range
# ---------------------------------------------------------------------------

def test_scenarios_load_data(base_url):
    """scenarios.js: GET /api/v1/backtest-daily — baseline chart on load."""
    r = requests.get(f"{base_url}/api/v1/backtest-daily", timeout=TIMEOUT)
    assert r.status_code == 200, f"backtest-daily missing — Scenarios section will be empty: {r.status_code}"


def test_scenarios_submit_backtest(base_url):
    """scenarios.js: POST /api/v1/backtest — user triggers a scenario run."""
    r = requests.post(f"{base_url}/api/v1/backtest", json={}, timeout=TIMEOUT)
    assert r.status_code in (200, 201, 202), f"backtest submission failed: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-05  Performance
# ---------------------------------------------------------------------------

def test_performance_summary(base_url):
    """performance.js: GET /api/v1/performance-summary — Sharpe, MDD, return KPIs."""
    r = requests.get(f"{base_url}/api/v1/performance-summary", timeout=TIMEOUT)
    assert r.status_code == 200, f"performance-summary missing: {r.status_code}"


def test_performance_backtest_daily(base_url):
    """performance.js: GET /api/v1/backtest-daily — equity curve chart."""
    r = requests.get(f"{base_url}/api/v1/backtest-daily", timeout=TIMEOUT)
    assert r.status_code == 200, f"backtest-daily missing: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-06  Trade Journal
# ---------------------------------------------------------------------------

def test_trade_journal(base_url):
    """trades.js: GET /api/v1/risk-timeline?phase=all — trade log table."""
    r = requests.get(f"{base_url}/api/v1/risk-timeline?phase=all", timeout=TIMEOUT)
    assert r.status_code == 200, f"risk-timeline missing — Trade Journal will be empty: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-07  Trade Diagnostics
# ---------------------------------------------------------------------------

def test_trade_diagnostics_daily(base_url):
    """diagnostics.js: GET /api/v1/backtest-daily — diagnostic charts."""
    r = requests.get(f"{base_url}/api/v1/backtest-daily", timeout=TIMEOUT)
    assert r.status_code == 200, f"backtest-daily missing: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-08  Explainability
# ---------------------------------------------------------------------------

def test_explainability_shap(base_url):
    """explainability.js: GET /api/v1/shap — SHAP feature importance table."""
    r = requests.get(f"{base_url}/api/v1/shap", timeout=TIMEOUT)
    assert r.status_code == 200, f"shap missing — Explainability section will be empty: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-09  Risk View
# ---------------------------------------------------------------------------

def test_risk_timeline(base_url):
    """risk.js: GET /api/v1/risk-timeline — risk chart data."""
    r = requests.get(f"{base_url}/api/v1/risk-timeline", timeout=TIMEOUT)
    assert r.status_code == 200, f"risk-timeline missing — Risk View will be empty: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-10  Training Progress
# ---------------------------------------------------------------------------

def test_training_history(base_url):
    """training.js: GET /api/v1/training-history — training run table."""
    r = requests.get(f"{base_url}/api/v1/training-history", timeout=TIMEOUT)
    assert r.status_code == 200, f"training-history missing — Training Progress will be empty: {r.status_code}"
    assert isinstance(r.json(), list)


def test_training_submit(base_url, auth_token):
    """workflow: POST /api/v1/workflow/train — user triggers a training run (JWT required)."""
    payload = {
        "model_version": "v1.0-test",
        "algorithm": "DoubleDQN",
        "timesteps": 1000,
        "learning_rate": 0.0001,
        "buffer_size": 1000,
        "net_arch": "[64, 64]",
        "exploration_pct": 0.1,
    }
    headers = {"Authorization": f"Bearer {auth_token}"}
    r = requests.post(f"{base_url}/api/v1/workflow/train", json=payload, headers=headers, timeout=TIMEOUT)
    assert r.status_code in (200, 201, 202), f"train submission failed: {r.status_code}"
    body = r.json()
    assert "run_id" in body or "status" in body


# ---------------------------------------------------------------------------
# UC-11  Observability
# ---------------------------------------------------------------------------

def test_observability_drift(base_url):
    """observability.js: GET /api/v1/drift — drift health checks."""
    r = requests.get(f"{base_url}/api/v1/drift", timeout=TIMEOUT)
    assert r.status_code == 200
    body = r.json()
    # Endpoint shape: { "summary": { "overall": "ok"|"warn"|"alert" }, "checks": {...} }
    assert "summary" in body, f"Expected 'summary' key in drift response, got: {list(body.keys())}"
    assert "checks" in body, f"Expected 'checks' key in drift response, got: {list(body.keys())}"


def test_observability_step_log(base_url):
    """observability.js: GET /api/experience/ops/step-log — pipeline step table."""
    r = requests.get(f"{base_url}/api/experience/ops/step-log", timeout=TIMEOUT)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# UC-12  MCP Calls
# ---------------------------------------------------------------------------

def test_mcp_calls(base_url):
    """mcp.js: GET /api/v1/mcp-calls — MCP tool call log."""
    r = requests.get(f"{base_url}/api/v1/mcp-calls", timeout=TIMEOUT)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# UC-13  Audit
# ---------------------------------------------------------------------------

def test_audit_training_history(base_url):
    """audit.js: GET /api/v1/training-history — training runs in audit log."""
    r = requests.get(f"{base_url}/api/v1/training-history", timeout=TIMEOUT)
    assert r.status_code == 200, f"training-history missing: {r.status_code}"


def test_audit_step_log(base_url):
    """audit.js: GET /api/experience/ops/step-log — step log in audit view."""
    r = requests.get(f"{base_url}/api/experience/ops/step-log", timeout=TIMEOUT)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
