"""F42 P3 — QA regression (real-data fixes in e182543) + defect probes on FIFO / analytics / service."""
from __future__ import annotations

import pytest

from rita.services import fno_trade_analytics as an
from rita.services.fno_trade_fifo import build_closed_trades, sweep_positions
from rita.services.fno_trade_suggestions import suggestions
from tests.unit.f42_p3_helpers import D, cfg, ctx, fifo, fill, spot

W = dict(date_from="2026-10-01", date_to="2026-10-12")


def _led(rows):
    return [an.LedgerRow(D(d), deb, cred, nb, i) for i, (d, deb, cred, nb) in enumerate(rows)]


# ── regressions for e182543 ───────────────────────────────────────────────────

def test_negative_cash_days_count_as_below_low_cash_threshold():
    """Pre-fix predicate `0 <= c < thr` ignored overdrawn days (counted 0 below threshold)."""
    rows = _led([("2026-10-01", 0, 100000, 100000), ("2026-10-02", 130000, 0, -30000),
                 ("2026-10-05", 20000, 0, -50000)])
    sp = spot(NIFTY=[(d, 24000.0) for d in ("2026-10-01", "2026-10-02", "2026-10-05")])
    c = ctx([fill("sell", 10, 10.0, "2026-10-02", "10:00")], sp=sp, c=cfg(low_cash_threshold_inr=50000.0), **W)
    m = an.margin_trap(c, rows, None)
    assert m["cash"]["days_negative"] == 2
    assert m["cash"]["days_below_threshold"] == 2


def test_days_below_threshold_is_superset_of_days_negative():
    rows = _led([("2026-10-01", 0, 100000, 100000), ("2026-10-02", 60000, 0, 40000),
                 ("2026-10-05", 60000, 0, -20000)])
    sp = spot(NIFTY=[(d, 24000.0) for d in ("2026-10-01", "2026-10-02", "2026-10-05")])
    c = ctx([fill("sell", 10, 10.0, "2026-10-02", "10:00")], sp=sp, c=cfg(low_cash_threshold_inr=50000.0), **W)
    m = an.margin_trap(c, rows, None)["cash"]
    assert m["days_below_threshold"] == 2 and m["days_negative"] == 1   # 40000 and -20000 are below 50000


def _margin(vals):
    days = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
    return {"ledger": {"available": True}, "cash_series": [
        {"date": d, "cash": float(v), "carried": False} for d, v in zip(days, vals)],
        "trap": {"days": 0}, "cash": {"min": None}, "stops": {"rows": []}}


def _sugg(margin):
    fs = [fill("sell", 10, 10.0, "2026-10-08", "10:00"), fill("sell", 10, 10.0, "2026-10-09", "10:00"),
          fill("buy", 20, 14.0, "2026-10-12", "10:00")]
    cx = ctx(fs, c=cfg(suggestion_min_closed_trades=1), **W)
    lots = an.LotInfo()
    out = suggestions(cx, an.overtrading(cx, []), an.buildup(cx, lots), margin, lots)
    return next(r for r in out["rules"] if r["id"] == "margin_headroom_floor")


def test_cash_floor_rule_suppressed_when_ledger_balance_non_positive():
    r = _sugg(_margin([-100000, -90000, -80000, -70000, -20000, -10000, -60000]))
    assert r["status"] == "insufficient_data"
    assert "collateral" in (r.get("reason") or r.get("message") or str(r))


def test_cash_floor_rule_suppressed_when_floor_exactly_zero():
    assert _sugg(_margin([0, 0, 0, 0, 0, 0, 0]))["status"] == "insufficient_data"


def test_cash_floor_rule_still_applicable_when_floor_positive_despite_some_negative_days():
    r = _sugg(_margin([100000, 90000, 80000, 70000, 20000, -10000, 60000]))
    assert r["status"] == "applicable" and r["parameter"]["value"] > 0


# ── FIFO probes ───────────────────────────────────────────────────────────────

def test_flip_then_partial_cover_matches_flip_remainder_not_original_side():
    r = fifo([fill("buy", 100, 10.0, "2026-10-01"), fill("sell", 150, 14.0, "2026-10-02", "10:00"),
              fill("buy", 20, 12.0, "2026-10-03", "10:00")])
    assert [(s.side, s.qty, s.pnl) for s in r.segments] == [(1, 100, 400.0), (-1, 20, 40.0)]
    assert r.segments[1].flip is True
    lot = r.residual_lots[0]
    assert lot.side == -1 and lot.qty == 30 and lot.avg_entry == 14.0


def test_flat_then_reverse_in_separate_fills_not_a_flip():
    r = fifo([fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 11.0, "2026-10-01", "11:00"),
              fill("sell", 10, 12.0, "2026-10-02")])
    assert [e.cls for e in r.events] == ["open_new", "close", "open_new"]
    assert r.residual_lots[0].side == -1 and not r.segments[0].flip


def test_short_partial_covers_fifo_across_lots():
    r = fifo([fill("sell", 30, 20.0, "2026-10-01"), fill("sell", 30, 10.0, "2026-10-02"),
              fill("buy", 40, 15.0, "2026-10-03")])
    assert [(s.qty, s.entry_px, s.pnl) for s in r.segments] == [(30, 20.0, 150.0), (10, 10.0, -50.0)]
    assert r.residual_lots[0].qty == 20 and r.residual_lots[0].avg_entry == 10.0


def test_short_put_expiry_itm_estimate_and_long_call_otm_worthless():
    sp = spot(NIFTY=[("2026-10-27", 23800.0)])
    r = fifo([fill("sell", 10, 100.0, "2026-10-01", symbol="NIFTY26OCT24000PE", itype="PE"),
              fill("buy", 10, 20.0, "2026-10-01", symbol="NIFTY26OCT24500CE", strike=24500.0)],
             as_of="2026-10-29", sp=sp)
    by = {s.symbol: s for s in r.est_segments}
    assert by["NIFTY26OCT24000PE"].exit_px == 200.0 and by["NIFTY26OCT24000PE"].pnl == -1000.0
    assert by["NIFTY26OCT24500CE"].exit_px == 0.0 and by["NIFTY26OCT24500CE"].pnl == -200.0


def test_expiry_estimate_of_flip_remainder_uses_flip_side():
    sp = spot(NIFTY=[("2026-10-27", 24500.0)])
    r = fifo([fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 15, 12.0, "2026-10-02", "10:00")],
             as_of="2026-10-29", sp=sp)
    e = r.est_segments[0]
    assert e.side == -1 and e.qty == 5 and e.exit_px == 500.0 and e.pnl == pytest.approx(5 * (12.0 - 500.0))


def test_pre_history_close_without_open_becomes_short_and_is_not_a_crash():
    """Sell with no prior buy (position opened before the import) is treated as a new short."""
    r = fifo([fill("sell", 10, 12.0, "2026-10-02")])
    assert r.segments == [] and r.residual_lots[0].side == -1


def test_zero_pnl_close_all_and_empty_inputs():
    r = fifo([])
    assert r.segments == [] and r.events == [] and r.residual_lots == []
    assert build_closed_trades([]) == []
    assert sweep_positions(r, [D("2026-10-01")]) == {D("2026-10-01"): {}}


def test_symbols_are_independent_books():
    r = fifo([fill("buy", 10, 10.0, "2026-10-01"),
              fill("sell", 10, 11.0, "2026-10-01", "11:00", symbol="NIFTY26OCT24500CE", strike=24500.0)])
    assert r.segments == [] and {lot.symbol: lot.side for lot in r.residual_lots} == {
        "NIFTY26OCT24000CE": 1, "NIFTY26OCT24500CE": -1}


# ── analytics probes: empty inputs, window filters ────────────────────────────

def test_all_panels_tolerate_empty_fills():
    c = ctx([], **W)
    an.overtrading(c, [])
    an.buildup(c, an.LotInfo())
    an.market_turn(c)
    m = an.margin_trap(c, [], None)
    assert m["ledger"]["available"] is False
    assert an.reconciliation(c, [])["rows"] == []


def test_pre_window_open_counts_trade_but_not_fill_and_is_carried_in():
    fs = [fill("buy", 10, 10.0, "2026-09-20"), fill("sell", 10, 15.0, "2026-10-02", "10:00")]
    c = ctx(fs, **W)
    ot = an.overtrading(c, [])
    assert ot["activity"]["fills_total"] == 1
    assert ot["winloss"]["n"] == 1 and ot["winloss"]["wins"] == 1
    assert c.trades[0].carried_in is True


def test_trade_closed_before_window_excluded_from_winloss():
    fs = [fill("buy", 10, 10.0, "2026-09-20"), fill("sell", 10, 15.0, "2026-09-25"),
          fill("buy", 10, 10.0, "2026-10-02"), fill("sell", 10, 9.0, "2026-10-03")]
    wl = an.overtrading(ctx(fs, **W), [])["winloss"]
    assert wl["n"] == 1 and wl["losses"] == 1 and wl["wins"] == 0


def test_expiry_estimate_toggle_excludes_est_from_trades():
    sp = spot(NIFTY=[("2026-10-27", 23000.0)])
    fs = [fill("sell", 10, 50.0, "2026-10-02")]
    on = ctx(fs, date_to="2026-10-29", include_est=True, sp=sp, date_from="2026-10-01")
    off = ctx(fs, date_to="2026-10-29", include_est=False, sp=sp, date_from="2026-10-01")
    assert len(on.trades) == 1 and on.trades[0].estimated and off.trades == []


def test_reconciliation_period_boundaries_inclusive_and_cross_period_split():
    fs = [fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 5, 12.0, "2026-10-05"),
          fill("sell", 5, 14.0, "2026-10-06")]
    c = ctx(fs, **W)
    lines = [an.PnlLine("NIFTY26OCT24000CE", "NIFTY", "2026-10", D("2026-10-01"), D("2026-10-05"), 10.0, 0, None),
             an.PnlLine("NIFTY26OCT24000CE", "NIFTY", "2026-10", D("2026-10-06"), D("2026-10-10"), 20.0, 0, None)]
    row = an.reconciliation(c, lines)["rows"][0]
    assert row["fifo_measured"] == 30.0 and row["sheet_realised"] == 30.0 and row["within_tolerance"]


# ── service-level probes (date window, user scoping, negative ledger end-to-end) ──

def _svc(db):
    from rita.services.fno_trade_analytics_service import FnoTradeAnalyticsService
    from datetime import date
    return FnoTradeAnalyticsService(db, today=date(2026, 10, 12))


def test_service_date_to_excludes_later_fills_and_pnl(db_session):
    from rita.services.fno_trade_analytics_service import AnalyticsParams
    from tests.unit.f42_p3_helpers import seed
    from datetime import date
    fs = [fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 12.0, "2026-10-02", "10:00"),
          fill("buy", 10, 10.0, "2026-10-08"), fill("sell", 10, 5.0, "2026-10-09", "10:00")]
    seed(db_session, "u", fs)
    r = _svc(db_session).overtrading("u", AnalyticsParams(date_to=date(2026, 10, 5)))
    assert r.activity.fills_total == 2 and r.winloss.n == 1 and r.winloss.wins == 1


def test_service_ledger_is_user_scoped_and_negative_cash_counts_below_threshold(db_session):
    from rita.services.fno_trade_analytics_service import AnalyticsParams
    from tests.unit.f42_p3_helpers import seed
    fs = [fill("sell", 10, 10.0, "2026-10-02", "10:00"), fill("buy", 10, 9.0, "2026-10-05", "10:00")]
    led = [("2026-10-01", 0, 100000, 100000), ("2026-10-02", 130000, 0, -30000), ("2026-10-05", 20000, 0, -50000)]
    seed(db_session, "a", fs, [("NIFTY", d, 24000.0) for d in ("2026-10-01", "2026-10-02", "2026-10-05")], led)
    seed(db_session, "b", fs)
    m = _svc(db_session).margin_trap("a", AnalyticsParams())
    assert m.cash.days_negative == 2 and m.cash.days_below_threshold >= 2
    assert _svc(db_session).margin_trap("b", AnalyticsParams()).ledger.available is False
