"""F42 P3 — rule-based what-ifs on small synthetic books (thresholds from config percentiles)."""
from __future__ import annotations

import pytest

from rita.services import fno_trade_analytics as an
from rita.services.fno_trade_suggestions import DISCLAIMER, suggestions
from tests.unit.f42_p3_helpers import cfg, ctx, fill

W = dict(date_from="2026-10-01", date_to="2026-10-12")
NO_MARGIN = {"ledger": {"available": False}, "cash_series": [], "trap": {"days": 0},
             "cash": {"min": None}, "stops": {"rows": []}}


def _run(fs, margin=None, c=None, **kw):
    c = c or cfg(suggestion_min_closed_trades=1)
    cx = ctx(fs, c=c, **{**W, **kw})
    lots = an.LotInfo()
    return suggestions(cx, an.overtrading(cx, []), an.buildup(cx, lots), margin or NO_MARGIN, lots), cx


def _rule(out, rid):
    return next(r for r in out["rules"] if r["id"] == rid)


def _pair(day, t0, t1, sell_px, buy_px=10.0, **kw):
    return [fill("buy", 10, buy_px, day, t0, **kw), fill("sell", 10, sell_px, day, t1, **kw)]


def test_max_trades_per_day_threshold_and_whatif():
    fs = (_pair("2026-10-01", "09:31", "09:40", 15.0) + _pair("2026-10-01", "09:45", "09:50", 7.0)
          + _pair("2026-10-01", "09:55", "10:00", 8.0) + _pair("2026-10-02", "10:00", "10:31", 11.0)
          + _pair("2026-10-05", "10:00", "10:31", 11.0) + _pair("2026-10-06", "10:00", "10:31", 11.0))
    out, _ = _run(fs)
    r = _rule(out, "max_trades_per_day")
    assert r["status"] == "applicable" and (
        r["parameter"]["name"], r["parameter"]["value"], r["parameter"]["unit"]) == ("max_entries_per_day", 1, "entries")
    w = r["what_if"]
    assert (w["baseline_pnl"], w["delta"], w["whatif_pnl"]) == (30.0, 50.0, 80.0)
    assert (w["trades_removed"], w["units_removed"], w["closed_trades_affected"]) == (2, 20.0, 2)
    assert "75th percentile" in r["threshold_basis"] and r["evidence"] and r["caveats"]
    assert out["disclaimer"] == DISCLAIMER and out["baseline_pnl"] == 30.0


def test_cooling_off_clamped_median_and_veto():
    fs = (_pair("2026-10-01", "09:31", "09:40", 15.0) + _pair("2026-10-01", "09:45", "09:50", 7.0)
          + _pair("2026-10-01", "09:55", "10:00", 8.0) + _pair("2026-10-02", "10:00", "10:31", 11.0))
    r = _rule(_run(fs)[0], "cooling_off_after_loss")
    assert r["parameter"]["value"] == 15 and r["parameter"]["unit"] == "minutes"   # clamped from 5 to the minimum
    assert r["what_if"]["trades_removed"] == 1 and r["what_if"]["delta"] == 20.0


def test_cooling_off_insufficient_without_timestamps():
    fs = [fill(s, 10, p, d, None) for s, p, d in [("buy", 10.0, "2026-10-01"), ("sell", 8.0, "2026-10-01")]]
    assert _rule(_run(fs)[0], "cooling_off_after_loss")["status"] == "insufficient_data"


def test_qty_cap_pro_rata_chronological_and_no_reinstatement():
    big = [fill("buy", 100, 10.0, "2026-10-01"), fill("buy", 100, 11.0, "2026-10-02"),
           fill("sell", 200, 12.0, "2026-10-05", "10:00")]
    small = []
    for und, exp, sym in [("NIFTY", "2026-11-24", "NIFTY26NOV24000CE"), ("BANKNIFTY", "2026-10-27", "BANKNIFTY26OCT50000CE"),
                          ("BANKNIFTY", "2026-11-24", "BANKNIFTY26NOV50000CE")]:
        kw = dict(symbol=sym, underlying=und, expiry=exp)
        small += [fill("buy", 40, 10.0, "2026-10-01", **kw), fill("sell", 40, 10.0, "2026-10-02", **kw)]
    r = _rule(_run(big + small)[0], "qty_cap_per_expiry")
    assert r["parameter"]["value"] == 40 and r["status"] == "applicable"
    w = r["what_if"]
    assert w["delta"] == -220.0               # -(0.6 x 200 + 1.0 x 100): vetoing winners lowers P&L
    assert w["units_removed"] == 160.0 and w["trades_removed"] == 2 and w["closed_trades_affected"] == 1
    assert any("pro rata" in c for c in r["caveats"])


def test_qty_cap_insufficient_with_single_group():
    r = _rule(_run([fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 11.0, "2026-10-02")])[0], "qty_cap_per_expiry")
    assert r["status"] == "insufficient_data"


def test_margin_headroom_floor_vetoes_short_entries_on_low_prior_cash():
    days = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
    vals = [100000, 90000, 80000, 70000, 20000, 10000, 60000]
    margin = {**NO_MARGIN, "ledger": {"available": True}, "cash_series": [
        {"date": d, "cash": float(v), "carried": False} for d, v in zip(days, vals)]}
    fs = [fill("sell", 10, 10.0, "2026-10-08", "10:00"), fill("sell", 10, 10.0, "2026-10-09", "10:00"),
          fill("buy", 20, 14.0, "2026-10-12", "10:00")]
    r = _rule(_run(fs, margin)[0], "margin_headroom_floor")
    assert r["status"] == "applicable" and r["parameter"]["value"] == 20000.0
    assert r["what_if"]["trades_removed"] == 1 and r["what_if"]["delta"] == 40.0   # veto the 10-09 short (prior cash 10000)
    assert _rule(_run(fs)[0], "margin_headroom_floor")["status"] == "insufficient_data"


def test_stop_discipline_exit_adjustment_one_sided_caveats_and_variants():
    fs = []
    for d, exit_px in (("2026-10-01", 25.0), ("2026-10-02", 15.0)):
        fs += [fill("sell", 100, 10.0, d, "10:00"), fill("buy", 100, exit_px, d, "10:31")]
    r = _rule(_run(fs)[0], "stop_discipline")
    assert r["parameter"]["value"] == 1.0 and r["what_if"]["delta"] == 500.0
    assert r["what_if"]["trades_removed"] == 0 and r["what_if"]["method"].startswith("exit_adjustment")
    assert {v["multiple"] for v in r["variants"]} >= {1.0, 1.5, 2.0}
    assert any("whipsaw" in c for c in r["caveats"]) and any("slippage" in c for c in r["caveats"])


def test_combined_union_and_stop_addon_without_double_count():
    fs = [fill("sell", 100, 10.0, "2026-10-01", "10:00"), fill("sell", 100, 12.0, "2026-10-02", "10:00"),
          fill("buy", 200, 25.0, "2026-10-05", "10:00")]
    out, _ = _run(fs)
    r5 = _rule(out, "no_averaging_down")
    assert r5["what_if"]["delta"] == 1300.0
    comb = out["combined"]
    assert comb["rules_included"] == ["no_averaging_down"] and comb["what_if"]["delta"] == 1300.0
    st = _rule(out, "stop_discipline")
    assert st["parameter"]["value"] == 1.25 and st["what_if"]["delta"] == 50.0
    assert comb["stop_addon"] == 50.0
    assert comb["combined_with_stop"] == 1325.0    # 1300 + 50 x (non-vetoed share 100/200)


def test_combined_takes_max_veto_fraction_per_fill():
    fs = (_pair("2026-10-01", "09:31", "09:40", 15.0) + _pair("2026-10-01", "09:45", "09:50", 7.0)
          + _pair("2026-10-01", "09:55", "10:00", 8.0) + _pair("2026-10-02", "10:00", "10:31", 11.0)
          + _pair("2026-10-05", "10:00", "10:31", 11.0) + _pair("2026-10-06", "10:00", "10:31", 11.0))
    out, _ = _run(fs)
    r1 = _rule(out, "max_trades_per_day")["what_if"]
    rc = _rule(out, "cooling_off_after_loss")["what_if"]
    c = out["combined"]["what_if"]
    assert set(out["combined"]["rules_included"]) >= {"max_trades_per_day", "cooling_off_after_loss"}
    # the vetoed set is the union, not the sum: trade 3 is vetoed by both but removed once
    assert c["trades_removed"] <= r1["trades_removed"] + rc["trades_removed"] - 1
    assert c["delta"] <= r1["delta"] + rc["delta"]


def test_insufficient_data_below_minimum_closed_trades_and_sample():
    fs = _pair("2026-10-01", "09:31", "09:40", 15.0)
    out, _ = _run(fs, c=cfg())
    assert out["sample"] == {"closed_trades": 1, "min_required": 10}
    assert all(r["status"] == "insufficient_data" and r["what_if"] is None for r in out["rules"])


def test_rules_ranked_by_delta_and_observations_cite_numbers():
    fs = (_pair("2026-10-01", "09:31", "09:40", 15.0) + _pair("2026-10-01", "09:45", "09:50", 7.0)
          + _pair("2026-10-01", "09:55", "10:00", 8.0))
    out, _ = _run(fs)
    app = [r for r in out["rules"] if r["status"] == "applicable"]
    assert [r["what_if"]["delta"] for r in app] == sorted((r["what_if"]["delta"] for r in app), reverse=True)
    assert [r["status"] for r in out["rules"]] == sorted((r["status"] for r in out["rules"]),
                                                         key=["applicable", "not_triggered", "insufficient_data"].index)
    ids = {o["id"] for o in out["observations"]}
    assert "high_churn" in ids and all(o["evidence"] for o in out["observations"])


def test_rule_wording_is_descriptive_not_imperative():
    out, _ = _run(_pair("2026-10-01", "09:31", "09:40", 15.0) + _pair("2026-10-01", "09:45", "09:50", 7.0))
    for r in out["rules"]:
        assert "should" not in r["title"].lower() and "must" not in r["title"].lower()
    assert any("what-if" in r["title"].lower() or "What-if" in r["title"] for r in out["rules"])
