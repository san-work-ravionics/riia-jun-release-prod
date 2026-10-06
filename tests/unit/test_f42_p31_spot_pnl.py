"""F42 P4 — Spot vs P&L: series, statistics, alignment, snapshot, what-if rules, service/API, config.

Synthetic data only (invented symbols, round numbers); nothing read from disk or live-data/.
"""
from __future__ import annotations

import statistics
from datetime import date
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from rita.config import TradeAnalysisSettings
from rita.schemas import fno_trade_analytics as sch
from rita.services import fno_trade_analytics as an
from rita.services import fno_trade_spot_pnl as sp
from rita.services.fno_trade_analytics_service import AnalyticsParams, FnoTradeAnalyticsService
from rita.services.fno_trade_suggestions import SPOT_RULE_IDS, spot_rules, suggestions
from tests.unit.f42_p3_helpers import D, cfg, ctx, fill, seed, spot

CLOSES = [("2026-09-30", 20000.0), ("2026-10-01", 20200.0), ("2026-10-02", 20400.0), ("2026-10-05", 20000.0),
          ("2026-10-06", 20100.0), ("2026-10-07", 19800.0), ("2026-10-08", 20000.0), ("2026-10-09", 20200.0),
          ("2026-10-12", 20200.0), ("2026-10-13", 20400.0)]
DAYS = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09",
        "2026-10-12", "2026-10-13"]
SMALL = dict(spot_rel_min_days=9, spot_rel_min_closing_days=3, spot_rel_min_bucket_days=1,
             spot_rel_min_bias_days=1, turn_threshold_pct=0.9)


def _book():
    return [
        fill("buy", 100, 10.0, "2026-10-01"), fill("sell", 100, 12.0, "2026-10-02"),           # +200 on 10-02
        fill("sell", 100, 20.0, "2026-10-05"), fill("buy", 100, 25.0, "2026-10-07"),           # -500 on 10-07
        fill("buy", 50, 10.0, "2026-10-08"), fill("sell", 50, 14.0, "2026-10-11"),             # +200, non-spot day
        fill("buy", 100, 10.0, "2026-10-13"), fill("sell", 100, 9.0, "2026-10-14"),            # -100 after last spot
    ]


def _cx(fills=None, **kw):
    c = cfg(**{**SMALL, **kw.pop("c", {})})
    return ctx(fills or _book(), date_from="2026-10-01", date_to=kw.pop("date_to", "2026-10-14"),
               sp=spot(NIFTY=CLOSES), c=c, **kw)


def _block(cx, lines=None):
    return sp.spot_vs_pnl(cx, lines or [], ["NIFTY"])["underlyings"][0]


# ── series ───────────────────────────────────────────────────────────────────────────────

def test_series_exact_daily_cumulative_rolled_and_after_last_spot():
    b = _block(_cx())
    s = b["series"]
    assert s["dates"] == DAYS
    assert s["realised_measured"] == [0, 200, 0, 0, -500, 0, 0, 200, 0]      # 10-11 close rolled to 10-12
    assert s["cum_measured"] == [0, 200, 200, 200, -300, -300, -300, -100, -100]
    assert s["closing_day"] == [0, 1, 0, 0, 1, 0, 0, 1, 0]
    assert s["bias_in"] == [0, 100, 0, -100, -100, 0, 50, 0, 0]
    assert s["big_move_flag"] == [1, 1, 1, 0, 1, 1, 1, 0, 1]
    assert s["reversal_flag"] == [0, 0, 1, 0, 1, 1, 0, 0, 0]
    assert s["adverse_flag"] == [0, 0, 0, 1, 0, 0, 0, 0, 0]
    t = b["totals"]
    assert (t["pnl_rolled_days"], t["pnl_rolled_amount"]) == (1, 200.0)
    assert (t["pnl_after_last_spot"], t["pnl_after_last_spot_count"]) == (-100.0, 1)
    assert t["measured_realised"] == -200.0 and t["n_days"] == 9 and t["n_closing_days"] == 3


def test_expiry_estimate_split_and_flag_off():
    fs = [fill("sell", 100, 50.0, "2026-10-01", symbol="NIFTY26OCT20000CE", strike=20000.0, expiry="2026-10-09")]
    on = _block(_cx(fs))
    assert on["series"]["realised_estimate"][6] == -15000.0 and on["series"]["expiry_flag"][6] == 1
    assert on["totals"]["estimated_realised"] == -15000.0 and on["series"]["closing_day"][6] == 1
    off = _block(_cx(fs, include_est=False))
    assert off["series"]["realised_estimate"] == [0] * 9 and off["totals"]["estimated_realised"] == 0.0


def test_truncation_keeps_stats_on_full_window():
    full = _block(_cx())
    cut = _block(_cx(c={"spot_series_max_points": 30}))
    assert not full["series"]["truncated"]
    # 9 days < 30 so nothing dropped; use the module directly with a tiny ceiling
    cx = _cx()
    cx.cfg = cfg(**{**SMALL, "spot_series_max_points": 30})
    assert cut["series"]["dropped_days"] == 0
    object.__setattr__(cx.cfg, "spot_series_max_points", 5)      # bypass validator to force truncation
    b = _block(cx)
    assert b["series"]["truncated"] and b["series"]["dropped_days"] == 4 and len(b["series"]["dates"]) == 5
    assert b["series"]["cum_total"] == full["series"]["cum_total"][4:]
    assert b["relationship"]["all_days"] == full["relationship"]["all_days"]


def test_no_spot_and_no_trades_blocks():
    cx = ctx(_book(), date_from="2026-10-01", date_to="2026-10-14", sp={}, c=cfg(**SMALL))
    v = sp.spot_vs_pnl(cx, [], ["NIFTY", "BANKNIFTY"])
    a, b = v["underlyings"]
    assert a["reason"] == "spot_unavailable" and a["series"]["dates"] == [] and a["totals"]["measured_realised"] == -200.0
    assert b["reason"] == "no_trades_for_underlying" and b["available"] is False


# ── statistics ───────────────────────────────────────────────────────────────────────────

def test_corr_perfect_plus_minus_one_and_beta():
    up = sp.corr_block([1, 2, 3, 4], [10, 20, 30, 40], 3, 1.96, False)
    assert up["pearson"] == 1.0 and up["spearman"] == 1.0 and up["beta_inr_per_pct"] == 10.0 and up["r2"] == 1.0
    assert up["significant"] is True and up["basis_tag"] == "measured"
    dn = sp.corr_block([1, 2, 3, 4], [40, 30, 20, 10], 3, 1.96, True)
    assert dn["pearson"] == -1.0 and dn["beta_inr_per_pct"] == -10.0 and dn["basis_tag"] == "mixed"


def test_corr_spearman_robust_to_outlier_and_average_rank_ties():
    o = sp.corr_block([1, 2, 3, 4, 5], [1, 2, 3, 4, 1000], 3, 1.96, False)
    assert o["spearman"] == 1.0 and o["pearson"] < 0.9
    t = sp.corr_block([1, 2, 3, 4], [0, 0, 0, 5], 3, 1.96, False)
    assert t["spearman"] == pytest.approx(3.0 / 15 ** 0.5, abs=1e-4)          # hand: 0.7746


def test_corr_gates_and_zero_variance():
    assert sp.corr_block([1, 2], [1, 2], 3, 1.96, False)["reason"] == "insufficient_sample"
    assert sp.corr_block([1, 1, 1], [1, 2, 3], 3, 1.96, False)["reason"] == "no_variation"
    z = sp.corr_block([1, 2, 3], [0, 0, 0], 3, 1.96, False)
    assert z["reason"] == "no_variation" and z["pearson"] is None


def test_corr_matches_independent_implementation_on_fixture():
    b = _block(_cx())
    cd = b["relationship"]["closing_days"]
    ret = [0.990099, -1.492537, 0.0]
    pnl = [200, -500, 200]
    assert cd["n"] == 3 and cd["pearson"] == pytest.approx(statistics.correlation(ret, pnl), abs=1e-3)
    assert cd["beta_inr_per_pct"] == pytest.approx(statistics.linear_regression(ret, pnl).slope, abs=1.0)


def test_below_minimums_are_insufficient_sample_by_default():
    b = _block(ctx(_book(), date_from="2026-10-01", date_to="2026-10-14", sp=spot(NIFTY=CLOSES), c=cfg()))
    assert b["relationship"]["all_days"]["reason"] == "insufficient_sample"
    assert b["alignment"]["verdict"] == "insufficient_sample"
    dn = b["relationship"]["by_direction"][1]                                  # 2 down days < default min 5
    assert dn["available"] is False and dn["total_pnl"] is None and dn["reason"] == "insufficient_sample"


def test_buckets_band_edges_totals_and_share():
    r = _block(_cx())["relationship"]
    up, dn, fl = r["by_direction"]
    assert (up["n_days"], dn["n_days"], fl["n_days"]) == (6, 2, 1)
    assert up["total_pnl"] == 200.0 and dn["total_pnl"] == -500.0 and fl["total_pnl"] == 200.0
    assert dn["hit_rate_pct"] == 0.0 and dn["share_of_total_loss_pct"] == 100.0 and dn["n_closing_days"] == 1
    for b in r["by_direction"] + r["big_move"] + r["expiry_days"]:
        if b["available"]:
            assert b["total_measured"] + b["total_estimate"] == pytest.approx(b["total_pnl"])


def test_band_edge_is_inclusive_and_configurable():
    cl = [("2026-09-30", 64.0), ("2026-10-01", 80.0), ("2026-10-02", 60.0)]       # +25.0% and -25.0% exactly
    def rel(band):
        cx = ctx([fill("buy", 1, 1.0, "2026-10-01")], date_from="2026-10-01", date_to="2026-10-02",
                 sp=spot(NIFTY=cl), c=cfg(**{**SMALL, "spot_flat_band_pct": band}))
        return {x["key"]: x["n_days"] for x in _block(cx)["relationship"]["by_direction"]}
    assert rel(25.0) == {"up": 1, "down": 1, "flat": 0}
    assert rel(25.5) == {"up": 0, "down": 0, "flat": 2}


def test_big_move_union_share_has_no_double_counting_A10():
    r = _block(_cx())["relationship"]
    bm = {b["key"]: b for b in r["big_move"]}
    assert bm["big_down"]["share_of_total_loss_pct"] == 100.0 and bm["reversal"]["share_of_total_loss_pct"] == 100.0
    naive = sum(bm[k]["share_of_total_loss_pct"] or 0 for k in ("big_up", "big_down", "reversal"))
    assert naive == 200.0                                                      # the overlap a naive sum would count
    assert r["big_any"]["share_of_total_loss_pct"] == 100.0 and r["big_any"]["n_days"] == 7
    assert bm["other"]["n_days"] == 2 and bm["other"]["total_pnl"] == 200.0
    obs = {o["id"]: o for o in _block(_cx())["observations"]}
    ev = obs["big_move_concentration"]["evidence"][0]
    assert ev["value"] == 100.0                                                # union share, never 200


def test_expiry_day_buckets_and_observation():
    fs = [fill("sell", 100, 50.0, "2026-10-01", symbol="NIFTY26OCT20000CE", strike=20000.0, expiry="2026-10-09")]
    b = _block(_cx(fs))
    ex = {x["key"]: x for x in b["relationship"]["expiry_days"]}
    assert ex["expiry"]["n_days"] == 1 and ex["expiry"]["total_estimate"] == -15000.0 and ex["expiry"]["total_measured"] == 0.0
    assert "expiry_day_loss" in {o["id"] for o in b["observations"]}
    off = {o["id"] for o in _block(_cx(fs, include_est=False))["observations"]}
    assert "expiry_day_loss" not in off                                        # no estimate, nothing lost on expiry day


# ── alignment ────────────────────────────────────────────────────────────────────────────

def test_alignment_fixture_arithmetic_and_no_lookahead():
    a = _block(_cx())["alignment"]
    assert (a["with_n"], a["against_n"], a["flat_market_n"], a["flat_book_n"]) == (3, 1, 0, 5)
    assert a["pct_with"] == 75.0 and a["with_units_pts"] == 60000.0 and a["against_units_pts"] == -10000.0
    assert a["net_units_pts"] == 50000.0 and a["by_bias"]["bullish"]["n"] == 2 and a["by_bias"]["bearish"]["n"] == 2
    assert a["by_bias"]["bearish"]["mean_ret_pct"] == pytest.approx((0.5 - 1.492537) / 2, abs=1e-3)
    assert a["verdict"] == "no_clear_lean" and "independent" in a["caveat"]
    # a fill made ON a day does not change that day's start-of-day bias (10-02 entry shows on 10-02 only via EOD 10-01)
    assert _block(_cx())["series"]["bias_in"][0] == 0


def test_wilson_interval_value_and_empty():
    lo, hi = sp.wilson(3, 4, 1.96)
    assert lo == pytest.approx(30.06, abs=0.05) and hi == pytest.approx(95.44, abs=0.05)
    assert sp.wilson(0, 0, 1.96) == (None, None)


def _days(n_with, n_against, bias=10):
    out = []
    for i in range(n_with + n_against):
        r = 1.0 if i < n_with else -1.0
        out.append(an.SpotDay(D("2026-10-01"), 101.0 if r > 0 else 99.0, 100.0, r, None, bias, [], 0.0))
    return out


@pytest.mark.parametrize("w,a,verdict", [(15, 0, "with_market"), (0, 15, "against_market"), (8, 8, "no_clear_lean"),
                                         (4, 1, "insufficient_sample")])
def test_alignment_verdict_paths(w, a, verdict):
    assert sp._alignment(cfg(), _days(w, a))["verdict"] == verdict


def test_alignment_excludes_flat_market_and_flat_book_and_signs():
    ds = [an.SpotDay(D("2026-10-01"), 100.1, 100.0, 0.1, None, 10, [], 0.0),       # flat market
          an.SpotDay(D("2026-10-02"), 102.0, 100.0, 2.0, None, 0, [], 0.0),        # flat book
          an.SpotDay(D("2026-10-05"), 102.0, 100.0, 2.0, None, -10, [], 0.0)]      # bearish into up day: against
    a = sp._alignment(cfg(), ds)
    assert (a["with_n"], a["against_n"], a["flat_market_n"], a["flat_book_n"]) == (0, 1, 1, 1)
    assert a["against_units_pts"] == -20.0


def test_observation_triggers_gated_and_capped():
    obs = [o["id"] for o in _block(_cx())["observations"]]
    assert "loses_on_down_days" in obs and "low_sample" in obs and len(obs) <= 6
    gated = [o["id"] for o in _block(ctx(_book(), date_from="2026-10-01", date_to="2026-10-14",
                                         sp=spot(NIFTY=CLOSES), c=cfg()))["observations"]]
    assert "low_sample" in gated                                                   # names what is withheld
    assert not {"book_against_market", "book_with_market", "negative_beta", "loses_on_down_days"} & set(gated)
    one = _block(_cx(c={"spot_obs_max": 1}))["observations"]
    assert len(one) == 1 and "over-read" in one[0]["text"]
    for o in obs_all(_cx()):
        assert "because" not in o["text"] and "caused" not in o["text"]
    hi = {o["id"] for o in _block(_cx(c={"spot_obs_concentration_pct": 100.0}))["observations"]}
    assert "big_move_concentration" in hi                                          # 100 >= 100
    cx = _cx()
    object.__setattr__(cx.cfg, "spot_obs_concentration_pct", 100.5)
    assert "big_move_concentration" not in {o["id"] for o in _block(cx)["observations"]}


def obs_all(cx):
    return _block(cx)["observations"]


# ── unrealised snapshot ──────────────────────────────────────────────────────────────────

def _line(sym, pf, pt, unreal, oq=100, und="NIFTY"):
    return an.PnlLine(sym, und, "2026-10", D(pf), D(pt), 0.0, oq, "Long", unrealized_pnl=unreal)


OPEN = [fill("buy", 100, 10.0, "2026-10-12", symbol="NIFTY26OCT20000CE"),
        fill("buy", 100, 10.0, "2026-10-12", symbol="NIFTY26OCT20100CE", strike=20100.0)]


def test_snapshot_latest_period_not_summed_null_not_zero_missing_and_stale():
    lines = [_line("NIFTY26OCT20000CE", "2026-10-01", "2026-10-09", 100.0),
             _line("NIFTY26OCT20000CE", "2026-10-01", "2026-10-12", 300.0),
             _line("NIFTY26OCT20100CE", "2026-10-01", "2026-10-12", None)]
    cx = _cx(OPEN)
    s = _block(cx, lines)["unrealised_snapshot"]
    assert s["available"] and s["amount"] == 300.0 and s["n_symbols"] == 1 and s["as_of"] == "2026-10-12"
    assert (s["fifo_open_symbols"], s["symbols_missing_in_sheet"], s["days_behind_spot"], s["stale"]) == (2, 1, 1, False)
    old = _block(cx, [_line("NIFTY26OCT20000CE", "2026-09-01", "2026-10-01", 50.0)])["unrealised_snapshot"]
    assert old["stale"] is True and old["reason"] == "sheet_stale" and old["available"] is True
    zero_q = _block(cx, [_line("NIFTY26OCT20000CE", "2026-10-01", "2026-10-12", 5.0, oq=0)])["unrealised_snapshot"]
    assert zero_q["available"] is False


def test_snapshot_reasons_and_totals_and_isolation_from_stats():
    cx = _cx(OPEN)
    assert _block(cx, [])["unrealised_snapshot"]["reason"] == "no_pnl_sheet"
    flat = _block(_cx(), [_line("NIFTY26OCT20000CE", "2026-10-01", "2026-10-12", None)])
    assert flat["unrealised_snapshot"]["reason"] == "no_open_positions"
    lines = [_line("NIFTY26OCT20000CE", "2026-10-01", "2026-10-12", 300.0)]
    with_l, without = _block(cx, lines), _block(cx, [])
    assert with_l["relationship"] == without["relationship"] and with_l["series"] == without["series"]
    t = with_l["totals"]
    assert t["realised_plus_unrealised"] == pytest.approx(t["measured_realised"] + t["estimated_realised"] + 300.0)
    assert without["totals"]["realised_plus_unrealised"] is None


# ── what-if rules ────────────────────────────────────────────────────────────────────────

def _rules(cx):
    view = sp.spot_vs_pnl(cx, [], ["NIFTY"])
    rs, vt = spot_rules(cx, view)
    return {r["id"]: r for r in rs}, vt


def test_expiry_proximity_rule_arithmetic():
    fs = [fill("buy", 10, 50.0, "2026-10-02", symbol="NIFTY26OCT20000CE", strike=20000.0, expiry="2026-10-09"),
          fill("sell", 10, 60.0, "2026-10-05", symbol="NIFTY26OCT20000CE", strike=20000.0, expiry="2026-10-09"),
          fill("buy", 10, 100.0, "2026-10-08", symbol="NIFTY26OCT20100CE", strike=20100.0, expiry="2026-10-09"),
          fill("sell", 10, 80.0, "2026-10-09", symbol="NIFTY26OCT20100CE", strike=20100.0, expiry="2026-10-09")]
    r, vt = _rules(_cx(fs, c={"suggestion_min_closed_trades": 1}))
    w = r["expiry_proximity_entries"]["what_if"]
    assert r["expiry_proximity_entries"]["title"].startswith("What-if:")
    assert (w["baseline_pnl"], w["delta"], w["whatif_pnl"], w["trades_removed"]) == (-100.0, 200.0, 100.0, 1)
    assert list(vt["expiry_proximity_entries"].values()) == [1.0]


def test_counter_move_rule_arithmetic():
    fs = [fill("sell", 10, 100.0, "2026-10-02", symbol="NIFTY26OCT20000CE"),         # bearish after big up day
          fill("buy", 10, 120.0, "2026-10-05", symbol="NIFTY26OCT20000CE"),          # -200
          fill("buy", 10, 50.0, "2026-10-02", symbol="NIFTY26OCT20100CE", strike=20100.0),   # bullish, aligned
          fill("sell", 10, 60.0, "2026-10-05", symbol="NIFTY26OCT20100CE", strike=20100.0),  # +100
          fill("sell", 10, 100.0, "2026-10-07", symbol="NIFTY26OCT20200CE", strike=20200.0),  # prev day +0.5%: not big
          fill("buy", 10, 90.0, "2026-10-08", symbol="NIFTY26OCT20200CE", strike=20200.0)]    # +100
    r, vt = _rules(_cx(fs, c={"suggestion_min_closed_trades": 1}))
    w = r["counter_move_entries"]["what_if"]
    assert (w["baseline_pnl"], w["delta"], w["trades_removed"]) == (0.0, 200.0, 1)


BIAS_BOOK = [fill("buy", 100, 10.0, "2026-10-01"), fill("buy", 100, 10.0, "2026-10-02"),
             fill("buy", 100, 10.0, "2026-10-05"), fill("sell", 300, 12.0, "2026-10-06")]


def test_bias_limit_and_illustrative_rule():
    cx = _cx(BIAS_BOOK, c={"suggestion_min_closed_trades": 1})
    r, vt = _rules(cx)
    b = r["bias_limit"]
    assert b["parameter"]["value"] == 200 and b["title"] == "What-if: net directional bias capped at 200 units"
    assert (b["what_if"]["baseline_pnl"], b["what_if"]["delta"], b["what_if"]["whatif_pnl"]) == (600.0, -200.0, 400.0)
    h = r["bias_hedge_illustrative"]
    assert h["status"] == "illustrative" and h["what_if"] is None and h["parameter"]["value"] == -10000.0
    assert "bias_hedge_illustrative" not in vt and "bias_limit" in vt


def test_rules_in_suggestions_combined_sorted_and_same_numbers():
    cx = _cx(BIAS_BOOK, c={"suggestion_min_closed_trades": 1})
    lots = an.LotInfo()
    out = suggestions(cx, an.overtrading(cx, []), an.buildup(cx, lots),
                      {"ledger": {"available": False}, "cash_series": [], "trap": {"days": 0},
                       "cash": {"min": None}, "stops": {"rows": []}}, lots)
    ids = [x["id"] for x in out["rules"]]
    assert set(SPOT_RULE_IDS) <= set(ids)
    assert out["rules"][-1]["status"] == "illustrative" and ids[-1] == "bias_hedge_illustrative"
    assert "bias_limit" in out["combined"]["rules_included"]
    assert "bias_hedge_illustrative" not in out["combined"]["rules_included"]
    mine, _ = _rules(cx)
    assert {x["id"]: x for x in out["rules"]}["bias_limit"]["what_if"] == mine["bias_limit"]["what_if"]


def test_spot_rules_insufficient_on_tiny_input_and_without_spot():
    tiny = ctx([fill("buy", 1, 1.0, "2026-10-01")], date_from="2026-10-01", date_to="2026-10-05",
               sp=spot(NIFTY=CLOSES), c=cfg())
    rs, _ = spot_rules(tiny, sp.spot_vs_pnl(tiny, [], ["NIFTY"]))
    assert {r["id"]: r["status"] for r in rs} == {i: "insufficient_data" for i in SPOT_RULE_IDS}
    nospot = ctx(BIAS_BOOK, date_from="2026-10-01", date_to="2026-10-12", sp={}, c=cfg(suggestion_min_closed_trades=1))
    rs2 = {r["id"]: r["status"] for r in spot_rules(nospot, sp.spot_vs_pnl(nospot, [], ["NIFTY"]))[0]}
    assert rs2["bias_limit"] == "insufficient_data" and rs2["counter_move_entries"] == "insufficient_data"


# ── service / API / schema ───────────────────────────────────────────────────────────────

TODAY = date(2026, 10, 14)
SPOT_ROWS = [("NIFTY", d, c) for d, c in CLOSES]


def _svc(db):
    return FnoTradeAnalyticsService(db, today=TODAY)


def test_empty_user_no_data_and_bad_params(db_session):
    r = _svc(db_session).spot_vs_pnl("nobody", AnalyticsParams())
    assert r.available is False and r.reason == "no_data"
    seed(db_session, "u", _book(), SPOT_ROWS)
    assert _svc(db_session).spot_vs_pnl("u", AnalyticsParams(expiry_month=12)).reason == "no_trades_in_scope"
    assert _svc(db_session).spot_vs_pnl("u", AnalyticsParams(date_from=date(2026, 10, 9), date_to=date(2026, 10, 8))
                                        ).reason == "no_trades_in_scope"
    assert _svc(db_session).spot_vs_pnl("u", AnalyticsParams(expiry_month=10)).available


def test_response_validates_schema_all_underlyings_and_isolation(db_session):
    seed(db_session, "u", _book(), SPOT_ROWS)
    seed(db_session, "other", [fill("buy", 10, 10.0, "2026-10-01", symbol="BANKNIFTY26OCT50000CE",
                                    underlying="BANKNIFTY")])
    r = _svc(db_session).spot_vs_pnl("u", AnalyticsParams(date_from=date(2026, 4, 1)))   # early date_from accepted
    assert r.available and [u.underlying for u in r.underlyings] == ["NIFTY", "BANKNIFTY"]
    n, bn = r.underlyings
    assert n.available and bn.available is False and bn.reason == "no_trades_for_underlying"
    sch.SpotVsPnlResponse.model_validate(r.model_dump())
    assert {x.id for x in r.improvement.rules} <= set(SPOT_RULE_IDS) and r.improvement.disclaimer
    assert r.info.assumptions and r.delta1_note
    one = _svc(db_session).spot_vs_pnl("u", AnalyticsParams(underlying="NIFTY"))
    assert [u.underlying for u in one.underlyings] == ["NIFTY"]
    assert _svc(db_session).spot_vs_pnl("other", AnalyticsParams()).reason == "spot_unavailable"


def test_pnl_sheet_unrealised_reaches_snapshot_through_service(db_session):
    from rita.models.fno_import import FnoPnlLineModel
    fs = OPEN
    seed(db_session, "u", fs, SPOT_ROWS)
    seed(db_session, "u", [], [], pnl_lines=[("NIFTY26OCT20000CE", "NIFTY", "2026-10", "2026-10-01", "2026-10-12", 0.0, 100, "Long")])
    row = db_session.query(FnoPnlLineModel).filter_by(user_id="u").one()
    row.unrealized_pnl = 450.0
    db_session.commit()
    s = _svc(db_session).spot_vs_pnl("u", AnalyticsParams(date_to=date(2026, 10, 14))).underlyings[0].unrealised_snapshot
    assert s.available and s.amount == 450.0 and s.n_symbols == 1


def test_service_is_read_only(db_session, monkeypatch):
    from sqlalchemy.orm import Session
    seed(db_session, "u", _book(), SPOT_ROWS)

    def boom(*a, **k):
        raise AssertionError("write attempted")

    for attr in ("commit", "add", "add_all", "delete", "merge"):
        monkeypatch.setattr(Session, attr, boom)
    assert _svc(db_session).spot_vs_pnl("u", AnalyticsParams()).available


@pytest.fixture()
def user(client, db_session):
    from rita.api.experience import fno_trade_analytics as router_mod
    from rita.auth import get_current_user
    from rita.main import app
    u = MagicMock()
    u.id = "u-api"
    app.dependency_overrides[get_current_user] = lambda: u
    app.dependency_overrides[router_mod._get_service] = lambda: FnoTradeAnalyticsService(db_session, today=TODAY)
    yield u
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(router_mod._get_service, None)


URL = "/api/v1/experience/fno/trade-analysis/analytics/spot-vs-pnl"


def test_api_auth_422_empty_and_payload(client, user, db_session):
    r = client.get(URL)
    assert r.status_code == 200 and r.json()["reason"] == "no_data"
    assert client.get(URL + "?underlying=FINNIFTY").status_code == 422
    seed(db_session, "u-api", _book(), SPOT_ROWS)
    r = client.get(URL + "?underlying=NIFTY&expiry_month=10")
    assert r.status_code == 200 and r.json()["underlyings"][0]["series"]["dates"] == DAYS


def test_api_requires_auth(client):
    assert client.get(URL).status_code == 401


# ── config (widened scope, new keys, validators) ───────────────────────────────────────────

def test_expiry_months_widened_and_base_yaml_parity():
    from pathlib import Path

    import yaml
    base = yaml.safe_load((Path(__file__).resolve().parents[2] / "config/base.yaml").read_text())["trade_analysis"]
    full = [4, 5, 6, 7, 8, 9, 10, 11]
    assert TradeAnalysisSettings().expiry_months == full and base["expiry_months"] == full
    for k in ("spot_flat_band_pct", "spot_rel_min_days", "spot_rel_min_closing_days", "spot_rel_min_bucket_days",
              "spot_rel_min_bias_days", "spot_rel_ci_z", "sheet_snapshot_stale_days", "expiry_proximity_days",
              "spot_series_max_points", "spot_obs_max", "spot_obs_concentration_pct"):
        assert base[k] == getattr(TradeAnalysisSettings(), k), k
    assert set(base) == set(TradeAnalysisSettings.model_fields)


@pytest.mark.parametrize("kw", [
    {"expiry_months": []}, {"expiry_months": [9, 9]}, {"expiry_months": [10, 9]}, {"expiry_months": [0, 5]},
    {"expiry_months": [5, 13]}, {"spot_flat_band_pct": -0.1}, {"spot_rel_min_days": 2}, {"spot_rel_min_closing_days": 2},
    {"spot_rel_min_bucket_days": 0}, {"spot_rel_min_bias_days": 0}, {"spot_rel_ci_z": 0}, {"sheet_snapshot_stale_days": -1},
    {"expiry_proximity_days": -1}, {"spot_series_max_points": 29}, {"spot_obs_max": 0},
    {"spot_obs_concentration_pct": 100.1}, {"spot_obs_concentration_pct": -1}])
def test_new_config_validators_reject(kw):
    with pytest.raises(ValidationError):
        TradeAnalysisSettings(**kw)


def test_months_4_to_11_accepted_by_filter_12_not_in_config(db_session):
    seed(db_session, "u", _book(), SPOT_ROWS)
    svc = _svc(db_session)
    for m in (4, 8, 10):
        assert svc.spot_vs_pnl("u", AnalyticsParams(expiry_month=m)).reason != "no_data"
    assert svc.spot_vs_pnl("u", AnalyticsParams(expiry_month=12)).reason == "no_trades_in_scope"
    assert svc.spot_vs_pnl("u", AnalyticsParams()).filter.expiry_months == [4, 5, 6, 7, 8, 9, 10, 11]


def test_widened_scope_reconciliation_old_symbols_unchanged_added_symbol_extra_row():
    old = [fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 12.0, "2026-10-02")]
    aug = [fill("buy", 10, 5.0, "2026-10-01", symbol="NIFTY26AUG20000CE", expiry="2026-08-25"),
           fill("sell", 10, 6.0, "2026-10-02", symbol="NIFTY26AUG20000CE", expiry="2026-08-25")]
    a = an.reconciliation(ctx(old, date_from="2026-10-01", date_to="2026-10-05"), [])
    b = an.reconciliation(ctx(old + aug, date_from="2026-10-01", date_to="2026-10-05"), [])
    by_a = {r["symbol"]: r for r in a["rows"]}
    by_b = {r["symbol"]: r for r in b["rows"]}
    assert set(by_b) - set(by_a) == {"NIFTY26AUG20000CE"}
    for s_, row in by_a.items():
        assert by_b[s_]["fifo_measured"] == row["fifo_measured"] and by_b[s_]["gap_measured"] == row["gap_measured"]
