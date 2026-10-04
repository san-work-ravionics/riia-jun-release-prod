"""portfolio-hedge cost_pct source order: live Kite -> deployed snapshot CSV -> model estimate.

Only India F&O names / NIFTY / BANKNIFTY are looked up; others always stay 'estimated'.
Repos and the two Kite lookups are patched — no network, no seeded data.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

_P = "rita.api.experience.portfolio_hedge"


@pytest.fixture(autouse=True)
def _auth(client, db_session):
    from rita.auth import get_current_user
    from rita.main import app

    user = MagicMock()
    user.id = "u1"
    app.dependency_overrides[get_current_user] = lambda: user
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _get(client, *, live, snap):
    pf = MagicMock()
    pf.holdings = [{"instrument_id": "RELIANCE", "allocation_pct": 60.0}, {"instrument_id": "NVIDIA", "allocation_pct": 40.0}]
    pf.total_value_eur = None
    with patch(f"{_P}.UserPortfolioKeyRepo") as k, patch(f"{_P}.UserPortfolioRepo") as p, \
         patch(f"{_P}.MarketDataCacheRepository") as m, \
         patch(f"{_P}.fetch_put_premium", return_value=live) as fl, \
         patch(f"{_P}.put_premium_from_csv", return_value=snap) as fc:
        k.return_value.find_by_user_id.return_value = MagicMock(key_id="k")
        p.return_value.find_active_by_key_id.return_value = pf
        m.return_value.read_all.return_value = []
        resp = client.get("/api/v1/experience/fno/portfolio-hedge?coverage=50")
    assert resp.status_code == 200, resp.text
    return {h["instrument_id"]: h for h in resp.json()["holdings"]}, fl, fc


def test_live_kite_wins_and_csv_not_consulted(client):
    h, _, fc = _get(client, live={"cost_pct": 0.9, "detail": "live"}, snap={"cost_pct": 1.1, "detail": "csv"})
    assert h["RELIANCE"]["cost_source"] == "kite" and h["RELIANCE"]["cost_pct"] == 0.9
    fc.assert_not_called()


def test_csv_snapshot_used_when_live_unavailable(client):
    h, _, _ = _get(client, live=None, snap={"cost_pct": 1.1, "detail": "Zerodha snapshot 2026-10-04"})
    assert h["RELIANCE"]["cost_source"] == "kite_csv" and h["RELIANCE"]["cost_pct"] == 1.1
    assert "snapshot" in h["RELIANCE"]["cost_detail"]


def test_estimate_when_neither_and_non_india_never_looked_up(client):
    h, fl, _ = _get(client, live=None, snap=None)
    assert h["RELIANCE"]["cost_source"] == "estimated" and h["RELIANCE"]["cost_detail"] is None
    assert h["NVIDIA"]["cost_source"] == "estimated"
    assert [c.args[0] for c in fl.call_args_list] == ["RELIANCE"]  # NVIDIA (US) not looked up
