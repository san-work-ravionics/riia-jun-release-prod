"""Functional scenario tests for the FnO dashboard.

One test per menu section. Pure HTTP via requests, no browser.
Same server fixture as test_smoke.py and test_rita_scenarios.py.

Failing test = that FnO section will be empty or error on load.
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
# UC-F01  Dashboard (Overview) — portfolio summary cards
# ---------------------------------------------------------------------------

def test_fno_dashboard_health(base_url):
    """api.js: GET /health — server status shown on FnO overview."""
    r = requests.get(f"{base_url}/health", timeout=TIMEOUT)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_fno_dashboard_portfolio_summary(base_url):
    """api.js: GET /api/v1/portfolio/summary — KPI cards on FnO dashboard."""
    r = requests.get(f"{base_url}/api/v1/portfolio/summary", timeout=TIMEOUT)
    assert r.status_code == 200, f"portfolio/summary missing — FnO Dashboard will be empty: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-F02  Positions
# ---------------------------------------------------------------------------

def test_fno_positions(base_url):
    """positions.js: GET /api/experience/fno/ — positions table."""
    r = requests.get(f"{base_url}/api/experience/fno/", timeout=TIMEOUT)
    assert r.status_code == 200, f"fno experience endpoint missing: {r.status_code}"
    body = r.json()
    assert "snapshots" in body or "positions" in body or "manoeuvres" in body


# ---------------------------------------------------------------------------
# UC-F03  Margin Tracker
# ---------------------------------------------------------------------------

def test_fno_margin(base_url):
    """margin.js: data comes via /api/experience/fno/ — margin fields."""
    r = requests.get(f"{base_url}/api/experience/fno/", timeout=TIMEOUT)
    assert r.status_code == 200, f"fno experience endpoint missing: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-F04  Risk & Greeks
# ---------------------------------------------------------------------------

def test_fno_greeks(base_url):
    """greeks.js: data comes via /api/experience/fno/ — greeks fields."""
    r = requests.get(f"{base_url}/api/experience/fno/", timeout=TIMEOUT)
    assert r.status_code == 200
    body = r.json()
    assert "snapshots" in body or "manoeuvres" in body


# ---------------------------------------------------------------------------
# UC-F05  Risk-Reward (Scenarios)
# ---------------------------------------------------------------------------

def test_fno_risk_reward_price_history(base_url):
    """rr.js: GET /api/v1/portfolio/price-history — price chart data."""
    r = requests.get(f"{base_url}/api/v1/portfolio/price-history", timeout=TIMEOUT)
    assert r.status_code == 200, f"portfolio/price-history missing — Risk-Reward section will be empty: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-F06  Hedge Radar
# ---------------------------------------------------------------------------

def test_fno_hedge_history(base_url):
    """hedge.js: GET /api/v1/portfolio/hedge-history — hedge suggestions table."""
    r = requests.get(f"{base_url}/api/v1/portfolio/hedge-history", timeout=TIMEOUT)
    assert r.status_code == 200, f"portfolio/hedge-history missing — Hedge Radar will be empty: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-F07  Hedge History
# ---------------------------------------------------------------------------

def test_fno_hedge_history_list(base_url):
    """hedge.js: GET /api/v1/portfolio/hedge-history — historical hedge list."""
    r = requests.get(f"{base_url}/api/v1/portfolio/hedge-history", timeout=TIMEOUT)
    assert r.status_code == 200, f"portfolio/hedge-history missing: {r.status_code}"
    assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# UC-F08  Manoeuvre
# ---------------------------------------------------------------------------

def test_fno_manoeuvre_groups(base_url):
    """manoeuvre.js: GET /api/v1/portfolio/man-groups — manoeuvre group list."""
    r = requests.get(f"{base_url}/api/v1/portfolio/man-groups", timeout=TIMEOUT)
    assert r.status_code == 200, f"portfolio/man-groups missing — Manoeuvre section will be empty: {r.status_code}"


def test_fno_manoeuvre_snapshot(base_url):
    """manoeuvre.js: POST /api/v1/portfolio/man-snapshot — snapshot on manoeuvre apply."""
    r = requests.post(f"{base_url}/api/v1/portfolio/man-snapshot", json={}, timeout=TIMEOUT)
    assert r.status_code in (200, 201, 422), f"man-snapshot endpoint missing: {r.status_code}"


def test_fno_manoeuvre_pnl_history(base_url):
    """manoeuvre.js: GET /api/v1/portfolio/man-pnl-history — P&L history chart."""
    r = requests.get(f"{base_url}/api/v1/portfolio/man-pnl-history", timeout=TIMEOUT)
    assert r.status_code == 200, f"portfolio/man-pnl-history missing — Manoeuvre P&L chart will be empty: {r.status_code}"
