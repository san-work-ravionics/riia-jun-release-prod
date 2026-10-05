"""F42 P1 — fno_trade_analysis_service.build_live_payload (pure, synthetic data)."""
from __future__ import annotations

from datetime import date, datetime

from rita.services.fno_trade_analysis_service import build_live_payload
from rita.services.kite_middleware_client import ClientResult

NOW = datetime(2026, 10, 5, 12, 0, 0)
MASTER = {
    "NIFTY25NOV24000CE": {"name": "NIFTY", "expiry": date(2026, 11, 24), "strike": 24000.0,
                          "instrument_type": "CE", "lot_size": 65},
    "NIFTY25OCT24000PE": {"name": "NIFTY", "expiry": date(2026, 10, 27), "strike": 24000.0,
                          "instrument_type": "PE", "lot_size": 65},
    "NIFTY25AUG24000CE": {"name": "NIFTY", "expiry": date(2026, 8, 25), "strike": 24000.0,
                          "instrument_type": "CE", "lot_size": 65},
    "BANKNIFTY25NOV50000CE": {"name": "BANKNIFTY", "expiry": date(2026, 11, 24), "strike": 50000.0,
                              "instrument_type": "CE", "lot_size": None},
}
UNDS, MONTHS = ["NIFTY", "BANKNIFTY"], [9, 10, 11]


def _t(i, sym, side, qty, **kw):
    return {"trade_id": str(i), "order_id": "o" + str(i), "tradingsymbol": sym, "exchange": "NFO",
            "transaction_type": side, "quantity": qty, "average_price": 100.0,
            "fill_timestamp": "2026-10-05T10:00:00", **kw}


def _build(orders=None, trades=None, positions=None, master=None, snapshot=None, **kw):
    ok = lambda d: ClientResult({"success": True, "data": d})  # noqa: E731
    fail = ClientResult(None, "middleware_unreachable")
    return build_live_payload(
        orders=orders if isinstance(orders, ClientResult) else ok(orders or []),
        trades=trades if isinstance(trades, ClientResult) else ok(trades or []),
        positions=positions if isinstance(positions, ClientResult) else ok(positions or {"net": [], "day": []}),
        master=master if master is not None else ClientResult(MASTER),
        snapshot=snapshot if snapshot is not None else fail,
        underlyings=UNDS, expiry_months=MONTHS, now=NOW, **kw)


def test_all_legs_down_is_unavailable_fallback():
    down = ClientResult(None, "middleware_unreachable")
    r = _build(orders=down, trades=down, positions=down)
    assert (r.available, r.source, r.reason) == (False, "fallback", "middleware_unreachable")
    assert r.kpis is None and r.orders == r.trades == r.positions == []


def test_token_expired_wins_reason():
    r = _build(orders=ClientResult(None, "middleware_unreachable"), trades=ClientResult(None, "token_expired"),
               positions=ClientResult(None, "upstream_error"))
    assert r.reason == "token_expired"


def test_master_failure_no_hardcoded_fallback():
    r = _build(master=ClientResult(None, "upstream_error"), trades=[_t(1, "NIFTY25NOV24000CE", "BUY", 65)])
    assert r.available is False and r.reason == "upstream_error" and r.trades == []


def test_partial_failure_names_missing_leg():
    r = _build(orders=ClientResult(None, "upstream_error"), trades=[_t(1, "NIFTY25NOV24000CE", "BUY", 65)])
    assert r.available is True and "orders" in r.message and len(r.trades) == 1


def test_empty_day():
    r = _build()
    assert r.available and r.kpis.trades_count == 0 and r.kpis.lots_traded is None
    assert r.kpis.net_pnl == 0 and r.history_note and r.as_of_date == "2026-10-05"


def test_kpis_lots_round_trips_and_order_statuses():
    trades = [_t(1, "NIFTY25NOV24000CE", "BUY", 130), _t(2, "NIFTY25NOV24000CE", "SELL", 65)]
    orders = [{"tradingsymbol": "NIFTY25NOV24000CE", "status": s, "quantity": 65, "filled_quantity": 0,
               "pending_quantity": 65, "exchange": "NFO"}
              for s in ("COMPLETE", "REJECTED", "CANCELLED", "OPEN", "TRIGGER PENDING")]
    r = _build(orders=orders, trades=trades)
    k = r.kpis
    assert (k.orders_total, k.orders_complete, k.orders_rejected, k.orders_cancelled, k.orders_open) == (5, 1, 1, 1, 2)
    assert (k.buy_qty, k.sell_qty, k.trades_count) == (130, 65, 2)
    assert k.lots_traded == 3.0 and k.round_trips_today == 1
    assert r.orders[0].lots == 1.0 and r.orders[3].pending_quantity == 65


def test_lot_size_none_never_guessed():
    r = _build(trades=[_t(1, "BANKNIFTY25NOV50000CE", "BUY", 30)])
    assert r.trades[0].lot_size is None and r.trades[0].lots is None
    assert r.kpis.lots_traded is None and r.kpis.round_trips_today == 0


def test_exclusions_counted():
    trades = [
        _t(1, "NIFTY25AUG24000CE", "BUY", 65),            # out of window
        _t(2, "UNKNOWN25NOV1CE", "BUY", 1),               # unresolved
        _t(3, "NIFTY25NOVFUT", "BUY", 65),                # futures -> non_option
        _t(4, "RELIANCE", "BUY", 1, exchange="NSE"),      # equity -> non_option
        _t(5, "BANKNIFTY25NOV50000CE", "BUY", 30),        # other underlying when NIFTY selected
        _t(6, "NIFTY25NOV24000CE", "BUY", 65),
    ]
    r = _build(trades=trades, underlying="NIFTY")
    assert len(r.trades) == 1
    assert r.excluded.model_dump() == {"non_option": 2, "other_underlying": 1, "out_of_window": 1, "unresolved": 1}


def test_expiry_month_narrowing_and_outside_window_empty():
    trades = [_t(1, "NIFTY25NOV24000CE", "BUY", 65), _t(2, "NIFTY25OCT24000PE", "BUY", 65)]
    assert [t.tradingsymbol for t in _build(trades=trades, expiry_month=10).trades] == ["NIFTY25OCT24000PE"]
    r = _build(trades=trades, expiry_month=3)
    assert r.available and r.trades == [] and r.excluded.out_of_window == 0


def test_positions_flat_and_include_closed():
    pos = {"net": [
        {"tradingsymbol": "NIFTY25NOV24000CE", "quantity": -65, "pnl": 500.0, "realised": 0, "unrealised": 500.0,
         "exchange": "NFO", "average_price": 0},
        {"tradingsymbol": "NIFTY25OCT24000PE", "quantity": 0, "pnl": -200.0, "realised": -200.0,
         "unrealised": None, "exchange": "NFO"},
    ], "day": []}
    r = _build(positions=pos)
    assert [p.side for p in r.positions] == ["SHORT", "FLAT"]
    assert r.kpis.open_positions == 1 and r.kpis.realised_pnl == -200.0 and r.kpis.net_pnl == 300.0
    assert r.positions[0].lots == 1.0 and r.positions[1].unrealised is None
    r2 = _build(positions=pos, include_closed=False)
    assert [p.side for p in r2.positions] == ["SHORT"]
    assert r2.kpis.realised_pnl == -200.0 and r2.kpis.open_positions == 1


def test_by_expiry_and_snapshot():
    snap = ClientResult({"success": True, "days": [{}, {}], "first_date": "2026-10-01",
                         "last_date": "2026-10-05", "total_trades": 9})
    pos = {"net": [{"tradingsymbol": "NIFTY25NOV24000CE", "quantity": 65, "pnl": 10.0, "exchange": "NFO"}]}
    r = _build(trades=[_t(1, "NIFTY25NOV24000CE", "BUY", 65)], positions=pos, snapshot=snap)
    b = r.by_expiry[0]
    assert (b.underlying, b.expiry, b.trades, b.open_legs, b.net_quantity, b.pnl) == ("NIFTY", "2026-11-24", 1, 1, 65, 10.0)
    assert b.label == "NIFTY 24 Nov 2026"
    assert (r.snapshot.available, r.snapshot.days_captured, r.snapshot.total_trades) == (True, 2, 9)
    assert _build().snapshot.available is False


def test_failed_legs_give_null_kpis():
    down = ClientResult(None, "upstream_error")
    t = [_t(1, "NIFTY25NOV24000CE", "BUY", 65)]
    r = _build(positions=down, trades=t)
    k = r.kpis
    assert (k.net_pnl, k.realised_pnl, k.unrealised_pnl, k.open_positions) == (None,) * 4
    assert k.trades_count == 1 and k.orders_total == 0
    r = _build(trades=down)
    k = r.kpis
    assert (k.trades_count, k.buy_qty, k.sell_qty, k.lots_traded, k.round_trips_today) == (None,) * 5
    assert k.net_pnl == 0
    r = _build(orders=down, trades=t)
    k = r.kpis
    assert (k.orders_total, k.orders_complete, k.orders_rejected, k.orders_cancelled, k.orders_open) == (None,) * 5
    assert k.trades_count == 1
