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


# ── fetch_put_premium: real hedge cost from Kite option quotes ─────────────────

from datetime import date  # noqa: E402

from rita.services.kite_middleware_client import fetch_put_premium  # noqa: E402

_TODAY = date(2026, 10, 4)


def _pe(name: str, expiry: str, strike: float) -> dict:
    sym = f"{name}{expiry.replace('-', '')}{int(strike)}PE"
    return {"name": name, "instrument_type": "PE", "expiry": expiry, "strike": strike, "tradingsymbol": sym}


def _master() -> dict:
    return {"success": True, "instruments": [
        _pe("RELIANCE", "2026-10-27", 2400), _pe("RELIANCE", "2026-10-27", 2300),
        _pe("RELIANCE", "2026-10-13", 2400),  # too near: ignored (< 20 days)
        _pe("RELIANCE", "2026-11-24", 2400),
        {"name": "RELIANCE", "instrument_type": "CE", "expiry": "2026-10-27", "strike": 2400, "tradingsymbol": "X"},
    ]}


def _quotes(req_json: dict) -> dict:
    data = {}
    for k in req_json["instruments"]:
        if k == "NSE:RELIANCE":
            data[k] = {"last_price": 2500.0}
        elif k.endswith("2400PE"):
            data[k] = {"last_price": 30.0, "depth": {"buy": [{"price": 29.0}], "sell": [{"price": 31.0}]}}
        elif k.endswith("2300PE"):
            data[k] = {"last_price": 12.0, "depth": {"buy": [{"price": 11.0}], "sell": [{"price": 13.0}]}}
    return {"success": True, "data": data}


def _put_router(url, **kw):
    if url.endswith("/api/instruments"):
        return _resp(200, _master())
    return _resp(200, _quotes(kw["json"]))


def test_put_premium_uses_ask_nearest_strike_and_monthly_expiry() -> None:
    with patch(_PATCH_TARGET, side_effect=lambda m, u, **kw: _put_router(u, **kw)) as req:
        out = fetch_put_premium("RELIANCE", -4.0, today=_TODAY)  # 2500*0.96 = 2400
    assert out is not None
    assert out["cost_pct"] == pytest.approx(31.0 / 2500.0 * 100, abs=1e-3)  # best ask / spot
    assert out["expiry"] == "2026-10-27" and "RELIANCE20261027" in out["detail"]
    assert req.called


def test_put_spread_premium_is_buy_ask_minus_sell_bid() -> None:
    with patch(_PATCH_TARGET, side_effect=lambda m, u, **kw: _put_router(u, **kw)):
        out = fetch_put_premium("RELIANCE", -4.0, spread_width_pct=4.0, today=_TODAY)  # 2400 / 2300
    assert out is not None
    assert out["cost_pct"] == pytest.approx((31.0 - 11.0) / 2500.0 * 100, abs=1e-3)


def test_put_premium_none_when_middleware_down_and_backs_off() -> None:
    with patch(_PATCH_TARGET, side_effect=httpx.ConnectError("refused")) as req:
        assert fetch_put_premium("RELIANCE", -4.0, today=_TODAY) is None
        assert fetch_put_premium("INFY", -4.0, today=_TODAY) is None
    assert req.call_count == 1  # second call short-circuits on the failure back-off


def test_put_premium_none_for_unknown_underlying_or_missing_quote() -> None:
    with patch(_PATCH_TARGET, side_effect=lambda m, u, **kw: _put_router(u, **kw)):
        assert fetch_put_premium("NOSUCH", -4.0, today=_TODAY) is None
    def no_opt_quote(m, u, **kw):
        if u.endswith("/api/instruments"):
            return _resp(200, _master())
        return _resp(200, {"success": True, "data": {k: {"last_price": 2500.0} for k in kw["json"]["instruments"] if k.startswith("NSE:")}})
    kmc._reset_cache()
    with patch(_PATCH_TARGET, side_effect=no_opt_quote):
        assert fetch_put_premium("RELIANCE", -4.0, today=_TODAY) is None


# ── CSV snapshot flow: fetch_put_chain -> write_put_csv -> put_premium_from_csv ─

from rita.services.kite_middleware_client import (  # noqa: E402
    fetch_put_chain,
    put_premium_from_csv,
    write_put_csv,
)


def _chain_master() -> dict:
    return {"success": True, "instruments": [
        _pe("RELIANCE", "2026-10-27", 2400), _pe("RELIANCE", "2026-10-27", 2300),
        _pe("RELIANCE", "2026-10-27", 1000),  # outside the 80-100% band: dropped
    ]}


def _chain_router(url, **kw):
    if url.endswith("/api/instruments"):
        return _resp(200, _chain_master())
    return _resp(200, _quotes(kw["json"]))


def test_chain_to_csv_to_premium_round_trip(tmp_path) -> None:
    with patch(_PATCH_TARGET, side_effect=lambda m, u, **kw: _chain_router(u, **kw)):
        rows = fetch_put_chain("RELIANCE", today=_TODAY)
    assert rows and {r["strike"] for r in rows} == {2400, 2300} and rows[0]["spot"] == 2500.0
    f = tmp_path / "kite" / "put_premiums.csv"
    write_put_csv(f, rows)
    one = put_premium_from_csv("RELIANCE", -4.0, path=f, today=_TODAY)
    assert one and one["cost_pct"] == pytest.approx(31.0 / 2500.0 * 100, abs=1e-3) and one["as_of"] == "2026-10-04"
    assert "snapshot 2026-10-04" in one["detail"]
    spread = put_premium_from_csv("RELIANCE", -4.0, spread_width_pct=4.0, path=f, today=_TODAY)
    assert spread and spread["cost_pct"] == pytest.approx((31.0 - 11.0) / 2500.0 * 100, abs=1e-3)


def test_csv_premium_none_when_stale_expired_missing_or_unknown(tmp_path) -> None:
    f = tmp_path / "put_premiums.csv"
    assert put_premium_from_csv("RELIANCE", -4.0, path=f, today=_TODAY) is None  # no file
    with patch(_PATCH_TARGET, side_effect=lambda m, u, **kw: _chain_router(u, **kw)):
        write_put_csv(f, fetch_put_chain("RELIANCE", today=_TODAY))
    assert put_premium_from_csv("INFY", -4.0, path=f, today=_TODAY) is None       # unknown instrument
    assert put_premium_from_csv("RELIANCE", -4.0, path=f, today=date(2026, 10, 20)) is None  # 16d old
    assert put_premium_from_csv("RELIANCE", -4.0, path=f, today=date(2026, 10, 28)) is None  # expired

