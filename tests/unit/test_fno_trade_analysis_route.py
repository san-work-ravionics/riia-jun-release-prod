"""F42 P1 — GET /api/v1/experience/fno/trade-analysis/live route (client patched)."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from rita.schemas.fno_trade_analysis import TradeAnalysisLiveResponse
from rita.services.kite_middleware_client import ClientResult

_K = "rita.api.experience.fno_trade_analysis.kmc"
_URL = "/api/v1/experience/fno/trade-analysis/live"


@pytest.fixture(autouse=True)
def _auth(client):
    from rita.auth import get_current_user
    from rita.main import app

    u = MagicMock()
    u.id = "u-ta"
    app.dependency_overrides[get_current_user] = lambda: u
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _patched(**over):
    m = MagicMock()
    ok = lambda d: ClientResult({"success": True, "data": d})  # noqa: E731
    m.fetch_live_orders.return_value = over.get("orders", ok([]))
    m.fetch_live_trades.return_value = over.get("trades", ok([
        {"trade_id": "1", "tradingsymbol": "NIFTY25NOV24000CE", "exchange": "NFO",
         "transaction_type": "BUY", "quantity": 65, "average_price": 10.0}]))
    m.fetch_live_positions.return_value = over.get("positions", ok({"net": [], "day": []}))
    m.fetch_snapshot_status.return_value = ClientResult({"success": True, "days": [], "total_trades": 0})
    m.fetch_instrument_master_nfo.return_value = over.get("master", ClientResult({
        "NIFTY25NOV24000CE": {"name": "NIFTY", "expiry": date(2026, 11, 24), "strike": 24000.0,
                              "instrument_type": "CE", "lot_size": 65}}))
    return m


def test_route_ok_payload_has_every_schema_field(client):
    with patch(_K, _patched()):
        r = client.get(_URL)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == set(TradeAnalysisLiveResponse.model_fields)
    assert body["available"] and body["source"] == "kite" and body["trades"][0]["lots"] == 1.0


def test_route_always_200_when_middleware_down(client):
    down = ClientResult(None, "middleware_unreachable")
    with patch(_K, _patched(orders=down, trades=down, positions=down, master=down)):
        r = client.get(_URL)
    assert r.status_code == 200
    assert r.json()["available"] is False and r.json()["source"] == "fallback"


def test_route_token_expired(client):
    exp = ClientResult(None, "token_expired")
    with patch(_K, _patched(orders=exp, trades=exp, positions=exp)):
        r = client.get(_URL)
    assert r.json()["reason"] == "token_expired"


def test_route_params_validated(client):
    with patch(_K, _patched()):
        assert client.get(_URL, params={"underlying": "FINNIFTY"}).status_code == 422
        assert client.get(_URL, params={"expiry_month": 13}).status_code == 422
        assert client.get(_URL, params={"underlying": "NIFTY", "expiry_month": 11,
                                         "include_closed": "false"}).status_code == 200
