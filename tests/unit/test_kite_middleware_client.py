"""Unit tests — F39 Phase 3: kite_middleware_client.fetch_kite_quote against the real
fno-margin-fetch routes (GET /api/instruments, POST /api/quotes).

Mocked HTTP only (httpx.request) — NOT live integration tests against a running
fno-margin-fetch. All failure modes (connect, timeout, 401, 500, bad JSON,
success:false) go through one fallback path and return None; the client never raises.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from rita.services import kite_middleware_client as kmc
from rita.services.kite_middleware_client import fetch_kite_quote

_PATCH_TARGET = "rita.services.kite_middleware_client.httpx.request"


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    kmc._reset_cache()


def _resp(status: int = 200, body: object = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    return r


def _instruments(*lots: int, name: str = "NIFTY") -> dict:
    return {
        "success": True,
        "instruments": [{"name": name, "lot_size": n} for n in lots],
    }


def _quote(key: str = "NSE:NIFTY 50") -> dict:
    return {
        "success": True,
        "data": {
            key: {
                "last_price": 24100.5,
                "depth": {"buy": [{"price": 24100.0}], "sell": [{"price": 24101.0}]},
            }
        },
    }


def _router(instruments: MagicMock, quotes: MagicMock):
    def _side_effect(method, url, **kwargs):
        return instruments if url.endswith("/api/instruments") else quotes

    return _side_effect


def test_connection_refused_returns_none() -> None:
    with patch(_PATCH_TARGET, side_effect=httpx.ConnectError("refused")):
        assert fetch_kite_quote("NIFTY") is None


def test_timeout_returns_none() -> None:
    with patch(_PATCH_TARGET, side_effect=httpx.TimeoutException("timed out")):
        assert fetch_kite_quote("NIFTY") is None


def test_401_returns_none() -> None:
    with patch(_PATCH_TARGET, return_value=_resp(401)):
        assert fetch_kite_quote("NIFTY") is None


def test_500_returns_none() -> None:
    with patch(_PATCH_TARGET, return_value=_resp(500)):
        assert fetch_kite_quote("NIFTY") is None


def test_bad_json_returns_none() -> None:
    r = _resp(200)
    r.json.side_effect = ValueError("not json")
    with patch(_PATCH_TARGET, return_value=r):
        assert fetch_kite_quote("NIFTY") is None


def test_success_false_returns_none() -> None:
    with patch(_PATCH_TARGET, return_value=_resp(200, {"success": False, "error": "token"})):
        assert fetch_kite_quote("NIFTY") is None


def test_success_maps_lot_size_and_quote_and_never_margin() -> None:
    side = _router(_resp(200, _instruments(75, 75)), _resp(200, _quote()))
    with patch(_PATCH_TARGET, side_effect=side) as mock_req:
        result = fetch_kite_quote("NIFTY", strike=24000, option_type="CE", quantity=75)
    assert result == {"lot_size": 75, "ltp": 24100.5, "bid": 24100.0, "ask": 24101.0}
    assert "required" not in result and "span" not in result
    calls = {c.args[1].rsplit("/api/", 1)[1]: c for c in mock_req.call_args_list}
    assert calls["instruments"].kwargs["params"]["exchange"] == "NFO"
    assert calls["instruments"].kwargs["params"]["limit"] > 100
    assert calls["quotes"].kwargs["json"] == {"instruments": ["NSE:NIFTY 50"]}


def test_equity_symbol_uses_plain_nse_key() -> None:
    side = _router(
        _resp(200, _instruments(300, name="RELIANCE")),
        _resp(200, _quote("NSE:RELIANCE")),
    )
    with patch(_PATCH_TARGET, side_effect=side):
        result = fetch_kite_quote("RELIANCE")
    assert result["lot_size"] == 300 and result["ltp"] == 24100.5


def test_ambiguous_lot_size_is_unavailable_but_quote_still_returned() -> None:
    side = _router(_resp(200, _instruments(75, 50)), _resp(200, _quote()))
    with patch(_PATCH_TARGET, side_effect=side):
        result = fetch_kite_quote("NIFTY")
    assert result["lot_size"] is None
    assert result["ltp"] == 24100.5


def test_unknown_instrument_and_failed_quote_returns_none() -> None:
    side = _router(_resp(200, _instruments(75, name="OTHER")), _resp(200, {"success": False}))
    with patch(_PATCH_TARGET, side_effect=side):
        assert fetch_kite_quote("ASML") is None


def test_lot_size_is_cached_between_calls() -> None:
    side = _router(_resp(200, _instruments(75)), _resp(200, _quote()))
    with patch(_PATCH_TARGET, side_effect=side) as mock_req:
        fetch_kite_quote("NIFTY")
        fetch_kite_quote("NIFTY")
    urls = [c.args[1] for c in mock_req.call_args_list]
    assert sum(u.endswith("/api/instruments") for u in urls) == 1
