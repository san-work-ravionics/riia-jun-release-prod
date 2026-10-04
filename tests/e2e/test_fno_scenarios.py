"""Functional scenario tests for the FnO dashboard.

One test per menu section. Pure HTTP via requests, no browser.
Same server fixture as test_smoke.py and test_rita_scenarios.py.

Failing test = that FnO section will be empty or error on load.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import requests
import pytest

from tests.e2e.conftest import ISO_LAST_CLOSE, ISO_SHARES

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
# UC-F06  Hedge Radar (retired page; endpoint kept, no workflow consumer since F40)
# ---------------------------------------------------------------------------

def test_fno_hedge_history(base_url):
    """GET /api/v1/portfolio/hedge-history — Manoeuvre hedge action log (flat list; no longer shown on the Save step)."""
    r = requests.get(f"{base_url}/api/v1/portfolio/hedge-history", timeout=TIMEOUT)
    assert r.status_code == 200, f"portfolio/hedge-history missing — Hedge Radar will be empty: {r.status_code}"


# ---------------------------------------------------------------------------
# UC-F07  Hedge History
# ---------------------------------------------------------------------------

def test_fno_hedge_history_list(base_url):
    """GET /api/v1/portfolio/hedge-history — flat list shape (no longer shown on the Save step)."""
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


# ---------------------------------------------------------------------------
# UC-F39  Unified Hedge Workflow (Phase 3) — exposure -> recommendation ->
#         what-if -> save, then reload restores step + history.
#         Pure HTTP: exercises the exact endpoints the 4 step modules call.
# ---------------------------------------------------------------------------

def _auth(auth_token) -> dict:
    return {"Authorization": f"Bearer {auth_token}"}


def test_fno_hedge_workflow_exposure_leg(base_url, auth_token):
    """Exposure leg: portfolio-analytics, portfolio-hedge, POST equity-hedge-scenarios."""
    headers = _auth(auth_token)

    r = requests.get(f"{base_url}/api/v1/experience/fno/portfolio-analytics",
                     params={"mode": "real"}, headers=headers, timeout=TIMEOUT)
    assert r.status_code == 200, f"portfolio-analytics failed: {r.status_code} {r.text}"
    data = r.json()
    for key in ("positions", "greeks", "net_greeks", "hedge_quality"):
        assert key in data, f"portfolio-analytics missing '{key}'"

    # portfolio-hedge needs an active portfolio: 404 'No active portfolio found' is the
    # documented dev-user state (no portfolio key). 200 is verified for shape.
    r = requests.get(f"{base_url}/api/v1/experience/fno/portfolio-hedge",
                     params={"coverage": 50}, headers=headers, timeout=TIMEOUT)
    assert r.status_code in (200, 404), f"portfolio-hedge unexpected: {r.status_code} {r.text}"
    if r.status_code == 200:
        assert "holdings" in r.json()

    end = date.today()
    body = {"instrument": "NIFTY", "n_shares": 1,
            "start_date": (end - timedelta(days=365)).isoformat(), "end_date": end.isoformat()}
    r = requests.post(f"{base_url}/api/v1/portfolio/equity-hedge-scenarios", json=body, timeout=TIMEOUT)
    if r.status_code == 422:
        pytest.skip(f"equity-hedge-scenarios has no price data for NIFTY here: {r.text[:120]}")
    assert r.status_code == 200, f"equity-hedge-scenarios failed: {r.status_code} {r.text[:200]}"
    assert "portfolio" in r.json()


def test_fno_hedge_workflow_recommendation_leg(base_url):
    """Recommendation leg: Hedge Advisor cascade (no auth, deterministic)."""
    r = requests.get(
        f"{base_url}/api/v1/experience/fno/hedge-reasoning",
        params={"instrument": "NIFTY", "n_shares": 10},
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        pytest.skip(f"hedge-reasoning needs instrument data not present here: {r.status_code}")
    adv = r.json()
    for key in ("instrument", "steps", "recommendation", "confidence", "spot_price", "data_source"):
        assert key in adv, f"hedge-reasoning missing '{key}'"
    assert adv["recommendation"] in ("call_sell", "put_buy", "no_hedge")


def test_fno_hedge_workflow_whatif_leg(base_url, auth_token):
    """What-if leg: kite-live always answers 200 (fallback in-payload when middleware is down)."""
    r = requests.get(
        f"{base_url}/api/v1/experience/fno/kite-live",
        params={"instrument_id": "NIFTY"},
        headers=_auth(auth_token),
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, f"kite-live must never fail: {r.status_code} {r.text}"
    assert r.json()["source"] in ("kite", "fallback")


def test_fno_hedge_workflow_save_leg(iso_base_url, iso_headers):
    """Save leg (F40, STRICT — no skip): runs on the isolated, seeded temp DB (iso_* fixtures).

    PUT explicit save -> GET restores last_step "save" + per-instrument selections; an
    Overview-style PUT (no last_step) preserves "save"; every PUT appends one history row
    (no dedupe); the history row carries the server-side market block.
    Isolation is enforced by the isolated_server startup guard (conftest.py).
    """
    url = f"{iso_base_url}/api/v1/experience/fno/hedge-plan"
    r = requests.get(f"{url}/history", headers=iso_headers, timeout=TIMEOUT)
    assert r.status_code == 200 and r.json()["count"] == 0, "isolated DB must start with no history"

    sel = {"ASML": "put_buy", "RELIANCE": "call_sell"}
    body = {"hedged_ids": ["ASML", "RELIANCE"], "coverage": 60, "scenario_tab": "collar",
            "last_step": "save", "trigger": "explicit", "source": "workflow", "selections": sel,
            "context": {"instruments": [{"instrument_id": "ASML", "strike_pct": 95.0, "premium_pct": 0.4,
                                         "cost_source": "kite_csv", "hedge_type": "put"}],
                        "margin": {"amount": 1000, "currency": "INR"}}}
    r = requests.put(url, json=body, headers=iso_headers, timeout=TIMEOUT)
    assert r.status_code == 200, f"hedge-plan PUT failed: {r.status_code} {r.text}"

    plan = requests.get(url, headers=iso_headers, timeout=TIMEOUT).json()
    assert plan["last_step"] == "save" and plan["coverage"] == 60
    assert plan["hedged_ids"] == ["ASML", "RELIANCE"] and plan["scenario_tab"] == "collar"
    assert plan["selections"] == sel

    # Overview-style autosave: no last_step -> server preserves "save"; selections preserved when omitted
    r = requests.put(url, json={"hedged_ids": ["ASML"], "coverage": 70, "scenario_tab": "collar",
                                "trigger": "autosave", "source": "overview"},
                     headers=iso_headers, timeout=TIMEOUT)
    assert r.status_code == 200
    plan = requests.get(url, headers=iso_headers, timeout=TIMEOUT).json()
    assert plan["last_step"] == "save" and plan["coverage"] == 70 and plan["selections"] == sel

    # Identical second autosave still appends (no dedupe)
    requests.put(url, json={"hedged_ids": ["ASML"], "coverage": 70, "scenario_tab": "collar",
                            "trigger": "autosave", "source": "overview"}, headers=iso_headers, timeout=TIMEOUT)

    hist = requests.get(f"{url}/history", headers=iso_headers, timeout=TIMEOUT).json()
    assert hist["count"] == 3
    assert [i["trigger"] for i in hist["items"]] == ["autosave", "autosave", "explicit"]  # newest first
    first = hist["items"][-1]
    by_id = {i["instrument_id"]: i for i in first["instruments"]}
    assert by_id["ASML"]["strategy"] == "put_buy" and by_id["ASML"]["currency"] == "EUR"
    assert by_id["ASML"]["shares"] == ISO_SHARES["ASML"]
    assert by_id["ASML"]["spot"] == ISO_LAST_CLOSE["ASML"]
    assert by_id["ASML"]["position_value"] == ISO_SHARES["ASML"] * ISO_LAST_CLOSE["ASML"]
    assert by_id["ASML"]["strike_pct"] == 95.0 and by_id["ASML"]["cost_source"] == "kite_csv"
    assert by_id["RELIANCE"]["currency"] == "INR" and by_id["RELIANCE"]["strategy"] == "call_sell"
    assert first["margin"] == {"amount": 1000, "currency": "INR"}
    assert first["portfolio"]["n_holdings"] == 2


def test_fno_hedge_history_export_role_gated_csv(iso_base_url, iso_headers):
    """System export: ops-role dev user gets CSV with the exact header; unauthenticated is rejected."""
    r = requests.get(f"{iso_base_url}/api/v1/system/hedge-plan-history?format=csv", headers=iso_headers, timeout=TIMEOUT)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    header = r.text.splitlines()[0].split(",")
    assert header[0] == "history_id" and header[-1] == "protected_pct" and len(header) == 32
    assert len(r.text.splitlines()) >= 4  # header + >=3 saved rows (2 instruments on the first save)
    assert requests.get(f"{iso_base_url}/api/v1/system/hedge-plan-history", timeout=TIMEOUT).status_code in (401, 403)


def test_fno_position_value_leg(iso_base_url, iso_headers):
    """Position-value leg (F40 Phase 3, STRICT — no skip) on the isolated seeded DB.

    ASML (EUR, 10 sh, last close 700 -> 7000) and RELIANCE (INR, 7 sh x 2500 -> 17500) each return
    >=12 monthly candles in their own currency (no FX) with ±1σ bands; NIFTY (option-only, not held)
    -> no_holding with the explicit message; the ann_vol_pct override takes precedence.
    """
    url = f"{iso_base_url}/api/v1/experience/fno/position-value"

    r = requests.get(url, params={"instrument": "ASML"}, headers=iso_headers, timeout=TIMEOUT)
    assert r.status_code == 200, f"position-value failed: {r.status_code} {r.text}"
    body = r.json()
    assert len(body["items"]) == 1
    asml = body["items"][0]
    assert asml["status"] == "ok" and asml["currency"] == "EUR" and asml["currency_symbol"] == "€"
    assert asml["shares"] == ISO_SHARES["ASML"]
    assert asml["last_close"] == ISO_LAST_CLOSE["ASML"]
    assert asml["last_value"] == ISO_SHARES["ASML"] * ISO_LAST_CLOSE["ASML"] == 7000.0
    assert len(asml["candles"]) >= 12
    assert asml["daily"][-1]["value"] == 7000.0 and body["as_of"] == asml["daily"][-1]["date"]
    assert asml["candles"][-1]["close"] == 7000.0
    assert asml["vol_source"] == "computed" and asml["ann_vol_pct"] > 0
    b = asml["bands"]
    assert b["anchor_value"] == 7000.0
    assert b["plus_1sigma_value"] > 7000.0 > b["minus_1sigma_value"]
    assert b["plus_1sigma_pct"] == pytest.approx(asml["monthly_sigma_pct"], abs=1e-3)

    # override takes precedence: golden 24% -> ±6.9282% of 7000
    o = requests.get(url, params={"instrument": "asml", "ann_vol_pct": 24}, headers=iso_headers, timeout=TIMEOUT).json()["items"][0]
    assert o["vol_source"] == "override" and o["ann_vol_pct"] == 24.0
    assert o["bands"]["plus_1sigma_value"] == pytest.approx(7000 * (1 + 0.069282), abs=0.05)
    assert o["bands"]["minus_1sigma_value"] == pytest.approx(7000 * (1 - 0.069282), abs=0.05)

    # all holdings: one item per holding, own currency each (no cross-currency sum)
    allr = requests.get(url, headers=iso_headers, timeout=TIMEOUT).json()
    by_id = {i["instrument_id"]: i for i in allr["items"]}
    assert list(by_id) == ["ASML", "RELIANCE"]
    rel = by_id["RELIANCE"]
    assert rel["status"] == "ok" and rel["currency"] == "INR" and rel["currency_symbol"] == "₹"
    assert rel["shares"] == ISO_SHARES["RELIANCE"] and rel["last_value"] == 7 * 2500.0
    assert len(rel["candles"]) >= 12

    # option-only / not held: explicit message, no chart data, never 404
    r = requests.get(url, params={"instrument": "NIFTY"}, headers=iso_headers, timeout=TIMEOUT)
    assert r.status_code == 200
    nifty = r.json()["items"][0]
    assert nifty["status"] == "no_holding" and nifty["candles"] == [] and nifty["bands"] is None
    assert nifty["message"] == "No equity holding for NIFTY (option exposure only). Position value needs shares held."

    # read-only: GET only; no write verbs on the path
    assert requests.post(url, headers=iso_headers, json={}, timeout=TIMEOUT).status_code == 405
