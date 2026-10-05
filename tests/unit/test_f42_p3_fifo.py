"""F42 P3 — FIFO engine: hand-computable synthetic cases."""
from __future__ import annotations

import random

from rita.services.fno_trade_fifo import build_closed_trades, run_fifo, sweep_positions
from tests.unit.f42_p3_helpers import D, fifo, fill, spot


def test_long_round_trip_pnl_and_holding():
    r = fifo([fill("buy", 100, 10.0, "2026-10-01", "10:00"), fill("sell", 100, 12.5, "2026-10-01", "10:31")])
    assert len(r.segments) == 1
    s = r.segments[0]
    assert s.pnl == 250.0 and s.side == 1 and s.same_day and s.holding_minutes == 31.0
    assert r.open_lots(True) == []


def test_short_round_trip_pnl():
    r = fifo([fill("sell", 50, 20.0, "2026-10-01"), fill("buy", 50, 15.0, "2026-10-02", "11:00")])
    s = r.segments[0]
    assert s.side == -1 and s.pnl == 250.0 and not s.same_day and s.holding_days == 1


def test_partial_close_keeps_remainder_entry_price():
    r = fifo([fill("buy", 100, 10.0, "2026-10-01"), fill("sell", 40, 11.0, "2026-10-01", "11:00")])
    assert r.segments[0].qty == 40
    lot = r.residual_lots[0]
    assert lot.qty == 60 and lot.avg_entry == 10.0 and lot.open_date == D("2026-10-01")
    assert r.events[1].cls == "scale_out"


def test_multi_lot_oldest_first():
    r = fifo([fill("buy", 50, 10.0, "2026-10-01"), fill("buy", 50, 20.0, "2026-10-02"),
              fill("sell", 70, 30.0, "2026-10-03")])
    assert [(s.qty, s.entry_px, s.pnl) for s in r.segments] == [(50, 10.0, 1000.0), (20, 20.0, 200.0)]
    assert r.residual_lots[0].qty == 30 and r.residual_lots[0].avg_entry == 20.0
    ct = build_closed_trades(r.segments)
    assert len(ct) == 1 and ct[0].pnl == 1200.0 and ct[0].qty == 70


def test_flip_through_zero_in_one_fill():
    r = fifo([fill("buy", 100, 10.0, "2026-10-01"), fill("sell", 150, 14.0, "2026-10-02")])
    assert r.segments[0].pnl == 400.0
    lot = r.residual_lots[0]
    assert lot.side == -1 and lot.qty == 50 and lot.avg_entry == 14.0
    assert r.events[1].cls == "flip" and r.events[1].closed_qty == 100 and r.events[1].opened_qty == 50


def test_adverse_add_long_below_and_short_above_average():
    r = fifo([fill("buy", 50, 20.0, "2026-10-01"), fill("buy", 50, 15.0, "2026-10-02"),
              fill("sell", 50, 30.0, "2026-10-03", symbol="NIFTY26OCT24100PE", itype="PE", strike=24100.0),
              fill("sell", 50, 25.0, "2026-10-04", symbol="NIFTY26OCT24100PE", itype="PE", strike=24100.0)])
    ev = r.events
    assert ev[1].adverse_add is True
    assert ev[2].adverse_add is False  # first fill of the PE symbol opens it
    assert ev[3].adverse_add is False  # short added below the 30 average: position was in profit, not a loser


def test_adverse_add_short_above_average():
    r = fifo([fill("sell", 50, 30.0, "2026-10-01"), fill("sell", 50, 40.0, "2026-10-02")])
    assert r.events[1].adverse_add is True


def test_same_day_churn_flag_and_tie_break_determinism():
    fs = [fill("buy", 10, 10.0, "2026-10-01", None, oid="A", tid="1"),
          fill("sell", 10, 11.0, "2026-10-01", None, oid="B", tid="2"),
          fill("buy", 10, 10.0, "2026-10-02", None, oid="C", tid="3"),
          fill("sell", 10, 9.0, "2026-10-02", None, oid="D", tid="4")]
    base = [(s.entry_px, s.exit_px) for s in fifo(fs).segments]
    for seed in range(5):
        sh = fs[:]
        random.Random(seed).shuffle(sh)
        assert [(s.entry_px, s.exit_px) for s in fifo(sh).segments] == base
    assert all(s.same_day for s in fifo(fs).segments)


def test_expiry_estimate_worthless_short_and_intrinsic_both_sides():
    sp = spot(NIFTY=[("2026-10-27", 23800.0)])
    r = fifo([
        fill("sell", 100, 50.0, "2026-10-01"),                                    # CE 24000 -> worthless
        fill("buy", 100, 100.0, "2026-10-01", symbol="NIFTY26OCT23900PE", itype="PE", strike=23900.0),  # PE 23900 -> 100 intrinsic
        fill("sell", 10, 200.0, "2026-10-01", symbol="NIFTY26OCT23500CE", itype="CE", strike=23500.0),  # CE 23500 -> 300 intrinsic
    ], as_of="2026-10-29", sp=sp)
    est = {s.symbol: s for s in r.est_segments}
    assert est["NIFTY26OCT24000CE"].exit_px == 0.0 and est["NIFTY26OCT24000CE"].pnl == 5000.0
    assert est["NIFTY26OCT23900PE"].exit_px == 100.0 and est["NIFTY26OCT23900PE"].pnl == 0.0
    assert est["NIFTY26OCT23500CE"].exit_px == 300.0 and est["NIFTY26OCT23500CE"].pnl == -1000.0
    assert all(s.estimated and s.close_kind == "expiry_est" for s in r.est_segments)
    assert r.segments == []
    assert all(lot.est_settled for lot in r.residual_lots)
    assert r.open_lots(True) == [] and len(r.open_lots(False)) == 3


def test_expiry_unknown_unpriced_and_future_stay_open():
    sp = spot(NIFTY=[("2026-10-26", 24000.0)])
    r = fifo([fill("buy", 10, 10.0, "2026-10-01", expiry=None),
              fill("buy", 10, 10.0, "2026-10-01", symbol="NIFTY26OCT24500CE", strike=24500.0),
              fill("buy", 10, 10.0, "2026-10-01", symbol="NIFTY26NOV24500CE", strike=24500.0,
                   expiry="2026-11-24")], as_of="2026-10-29", sp=sp)
    lots = {l.symbol: l for l in r.residual_lots}
    assert r.est_segments == []
    assert lots["NIFTY26OCT24000CE"].expiry_unknown
    assert lots["NIFTY26OCT24500CE"].settlement_unpriced and lots["NIFTY26OCT24500CE"].expired
    assert not lots["NIFTY26NOV24500CE"].expired and not lots["NIFTY26NOV24500CE"].settlement_unpriced


def test_expiry_day_itself_is_unpriced_not_estimated():
    sp = spot(NIFTY=[("2026-10-27", 23000.0)])
    r = fifo([fill("sell", 10, 10.0, "2026-10-01")], as_of="2026-10-27", sp=sp)
    assert r.est_segments == [] and r.residual_lots[0].settlement_unpriced


def test_carried_in_tag_and_window_start():
    r = fifo([fill("buy", 10, 10.0, "2026-06-20"), fill("sell", 10, 12.0, "2026-07-02")])
    assert r.segments[0].carried_in is True


def test_sweep_positions_eod_and_expired_dropped():
    r = fifo([fill("buy", 10, 10.0, "2026-10-01"), fill("buy", 5, 11.0, "2026-10-02"),
              fill("sell", 3, 12.0, "2026-10-03")])
    sn = sweep_positions(r, [D("2026-10-01"), D("2026-10-02"), D("2026-10-03"), D("2026-10-27")])
    assert sn[D("2026-10-01")]["NIFTY26OCT24000CE"].qty == 10
    assert sn[D("2026-10-02")]["NIFTY26OCT24000CE"].qty == 15
    assert sn[D("2026-10-03")]["NIFTY26OCT24000CE"].qty == 12
    assert sn[D("2026-10-27")] == {}   # expired: no exposure on/after expiry


def test_run_fifo_never_mutates_inputs():
    fs = [fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 11.0, "2026-10-02")]
    run_fifo(fs, window_start=D("2026-07-01"), as_of=D("2026-10-05"))
    assert fs[0].qty == 10
