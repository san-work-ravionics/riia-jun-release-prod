"""F42 P1 — kite_middleware_client._request_ex reasons + fetch_* helpers (mocked httpx)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from rita.services import kite_middleware_client as kmc

_T = "rita.services.kite_middleware_client.httpx.request"


@pytest.fixture(autouse=True)
def _clear() -> None:
    kmc._reset_cache()


def _resp(status=200, body=None, bad_json=False):
    r = MagicMock()
    r.status_code = status
    if bad_json:
        r.json.side_effect = ValueError("x")
    else:
        r.json.return_value = body
    return r


def test_reason_unreachable():
    with patch(_T, side_effect=httpx.ConnectError("refused")):
        assert kmc._request_ex("GET", "http://x") == (None, "middleware_unreachable")


def test_reason_token_expired_401():
    with patch(_T, return_value=_resp(401, {})):
        assert kmc._request_ex("GET", "http://x") == (None, "token_expired")


def test_reason_token_expired_success_false():
    with patch(_T, return_value=_resp(200, {"success": False, "error": "TokenException: bad access_token"})):
        assert kmc._request_ex("GET", "http://x")[1] == "token_expired"


def test_reason_upstream_and_bad_response():
    with patch(_T, return_value=_resp(500, {})):
        assert kmc._request_ex("GET", "http://x")[1] == "upstream_error"
    with patch(_T, return_value=_resp(200, {"success": False, "error": "boom"})):
        assert kmc._request_ex("GET", "http://x")[1] == "upstream_error"
    with patch(_T, return_value=_resp(200, bad_json=True)):
        assert kmc._request_ex("GET", "http://x")[1] == "bad_response"
    with patch(_T, return_value=_resp(200, ["not-a-dict"])):
        assert kmc._request_ex("GET", "http://x")[1] == "bad_response"


def test_request_wrapper_still_returns_none_or_body():
    with patch(_T, return_value=_resp(401, {})):
        assert kmc._request("GET", "http://x") is None
    with patch(_T, return_value=_resp(200, {"success": True, "k": 1})):
        assert kmc._request("GET", "http://x") == {"success": True, "k": 1}


def test_fetch_live_trades_passes_snapshot_flag():
    with patch(_T, return_value=_resp(200, {"success": True, "data": []})) as m:
        res = kmc.fetch_live_trades(snapshot=False)
    assert res.body["success"] and res.reason is None
    assert m.call_args.kwargs["params"] == {"snapshot": "false"}
    assert m.call_args.args[1].endswith("/api/trades")


def test_fetch_live_down_returns_reason():
    with patch(_T, side_effect=httpx.ConnectError("x")):
        res = kmc.fetch_live_positions()
    assert res.body is None and res.reason == "middleware_unreachable"


_MASTER = {"success": True, "instruments": [
    {"name": "NIFTY", "tradingsymbol": "NIFTY25NOV24000CE", "expiry": "2026-11-24", "strike": 24000,
     "instrument_type": "CE", "lot_size": 65},
    {"name": "NIFTY", "tradingsymbol": "NIFTY25NOVFUT", "expiry": "2026-11-24", "strike": 0,
     "instrument_type": "FUT", "lot_size": 65},
    {"name": "RELIANCE", "tradingsymbol": "RELIANCE25NOV1500CE", "expiry": "2026-11-24", "strike": 1500,
     "instrument_type": "CE", "lot_size": 500},
    {"name": "BANKNIFTY", "tradingsymbol": "BAD", "expiry": "garbage", "strike": 1, "instrument_type": "PE"},
]}


def test_master_keeps_only_configured_option_rows_and_caches():
    with patch(_T, return_value=_resp(200, _MASTER)) as m:
        r1 = kmc.fetch_instrument_master_nfo()
        r2 = kmc.fetch_instrument_master_nfo()
    assert list(r1.body) == ["NIFTY25NOV24000CE"]
    assert r1.body["NIFTY25NOV24000CE"]["lot_size"] == 65
    assert r2.body is r1.body
    assert m.call_count == 1
    assert m.call_args.kwargs["timeout"] == 15.0


def test_master_failure_backoff_returns_same_reason():
    with patch(_T, return_value=_resp(401, {})) as m:
        a = kmc.fetch_instrument_master_nfo()
        b = kmc.fetch_instrument_master_nfo()
    assert a.reason == b.reason == "token_expired" and a.body is None
    assert m.call_count == 1
