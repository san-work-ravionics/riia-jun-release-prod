"""F42 P3 — analyses 1-6 + reconciliation on small hand-computable synthetic books."""
from __future__ import annotations

import math

import pytest

from rita.services import fno_trade_analytics as an
from tests.unit.f42_p3_helpers import D, cfg, ctx, fill, spot

W = dict(date_from="2026-10-01", date_to="2026-10-12")


def _ot_book():
    return [
        fill("buy", 10, 10.0, "2026-10-01", "09:31"), fill("sell", 10, 12.0, "2026-10-01", "09:40"),
        fill("buy", 10, 12.0, "2026-10-01", "09:45"), fill("sell", 10, 11.0, "2026-10-01", "09:50"),
        fill("buy", 10, 11.0, "2026-10-01", "09:55"), fill("sell", 10, 13.0, "2026-10-02", "11:00"),
    ]


def test_overtrading_counts_weekly_churn_holding_bursts():
    c = ctx(_ot_book(), **W)
    ot = an.overtrading(c, [])
    a = ot["activity"]
    assert (a["fills_total"], a["orders_total"], a["active_days"]) == (6, 6, 2)
    assert a["fills_per_day"] == {"mean": 3.0, "median": 3.0, "p90": 4.6, "max": 5}
    assert ot["weekly"] == [{"week": "2026-W40", "fills": 6, "active_days": 2, "closed_trades": 3}]
    assert ot["churn"]["churn_qty_pct"] == pytest.approx(66.67) and ot["churn"]["churn_pnl"] == 10.0
    h = ot["holding"]
    assert h["median_minutes"] == 7.0
    assert {b["label"]: b["count"] for b in h["buckets"]} == {
        "<5m": 0, "5-30m": 2, "30m-2h": 0, ">2h same-day": 0, "1d": 1, "2-5d": 0, ">5d": 0}
    b = ot["bursts"]
    assert b["available"] and b["count"] == 1 and b["top"][0]["fills"] == 5
    assert b["reentries_after_loss"] == {"count": 1, "pnl": 20.0}
    for blk in (a, h, ot["churn"], b, ot["charges"], ot["winloss"]):
        assert blk["definition"] and blk["assumptions"]   # each sub-analysis carries its own text


def test_winloss_hand_computed():
    wl = an.overtrading(ctx(_ot_book(), **W), [])["winloss"]
    assert (wl["n"], wl["wins"], wl["losses"], wl["scratch"]) == (3, 2, 1, 0)
    assert wl["win_rate"] == pytest.approx(66.67)
    assert (wl["avg_win"], wl["avg_loss"], wl["payoff"], wl["expectancy"]) == (20.0, 10.0, 2.0, 10.0)
    assert wl["profit_factor"] == 4.0 and wl["breakeven_win_rate"] == pytest.approx(33.33)
    assert (wl["largest_win"], wl["largest_loss"], wl["max_loss_streak"]) == (20.0, -10.0, 1)
    assert wl["measured_only"]["n"] == 3 and wl["by_side"][0]["key"] == "long"


def test_scratch_excluded_from_win_rate_and_no_closed_trades_safe():
    fs = [fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 10.0, "2026-10-01", "10:31"),
          fill("buy", 10, 10.0, "2026-10-02"), fill("sell", 10, 12.0, "2026-10-02", "10:31")]
    wl = an.overtrading(ctx(fs, **W), [])["winloss"]
    assert wl["scratch"] == 1 and wl["win_rate"] == 100.0 and wl["avg_loss"] is None and wl["payoff"] is None
    only_open = an.overtrading(ctx([fill("buy", 10, 10.0, "2026-10-01")], **W), [])
    assert only_open["winloss"]["n"] == 0 and only_open["winloss"]["win_rate"] is None
    assert only_open["churn"]["churn_qty_pct"] is None


def test_timestamp_dependent_metrics_null_without_timestamps():
    fs = [fill(s, 10, p, d, None) for s, p, d in
          [("buy", 10.0, "2026-10-01"), ("sell", 12.0, "2026-10-01"), ("buy", 9.0, "2026-10-02"),
           ("sell", 8.0, "2026-10-03")]]
    ot = an.overtrading(ctx(fs, **W), [])
    assert ot["bursts"]["available"] is False and ot["bursts"]["reason"] == "no_timestamps"
    assert ot["bursts"]["count"] is None and ot["holding"]["median_minutes"] is None
    assert ot["holding"]["reason"] == "no_timestamps"
    assert ot["churn"]["churn_qty_pct"] is not None   # date-based metrics still work


def test_charges_allocation_by_turnover_and_estimate_flag():
    cp = an.ChargePeriod(D("2026-04-01"), D("2026-10-05"), 600.0, 6900.0)
    ch = an.overtrading(ctx(_ot_book(), **W), [cp])["charges"]
    assert ch["estimated"] is True and ch["total_sheet"] == 600.0
    assert ch["est_window"] == 60.0              # 600 x 690 / 6900
    assert ch["pct_of_gross"] == 200.0 and ch["per_closed_trade"] == 20.0
    assert ch["breakeven_trades_needed"] == math.ceil(60 / 10)


def test_charges_net_gross_negative_and_no_sheet():
    fs = [fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 8.0, "2026-10-01", "10:31")]
    cp = an.ChargePeriod(D("2026-04-01"), D("2026-10-05"), 100.0, 360.0)
    ch = an.overtrading(ctx(fs, **W), [cp])["charges"]
    assert ch["net_gross_negative"] is True and ch["pct_of_gross"] is None
    assert ch["breakeven_trades_needed"] is None
    assert an.overtrading(ctx(fs, **W), [])["charges"]["reason"] == "no_pnl_sheet"


def _build_book():
    return [fill("buy", 100, 20.0, "2026-10-01"), fill("buy", 100, 15.0, "2026-10-02", "10:00"),
            fill("buy", 50, 18.0, "2026-10-03", "10:00"), fill("sell", 250, 10.0, "2026-10-06", "10:00")]


def test_buildup_averaging_down_chain_and_timeline():
    sp = spot(NIFTY=[("2026-10-01", 24000.0), ("2026-10-02", 23800.0), ("2026-10-03", 23900.0),
                     ("2026-10-06", 24000.0)])
    c = ctx(_build_book(), sp=sp, **W)
    b = an.buildup(c, an.LotInfo())
    av = b["averaging"]
    assert av["adverse_add_fills"] == 1 and av["adverse_add_units"] == 100
    assert av["share_of_entries_pct"] == pytest.approx(33.33)
    assert av["adverse_add_closed_pnl"] == -500.0 and av["adverse_add_open_units"] == 0
    assert av["spot_adverse_adds"] == 1
    assert b["events"] == {"open_new": 1, "scale_in": 2, "scale_out": 0, "close": 1, "flip": 0}
    ch = b["chains"][0]
    assert (ch["adds"], ch["adverse_adds"], ch["peak_qty"], ch["pnl_measured"]) == (2, 1, 250, -1900.0)
    assert ch["still_open"] is False and b["chain_totals"] == {"count": 1, "with_adverse_add": 1, "max_adds": 2}
    row = next(r for r in b["timeline"] if r["date"] == "2026-10-02")
    assert (row["long_units"], row["short_units"], row["scale_in_units"], row["adverse_add_units"]) == (200, 0, 100, 100)
    assert b["lots"] == {"lots_available": False, "lots_basis": "unknown", "coverage_pct": None}
    assert row["long_lots"] is None


def test_buildup_spot_adverse_null_without_spot_and_lots_from_master_only():
    b = an.buildup(ctx(_build_book(), **W), an.LotInfo())
    assert b["averaging"]["spot_adverse_adds"] is None
    lots = an.LotInfo(True, {"NIFTY26OCT24000CE": 20}, {"NIFTY": 20})
    b2 = an.buildup(ctx(_build_book(), **W), lots)
    assert b2["lots"]["lots_basis"] == "kite_master" and b2["lots"]["coverage_pct"] == 100.0
    row = next(r for r in b2["timeline"] if r["date"] == "2026-10-02")
    assert row["long_lots"] == 10.0     # 200 units / lot size 20 (test-supplied master value)
    fb = an.LotInfo(True, {}, {"NIFTY": 20})
    assert an.buildup(ctx(_build_book(), **W), fb)["lots"]["lots_basis"] == "underlying_current"


def test_buildup_short_adverse_and_carried_in():
    fs = [fill("sell", 10, 10.0, "2026-09-20"), fill("sell", 10, 12.0, "2026-10-02")]
    c = ctx(fs, **W)
    b = an.buildup(c, an.LotInfo())
    assert b["averaging"]["adverse_add_fills"] == 1
    row = next(r for r in b["timeline"] if r["date"] == "2026-10-02")
    assert row["short_units"] == 20 and row["carried_in"] == 10 and row["short_notional_proxy"] == 20 * 24000.0
    assert b["averaging"]["adverse_add_open_units"] == 10    # open slice of the adverse add (second lot)


MT_SPOT = [("2026-10-01", 24000.0), ("2026-10-02", 24300.0), ("2026-10-05", 24000.0),
           ("2026-10-06", 24000.0), ("2026-10-07", 23700.0)]


def _mt_book():
    return [fill("buy", 100, 10.0, "2026-10-01", "10:00"),
            fill("buy", 50, 10.0, "2026-10-05", "09:31"),      # same-day add: not in carried-in exposure
            fill("sell", 100, 8.0, "2026-10-05", "10:00")]


def test_market_turn_reversal_exposure_previous_eod_and_delta1():
    c = ctx(_mt_book(), sp=spot(NIFTY=MT_SPOT), **W)
    mt = an.market_turn(c)
    rows = {r["date"]: r for r in mt["turn_days"]}
    assert set(rows) == {"2026-10-02", "2026-10-05", "2026-10-07"}
    assert rows["2026-10-02"]["is_reversal"] is False            # no prior return
    assert rows["2026-10-07"]["is_reversal"] is False            # prior return is exactly 0
    r5 = rows["2026-10-05"]
    assert r5["is_reversal"] is True and r5["bias_units_in"] == 100 and r5["bias_label"] == "bullish"
    assert r5["adverse_exposed"] is True and r5["delta1_bound_pnl"] == -30000.0
    assert r5["realised_pnl_day"] == -200.0 and r5["realised_from_carried_in"] == -200.0
    assert r5["realised_from_opened_that_day"] == 0.0
    k = mt["kpis"]
    assert (k["n_turn_days"], k["n_big_move_days"], k["n_adverse_exposed"]) == (1, 3, 1)
    assert k["adverse_exposed_pct"] == 100.0 and k["realised_pnl_turn_adverse"] == -200.0
    assert k["realised_from_carried_in"] == -200.0 and k["realised_from_opened_that_day"] == 0.0
    s = mt["series"][0]
    assert s["underlying"] == "NIFTY" and len(s["dates"]) == len(s["turn_flag"]) == 4
    assert mt["worst_days"][0]["date"] == "2026-10-05" and mt["worst_days"][0]["realised_pnl_day"] == -200.0
    assert "NIFTY26OCT24000CE" in mt["worst_days"][0]["open_symbols"]
    assert mt["info"]["definition"] and mt["info"]["assumptions"]


def test_market_turn_delta_sign_table():
    cases = [("CE", "buy", "bullish"), ("PE", "sell", "bullish"), ("CE", "sell", "bearish"),
             ("PE", "buy", "bearish")]
    for itype, side, label in cases:
        sym = f"NIFTY26OCT24000{itype}"
        c = ctx([fill(side, 10, 10.0, "2026-10-01", symbol=sym, itype=itype)], sp=spot(NIFTY=MT_SPOT), **W)
        row = next(r for r in an.market_turn(c)["turn_days"] if r["date"] == "2026-10-02")
        assert row["bias_label"] == label, (itype, side)


def test_market_turn_missing_spot_degrades():
    mt = an.market_turn(ctx(_mt_book(), **W))
    assert mt["spot"]["available"] is False and mt["turn_days"] == [] and mt["series"] == []
    assert mt["worst_days"]    # drawdown days do not need spot


def _led(rows):
    return [an.LedgerRow(D(d), deb, cred, nb, i) for i, (d, deb, cred, nb) in enumerate(rows)]


def test_balance_sign_autodetect_both_ways():
    pos = _led([("2026-10-01", 0, 100000, 100000), ("2026-10-02", 60000, 0, 40000), ("2026-10-03", 10000, 0, 30000)])
    neg = _led([("2026-10-01", 0, 100000, -100000), ("2026-10-02", 60000, 0, -40000), ("2026-10-03", 10000, 0, -30000)])
    assert an.detect_balance_sign(pos) == (1, 100.0)
    assert an.detect_balance_sign(neg) == (-1, 100.0)
    assert an.detect_balance_sign(_led([("2026-10-01", 0, 5, 7), ("2026-10-02", 0, 5, 1000)]))[0] is None


MG_LEDGER = [("2026-10-01", 0, 100000, 100000), ("2026-10-02", 60000, 0, 40000),
             ("2026-10-03", 10000, 0, 30000), ("2026-10-06", 5000, 0, 25000)]


def _mg_book():
    return [fill("sell", 100, 10.0, "2026-10-02", "10:00"), fill("sell", 10, 14.0, "2026-10-03", "10:00"),
            fill("buy", 110, 18.0, "2026-10-07", "10:00")]


def test_margin_trap_cash_streak_low_cash_trap_loss_growth():
    sp = spot(NIFTY=[(d, 24000.0) for d in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-06", "2026-10-07")])
    c = ctx(_mg_book(), sp=sp, **W)
    m = an.margin_trap(c, _led(MG_LEDGER), None)
    assert m["ledger"]["available"] and m["ledger"]["balance_sign"] == 1
    assert m["cash"]["min"] == 25000.0 and m["cash"]["min_date"] == "2026-10-06"
    assert m["cash"]["days_below_threshold"] == 4 and m["cash"]["days_negative"] == 0  # incl. carried 10-07
    st = m["debit_streaks"]
    assert len(st) == 1 and st[0]["days"] == 3 and st[0]["net_outflow"] == 75000.0
    days = {t["date"]: t for t in m["trap"]["days_list"]}
    assert "2026-10-02" not in days            # own entry price is no loss
    assert days["2026-10-03"]["open_losers_count"] == 1 and days["2026-10-06"]["cash"] == 25000.0
    assert days["2026-10-03"]["short_notional_proxy"] == 110 * 24000.0
    assert days["2026-10-03"]["proxy_to_cash_ratio"] == pytest.approx(110 * 24000 / 30000, abs=1e-3)
    assert m["trap"]["days"] == len(days)
    g = m["trap"]["loss_growth_est"]
    assert g["first_trap_date"] == "2026-10-03" and g["symbols_n"] == 1
    assert g["loss_at_first_trap_est"] < 0 and g["final_closed_pnl"] < g["loss_at_first_trap_est"]
    assert m["exposure"]["estimated"] is True
    assert m["cash"]["info"]["assumptions"] and m["trap"]["info"]["definition"].startswith("Low-cash days")


def test_margin_trap_negative_sign_gap_carry_and_day_close_selection():
    rows = _led([("2026-10-01", 0, 100000, -100000),
                 ("2026-10-02", 10000, 0, -40000),        # imported first, but not the day close
                 ("2026-10-02", 50000, 0, -50000)])      # imported last; expected close = -100000+60000 = -40000
    sp = spot(NIFTY=[(d, 24000.0) for d in ("2026-10-01", "2026-10-02", "2026-10-05")])
    c = ctx([fill("buy", 10, 10.0, "2026-10-05", "10:00")], sp=sp, **W)
    m = an.margin_trap(c, rows, None)
    assert m["ledger"]["balance_sign"] == -1
    by = {p["date"]: p for p in m["cash_series"]}
    assert by["2026-10-02"]["cash"] == 40000.0 and by["2026-10-02"]["carried"] is False
    assert by["2026-10-05"]["cash"] == 40000.0 and by["2026-10-05"]["carried"] is True
    assert m["ledger"]["ledger_gap_days"] == 1 and m["ledger"]["ordering_ambiguous_days"] == 0


def test_margin_trap_stale_mark_is_unmarked_not_a_loser():
    fs = [fill("sell", 100, 10.0, "2026-10-01", "10:00"), fill("sell", 10, 14.0, "2026-10-01", "10:31")]
    sp = spot(NIFTY=[(d, 24000.0) for d in ("2026-10-01", "2026-10-12")])
    rows = _led([("2026-10-01", 0, 20000, 20000), ("2026-10-02", 1000, 0, 19000), ("2026-10-12", 1000, 0, 18000)])
    m = an.margin_trap(ctx(fs, sp=sp, **W), rows, None)
    assert m["trap"]["lots_unmarked"] >= 1
    assert all(t["date"] != "2026-10-12" for t in m["trap"]["days_list"])


def test_margin_trap_without_ledger_unavailable_but_stops_present():
    m = an.margin_trap(ctx(_mg_book(), **W), [], None)
    assert m["ledger"]["available"] is False and m["cash_series"] == [] and m["trap"]["days"] == 0
    assert m["stops"]["rows"]


def test_stops_what_if_per_multiple_longs_excluded():
    fs = [fill("sell", 100, 10.0, "2026-10-01", "10:00"), fill("buy", 100, 25.0, "2026-10-01", "10:31"),
          fill("sell", 100, 10.0, "2026-10-02", "10:00"), fill("buy", 100, 15.0, "2026-10-02", "10:31"),
          fill("buy", 100, 10.0, "2026-10-03", "10:00"), fill("sell", 100, 8.0, "2026-10-03", "10:31")]
    st = an.margin_trap(ctx(fs, **W), [], None)["stops"]
    rows = {r["multiple"]: r for r in st["rows"]}
    assert st["long_closed_excluded"] == 1 and st["short_closed"] == 2
    assert rows[1.0]["n_exceeded"] == 1 and rows[1.0]["saved_if_stopped"] == 500.0
    assert rows[1.0]["realised_loss_exceeding"] == 1500.0
    assert rows[1.0]["share_of_total_loss_pct"] == pytest.approx(500 / 2200 * 100, abs=0.01)
    assert rows[1.5]["saved_if_stopped"] == 0.0 and rows[2.0]["n_exceeded"] == 0
    assert any("whipsaw" in a for a in st["assumptions"]) and any("slippage" in a for a in st["assumptions"])


def test_stops_open_beyond_estimate():
    fs = [fill("sell", 100, 10.0, "2026-10-01", "10:00"), fill("sell", 10, 30.0, "2026-10-04", "10:00")]
    rows = {r["multiple"]: r for r in an.margin_trap(ctx(fs, date_from="2026-10-01", date_to="2026-10-07"),
                                                      [], None)["stops"]["rows"]}
    assert rows[1.0]["open_beyond_n"] >= 1 and rows[1.0]["open_beyond_excess_est"] > 0


# ── reconciliation ─────────────────────────────────────────────────────────────

PER = (D("2026-04-01"), D("2026-10-05"))


def _line(sym, realised, open_q=0, typ=None, **kw):
    return an.PnlLine(sym, "NIFTY", "2026-10", *PER, realised, open_q, typ)


def test_reconciliation_gap_causes_and_totals():
    ok = "NIFTY26OCT24000CE"
    fs = [fill("buy", 100, 10.0, "2026-10-01"), fill("sell", 100, 12.0, "2026-10-02", "11:00"),
          fill("buy", 10, 10.0, "2026-10-01", symbol="NIFTY26OCT24100CE", strike=24100.0),
          fill("sell", 10, 11.0, "2026-10-02", symbol="NIFTY26OCT24100CE", strike=24100.0),
          fill("buy", 10, 10.0, "2026-10-01", symbol="NIFTY26OCT24200CE", strike=24200.0),
          fill("sell", 10, 11.0, "2026-10-02", symbol="NIFTY26OCT24200CE", strike=24200.0),
          fill("buy", 10, 10.0, "2026-10-01", symbol="NIFTY26OCT24300CE", strike=24300.0),
          fill("sell", 10, 11.0, "2026-10-02", symbol="NIFTY26OCT24300CE", strike=24300.0)]
    lines = [_line(ok, 200.0), _line("NIFTY26OCT24100CE", 300.0), _line("NIFTY26OCT24200CE", 10.5),
             _line("NIFTY26OCT99999CE", 50.0)]
    rec = an.reconciliation(ctx(fs, **W), lines)
    r = {x["symbol"]: x for x in rec["rows"]}
    assert r[ok]["within_tolerance"] and r[ok]["causes"] == []
    assert r["NIFTY26OCT24100CE"]["gap_measured"] == 290.0 and "pre_history_open" in r["NIFTY26OCT24100CE"]["causes"]
    assert r["NIFTY26OCT24200CE"]["within_tolerance"] and r["NIFTY26OCT24200CE"]["causes"] == ["rounding"]
    assert r["NIFTY26OCT24300CE"]["causes"] == ["sheet_missing"] and r["NIFTY26OCT24300CE"]["sheet_realised"] is None
    assert r["NIFTY26OCT99999CE"]["causes"] == ["trades_missing"]
    t = rec["totals"]
    assert t["symbols"] == 5 and t["n_symbols_ok"] == 2 and t["n_symbols_gap"] == 3
    assert rec["definition"] and rec["assumptions"]


def test_reconciliation_expiry_estimate_and_implied_settle_px():
    sp = spot(NIFTY=[("2026-10-27", 23800.0)])
    fs = [fill("sell", 100, 50.0, "2026-10-01")]
    c = ctx(fs, date_from="2026-10-01", date_to="2026-10-29", sp=sp)
    ln = an.PnlLine("NIFTY26OCT24000CE", "NIFTY", "2026-10", D("2026-04-01"), D("2026-10-29"), 5000.0, 0, "Short")
    rec = an.reconciliation(c, [ln])
    row = rec["rows"][0]
    assert row["gap_measured"] == 5000.0 and row["gap_with_estimate"] == 0.0
    assert row["fifo_expiry_estimate"] == 5000.0 and row["fifo_open_qty"] == -100
    assert row["causes"] == ["expiry_unclosed"]
    assert row["sheet_implied_px"] == 0.0 and row["intrinsic_px"] == 0.0
    assert rec["totals"]["expiry_estimate_explains"] == 5000.0


def test_include_estimate_flag_switches_aggregates_but_keeps_measured():
    sp = spot(NIFTY=[("2026-10-27", 23800.0)])
    fs = [fill("sell", 100, 50.0, "2026-10-01"), fill("buy", 10, 5.0, "2026-10-02", "11:00")]
    on = ctx(fs, date_from="2026-10-01", date_to="2026-10-29", include_est=True, sp=sp)
    off = ctx(fs, date_from="2026-10-01", date_to="2026-10-29", include_est=False, sp=sp)
    assert an.overtrading(on, [])["winloss"]["n"] == 2
    assert an.overtrading(off, [])["winloss"]["n"] == 1
    assert an.overtrading(on, [])["winloss"]["measured_only"]["n"] == 1
    assert len(on.res.open_lots(True)) == 0 and len(off.res.open_lots(False)) == 1
