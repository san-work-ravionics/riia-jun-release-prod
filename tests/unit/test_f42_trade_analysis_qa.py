"""F42 QA — additional edge-case, property and contract tests (synthetic data only)."""
from __future__ import annotations

import random
import re
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from rita.schemas.fno_trade_analysis import (
    ExcludedCounts, ExpirySummary, OrderRow, PositionRow, SnapshotInfo,
    TradeAnalysisLiveResponse, TradeKpis, TradeRow,
)
from rita.services import kite_middleware_client as kmc
from rita.services.fno_trade_analysis_service import build_live_payload
from rita.services.kite_middleware_client import ClientResult

NOW = datetime(2026, 10, 5, 12, 0, 0)
CE = "NIFTY26NOV24000CE"
BN = "BANKNIFTY26NOV50000CE"
NX = "NIFTYNXT5026NOV70000CE"


def _m(name, exp, typ="CE", lot=65, strike=24000.0):
    return {"name": name, "expiry": exp, "strike": strike, "instrument_type": typ, "lot_size": lot}


MASTER = {
    CE: _m("NIFTY", date(2026, 11, 24)),
    "NIFTY26OCT24000PE": _m("NIFTY", date(2026, 10, 27), "PE"),
    BN: _m("BANKNIFTY", date(2026, 11, 24), lot=30, strike=50000.0),
    NX: _m("NIFTYNXT50", date(2026, 11, 24), lot=25),
}


def _t(i, sym, side, qty, **kw):
    return {"trade_id": str(i), "tradingsymbol": sym, "exchange": "NFO", "transaction_type": side,
            "quantity": qty, "average_price": 10.0, **kw}


def _build(orders=None, trades=None, positions=None, master=None, snapshot=None, **kw):
    ok = lambda d: ClientResult({"success": True, "data": d})  # noqa: E731
    return build_live_payload(
        orders=orders if isinstance(orders, ClientResult) else ok(orders or []),
        trades=trades if isinstance(trades, ClientResult) else ok(trades or []),
        positions=positions if isinstance(positions, ClientResult) else ok(positions or {"net": []}),
        master=master if master is not None else ClientResult(MASTER),
        snapshot=snapshot if snapshot is not None else ClientResult(None, "middleware_unreachable"),
        underlyings=["NIFTY", "BANKNIFTY"], expiry_months=[9, 10, 11], now=NOW, **kw)


# ── name equality (no startswith) ──────────────────────────────────────────────
def test_underlying_match_is_equality_not_prefix():
    r = _build(trades=[_t(1, CE, "BUY", 65), _t(2, BN, "BUY", 30), _t(3, NX, "BUY", 25)], underlying="NIFTY")
    assert [t.tradingsymbol for t in r.trades] == [CE]
    assert r.excluded.other_underlying == 2
    r = _build(trades=[_t(1, CE, "BUY", 65), _t(2, BN, "BUY", 30)], underlying="BANKNIFTY")
    assert [t.tradingsymbol for t in r.trades] == [BN]
    assert r.trades[0].lot_size == 30  # lot size from master, not config


def test_all_underlyings_includes_both():
    r = _build(trades=[_t(1, CE, "BUY", 65), _t(2, BN, "BUY", 30)])
    assert {t.underlying for t in r.trades} == {"NIFTY", "BANKNIFTY"}


# ── partial fills / order statuses ─────────────────────────────────────────────
def test_partial_fill_order_and_trade_lots():
    o = [{"order_id": "a", "tradingsymbol": CE, "exchange": "NFO", "status": "OPEN", "quantity": 130,
          "filled_quantity": 65, "pending_quantity": 65, "transaction_type": "BUY"}]
    r = _build(orders=o, trades=[_t(1, CE, "BUY", 65)])
    assert r.orders[0].lots == 2.0 and r.orders[0].pending_quantity == 65
    assert r.trades[0].lots == 1.0
    assert r.kpis.orders_open == 1 and r.kpis.orders_complete == 0


def test_status_case_and_unknown_status_counts_open():
    o = [{"tradingsymbol": CE, "status": "complete", "quantity": 65},
         {"tradingsymbol": CE, "status": "AMO REQ RECEIVED", "quantity": 65},
         {"tradingsymbol": CE, "status": None, "quantity": 65}]
    k = _build(orders=o).kpis
    assert k.orders_total == 3 and k.orders_complete == 1 and k.orders_open == 2


# ── null / odd fields ──────────────────────────────────────────────────────────
def test_null_and_odd_fields_do_not_raise():
    trades = [{"tradingsymbol": CE, "exchange": "NFO", "transaction_type": None, "quantity": None,
               "average_price": 0, "fill_timestamp": None, "trade_id": None},
              {"tradingsymbol": CE, "quantity": "abc", "average_price": "x"},
              {"tradingsymbol": None, "quantity": 5},
              {"tradingsymbol": CE, "quantity": True}]
    pos = {"net": [{"tradingsymbol": CE, "quantity": None, "pnl": None, "m2m": "bad", "average_price": 0}]}
    orders = [{"tradingsymbol": CE, "quantity": None, "filled_quantity": "n/a", "order_timestamp": None}]
    r = _build(orders=orders, trades=trades, positions=pos)
    assert r.available
    assert r.trades[0].quantity is None and r.trades[0].lots is None and r.trades[0].average_price == 0.0
    assert r.trades[1].quantity is None and r.trades[1].average_price is None
    assert r.excluded.unresolved == 1  # the None-symbol row
    assert r.positions[0].side == "FLAT" and r.positions[0].pnl is None and r.positions[0].m2m is None
    assert r.orders[0].lots is None and r.orders[0].filled_quantity is None
    assert r.kpis.net_pnl == 0.0
    # schema round-trips (this is what FastAPI serialises)
    TradeAnalysisLiveResponse.model_validate(r.model_dump())


def test_data_none_and_missing_keys_treated_as_empty():
    r = _build(orders=ClientResult({"success": True, "data": None}),
               trades=ClientResult({"success": True}),
               positions=ClientResult({"success": True, "data": None}))
    assert r.available and r.kpis.trades_count == 0 and r.kpis.open_positions == 0


def test_master_lot_size_none_row_still_listed_but_no_lots():
    m = {**MASTER, BN: _m("BANKNIFTY", date(2026, 11, 24), lot=None)}
    r = _build(trades=[_t(1, BN, "BUY", 30)], master=ClientResult(m))
    assert len(r.trades) == 1 and r.trades[0].lots is None and r.kpis.lots_traded is None


# ── snapshot failure never affects payload ─────────────────────────────────────
@pytest.mark.parametrize("snap", [ClientResult(None, "upstream_error"), ClientResult(None, "middleware_unreachable"),
                                  ClientResult({"success": True, "days": None, "total_trades": None})])
def test_snapshot_failure_does_not_change_payload(snap):
    trades = [_t(1, CE, "BUY", 65)]
    good = _build(trades=trades, snapshot=ClientResult({"success": True, "days": [], "total_trades": 0}))
    r = _build(trades=trades, snapshot=snap)
    assert r.available and r.message is None
    assert r.trades == good.trades and r.kpis == good.kpis
    assert r.snapshot.days_captured == 0


# ── token expired via success:false path propagated to payload ─────────────────
def test_all_legs_token_expired_reason_in_payload():
    x = ClientResult(None, "token_expired")
    r = _build(orders=x, trades=x, positions=x)
    assert (r.available, r.reason, r.kpis) == (False, "token_expired", None)


def test_master_failure_reason_propagates_even_if_legs_ok():
    r = _build(master=ClientResult(None, "token_expired"), trades=[_t(1, CE, "BUY", 65)])
    assert r.available is False and r.reason == "token_expired" and r.kpis is None


# ── include_closed ─────────────────────────────────────────────────────────────
def test_include_closed_false_only_filters_positions_not_by_expiry_or_kpis():
    pos = {"net": [{"tradingsymbol": CE, "quantity": 0, "pnl": 40.0, "realised": 40.0, "unrealised": 0.0}]}
    on = _build(positions=pos, include_closed=True)
    off = _build(positions=pos, include_closed=False)
    assert len(on.positions) == 1 and off.positions == []
    assert off.kpis == on.kpis and off.by_expiry == on.by_expiry
    assert off.kpis.realised_pnl == 40.0 and off.kpis.open_positions == 0


# ── semantics property test (seeded, no external dependency) ───────────────────
def _reference(trades, lot):
    buy = sum(q for s, q in trades if s == "BUY")
    sell = sum(q for s, q in trades if s == "SELL")
    return buy, sell, sum(q for _, q in trades) / lot, min(buy, sell) // lot


@pytest.mark.parametrize("seed", range(40))
def test_round_trips_and_lots_traded_semantics(seed):
    rng = random.Random(seed)
    lot = 65
    raw = [(rng.choice(["BUY", "SELL"]), lot * rng.randint(1, 6)) for _ in range(rng.randint(0, 12))]
    r = _build(trades=[_t(i, CE, s, q) for i, (s, q) in enumerate(raw)])
    buy, sell, lots, rt = _reference(raw, lot)
    k = r.kpis
    assert (k.buy_qty, k.sell_qty) == (buy, sell)
    assert k.round_trips_today == rt
    assert k.lots_traded == (round(lots, 2) if raw else None)
    # invariants
    assert k.round_trips_today * lot <= min(buy, sell)
    assert k.lots_traded is None or k.lots_traded >= k.round_trips_today * 2
    assert k.trades_count == len(raw)


def test_round_trips_summed_per_symbol_not_netted_across_symbols():
    # buy on one symbol, sell on another: no round trip
    r = _build(trades=[_t(1, CE, "BUY", 65), _t(2, "NIFTY26OCT24000PE", "SELL", 65)])
    assert r.kpis.round_trips_today == 0 and r.kpis.lots_traded == 2.0


def test_round_trips_floor_with_partial_lot():
    r = _build(trades=[_t(1, CE, "BUY", 100), _t(2, CE, "SELL", 100)])  # odd qty: floor(100/65)=1
    assert r.kpis.round_trips_today == 1


# ── client: extra edges ────────────────────────────────────────────────────────
_T = "rita.services.kite_middleware_client.httpx.request"


def _resp(status=200, body=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    return r


@pytest.fixture
def _clear():
    kmc._reset_cache()
    yield
    kmc._reset_cache()


def test_live_helper_never_raises_on_unexpected_exception(_clear):
    with patch(_T, side_effect=RuntimeError("weird")):
        assert kmc.fetch_live_orders() == ClientResult(None, "middleware_unreachable")


def test_timeout_is_unreachable(_clear):
    with patch(_T, side_effect=httpx.ReadTimeout("slow")):
        assert kmc.fetch_live_trades().reason == "middleware_unreachable"


def test_snapshot_status_path(_clear):
    with patch(_T, return_value=_resp(200, {"success": True, "days": []})) as m:
        assert kmc.fetch_snapshot_status().body["success"]
    assert m.call_args.args[1].endswith("/api/snapshot/status")


def test_master_odd_rows_lot_size_none_and_failure_not_cached_as_success(_clear):
    body = {"success": True, "instruments": [
        {"name": "NIFTY", "tradingsymbol": "A", "expiry": "2026-11-24", "strike": 1, "instrument_type": "CE", "lot_size": 0},
        {"name": "NIFTY", "tradingsymbol": "B", "expiry": "2026-11-24", "strike": 1, "instrument_type": "PE", "lot_size": True},
        {"name": "NIFTY", "tradingsymbol": "C", "expiry": "2026-11-24", "strike": 1, "instrument_type": "PE", "lot_size": "75"},
        {"name": "NIFTYNXT50", "tradingsymbol": "D", "expiry": "2026-11-24", "strike": 1, "instrument_type": "CE", "lot_size": 25},
        {"name": "NIFTY", "tradingsymbol": "", "expiry": "2026-11-24", "strike": 1, "instrument_type": "CE", "lot_size": 65},
        "junk",
    ]}
    with patch(_T, return_value=_resp(200, body)):
        res = kmc.fetch_instrument_master_nfo()
    assert set(res.body) == {"A", "B", "C"}  # D excluded: name equality; '' and junk skipped
    assert all(v["lot_size"] is None for v in res.body.values())  # never guessed


def test_master_unreachable_then_backoff_no_extra_call(_clear):
    with patch(_T, side_effect=httpx.ConnectError("x")) as m:
        a = kmc.fetch_instrument_master_nfo()
        b = kmc.fetch_instrument_master_nfo()
    assert a.reason == b.reason == "middleware_unreachable" and m.call_count == 1


# ── route extras ───────────────────────────────────────────────────────────────
_K = "rita.api.experience.fno_trade_analysis.kmc"
_URL = "/api/v1/experience/fno/trade-analysis/live"


@pytest.fixture
def _auth(client):
    from rita.auth import get_current_user
    from rita.main import app
    app.dependency_overrides[get_current_user] = lambda: MagicMock(id="u-qa")
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _kmc_mock(**over):
    m = MagicMock()
    ok = lambda d: ClientResult({"success": True, "data": d})  # noqa: E731
    m.fetch_live_orders.return_value = over.get("orders", ok([]))
    m.fetch_live_trades.return_value = over.get("trades", ok([]))
    m.fetch_live_positions.return_value = over.get("positions", ok({"net": []}))
    m.fetch_snapshot_status.return_value = over.get("snap", ClientResult(None, "upstream_error"))
    m.fetch_instrument_master_nfo.return_value = over.get("master", ClientResult(MASTER))
    return m


def test_route_empty_day_and_filters_echoed(client, _auth):
    with patch(_K, _kmc_mock()):
        b = client.get(_URL, params={"underlying": "NIFTY", "expiry_month": 3}).json()
    assert b["available"] and b["trades"] == [] and b["kpis"]["trades_count"] == 0
    assert b["filter"]["underlying"] == "NIFTY" and b["filter"]["expiry_months"] == [9, 10, 11]
    assert b["history_note"]


def test_route_snapshot_leg_failure_keeps_available(client, _auth):
    trades = ClientResult({"success": True, "data": [_t(1, CE, "BUY", 65)]})
    with patch(_K, _kmc_mock(trades=trades)):
        b = client.get(_URL).json()
    assert b["available"] and b["snapshot"]["available"] is False and len(b["trades"]) == 1


def test_route_master_failure_unavailable_200(client, _auth):
    with patch(_K, _kmc_mock(master=ClientResult(None, "upstream_error"))):
        r = client.get(_URL)
    assert r.status_code == 200 and r.json()["available"] is False and r.json()["reason"] == "upstream_error"


def test_route_requests_snapshot_true_from_middleware(client, _auth):
    m = _kmc_mock()
    with patch(_K, m):
        client.get(_URL)
    m.fetch_live_trades.assert_called_once_with(snapshot=True)


def test_route_requires_auth(client):
    from rita.main import app
    app.dependency_overrides.clear()
    r = client.get(_URL)
    assert r.status_code in (401, 403)


# ── static contract extras ─────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2] / "dashboard"
JS = (ROOT / "js/fno/trade-analysis.js").read_text()
HTML = (ROOT / "fno.html").read_text()
SRC = Path(__file__).resolve().parents[2] / "src/rita"


def test_js_never_calls_tofixed_and_escapes_text():
    assert ".toFixed(" not in JS
    assert "&lt;" in JS and "_esc(o.tradingsymbol)" in JS


def test_table_header_counts_match_js_row_cells():
    expected = {"ta-expiry-body": 6, "ta-orders-body": 16, "ta-trades-body": 13, "ta-positions-body": 16}
    for tid, n in expected.items():
        assert re.search(rf"_fill\('{tid}'.*?\)\), {n}, ", JS, re.S), tid
        i = HTML.index(f'id="{tid}"')
        head = HTML[HTML.rfind("<thead>", 0, i):i]
        assert len(re.findall(r"<th[ >]", head)) == n, tid


def test_every_ta_dom_id_in_html_is_unique():
    ids = re.findall(r'id="(ta-[a-z-]+)"', HTML)
    assert len(ids) == len(set(ids)) and len(ids) >= 25


def test_every_schema_field_is_consumed_or_documented():
    """Schema fields the JS never reads are listed here so a new unread field is a conscious choice."""
    reads = set(re.findall(r"(?<![\w.])(?:data|k|v|o|t|p|b|s|x)\.([a-z_0-9]+)", JS))
    # known, deliberate: header-only / not displayed in P1 (buy/sell qty feed P3 analytics)
    allowed_unread = {"source", "fetched_at", "filter", "buy_qty", "sell_qty"}
    for model in (TradeAnalysisLiveResponse, TradeKpis, OrderRow, TradeRow, PositionRow, ExpirySummary,
                  SnapshotInfo, ExcludedCounts):
        unread = set(model.model_fields) - reads
        # fields not read by any prefix at all
        assert unread <= allowed_unread, (model.__name__, unread)


def test_no_io_or_commit_in_route_and_service():
    for f in ("api/experience/fno_trade_analysis.py", "services/fno_trade_analysis_service.py"):
        import ast
        tree = ast.parse((SRC / f).read_text())
        for n in ast.walk(tree):  # drop docstrings
            if isinstance(n, (ast.Module, ast.FunctionDef)) and ast.get_docstring(n):
                n.body = n.body[1:]
        s = ast.unparse(tree)
        for banned in (".commit(", "open(", "Session", "Repository", "print(", "httpx", "kiteconnect"):
            assert banned not in s, (f, banned)


def test_main_registers_router_once():
    s = (SRC / "main.py").read_text()
    assert s.count("fno_trade_analysis") >= 2 and s.count("include_router(fno_trade_analysis_router)") == 1
