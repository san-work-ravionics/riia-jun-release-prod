"""F42 P4 (Spot vs P&L) — independent QA probes.

Complements the Engineer's test_f42_p31_spot_pnl*.py without duplicating them: every statistic is
re-derived here with a DIFFERENT method (rank-by-counting, bisection of the Wilson score equation,
statistics.correlation / linear_regression) and compared with the module output.  Synthetic data
only (invented symbols, round numbers, built in code); nothing is read from disk or live-data/.

Confirmed defects are strict-xfail tests (see ``DEFECT_`` names): they fail today and will flip to
XPASS(strict) -> a red build once the source is fixed, which is the cue to drop the marker.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import statistics
import subprocess
from datetime import date, timedelta
from pathlib import Path
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

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 10, 14)


# ── builders ──────────────────────────────────────────────────────────────────────────────


def _bdays(start: str, n: int) -> list[str]:
    out, d = [], D(start)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _lcg(seed_: int):
    s = seed_
    while True:
        s = (s * 1103515245 + 12345) % (2 ** 31)
        yield s / 2 ** 31


def _daily_book(days: list[str], ks: list):
    """One same-day round trip per day with gross P&L k (qty 1); None = no trade that day."""
    out = []
    for d, k in zip(days, ks):
        if k is None:
            continue
        out.append(fill("buy", 1, 100.0, d, "10:00"))
        out.append(fill("sell", 1, 100.0 + k, d, "11:00"))
    return out


def _walk(n: int, seed_: int, start: float = 20000.0) -> list[float]:
    g, c, out = _lcg(seed_), start, []
    for _ in range(n):
        c = round(c * (1 + (next(g) - 0.5) * 0.03), 2)
        out.append(c)
    return out


def _pairs(days: list[str], closes: list[float]):
    return list(zip(days, closes))


def _run(fills, closes, date_from, date_to, c=None, include_est=True, und="NIFTY"):
    cx = ctx(fills, date_from=date_from, date_to=date_to, include_est=include_est, sp=spot(**{und: closes}),
             c=c or cfg())
    return cx, sp.spot_vs_pnl(cx, [], [und])["underlyings"][0]


def _avg_rank(v):
    return [1 + sum(1 for y in v if y < x) + (sum(1 for y in v if y == x) - 1) / 2 for x in v]


def _oracle(x, y):
    """pearson, spearman, beta from stdlib only, independent of the module's code path."""
    pe = statistics.correlation(x, y)
    sr = statistics.correlation(_avg_rank(x), _avg_rank(y))
    return pe, sr, statistics.linear_regression(x, y).slope


def _wilson_bisect(k, n, z):
    """Bounds of the Wilson score interval by bisecting (p_hat - p)^2 = z^2 p(1-p)/n."""
    ph = k / n

    def g(p):
        return (ph - p) ** 2 - z * z * p * (1 - p) / n

    lo, hi = 0.0, ph
    for _ in range(200):                                    # g(0) > 0 > g(ph): root in between
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if g(mid) > 0 else (lo, mid)
    low = (lo + hi) / 2
    lo, hi = ph, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if g(mid) > 0 else (mid, hi)
    return low * 100, (lo + hi) / 2 * 100


# ── statistics vs independent recomputation ───────────────────────────────────────────────────────


@pytest.mark.parametrize("seed_", [1, 7, 42])
def test_pipeline_correlation_beta_spearman_match_independent_oracle(seed_):
    days = _bdays("2026-09-01", 30)
    closes = _walk(31, seed_)                                  # 31 closes -> 30 returns from 09-01 on
    days = _bdays("2026-08-31", 31)
    g = _lcg(seed_ + 100)
    ks = []
    for i in range(30):
        u = next(g)
        ks.append(None if u < 0.25 else (50.0 if u < 0.45 else round((u - 0.5) * 400)))   # ties at 50 and gaps
    book = _daily_book(days[1:], ks)
    cx, b = _run(book, _pairs(days, closes), "2026-09-01", "2026-10-30")
    ret = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, 31)]
    pnl = [0.0 if k is None else float(k) for k in ks]
    pe, sr, beta = _oracle(ret, pnl)
    al = b["relationship"]["all_days"]
    assert al["n"] == 30 and al["pearson"] == pytest.approx(pe, abs=2e-4)
    assert al["spearman"] == pytest.approx(sr, abs=2e-4)
    assert al["beta_inr_per_pct"] == pytest.approx(beta, abs=0.02) and al["r2"] == pytest.approx(pe ** 2, abs=2e-4)
    idx = [i for i, k in enumerate(ks) if k is not None]
    assert len(idx) >= 10
    pe2, sr2, beta2 = _oracle([ret[i] for i in idx], [pnl[i] for i in idx])
    cd = b["relationship"]["closing_days"]
    assert cd["n"] == len(idx) and cd["pearson"] == pytest.approx(pe2, abs=2e-4)
    assert cd["spearman"] == pytest.approx(sr2, abs=2e-4) and cd["beta_inr_per_pct"] == pytest.approx(beta2, abs=0.02)


def test_spearman_with_ties_in_both_variables_matches_hand_value():
    x, y = [1, 2, 2, 3, 3, 3], [5, 5, 7, 7, 9, 9]
    blk = sp.corr_block(x, y, 3, 1.96, False)
    pe, sr, _ = _oracle(x, y)
    assert blk["spearman"] == pytest.approx(sr, abs=1e-4) and blk["pearson"] == pytest.approx(pe, abs=1e-4)
    # hand: ranks x = 1,2.5,2.5,5,5,5 ; ranks y = 1.5,1.5,3.5,3.5,5.5,5.5
    assert _avg_rank(x) == [1, 2.5, 2.5, 5, 5, 5] and _avg_rank(y) == [1.5, 1.5, 3.5, 3.5, 5.5, 5.5]


def test_beta_and_pearson_scaling_invariance():
    x = [0.5, -1.0, 2.0, -0.2, 1.1, 0.0]
    y = [10.0, -30.0, 55.0, 5.0, 20.0, -4.0]
    a = sp.corr_block(x, y, 3, 1.96, False)
    b = sp.corr_block(x, [v * 1000 for v in y], 3, 1.96, False)
    c = sp.corr_block([v * 2 for v in x], y, 3, 1.96, False)
    assert b["pearson"] == a["pearson"] and b["spearman"] == a["spearman"]
    assert b["beta_inr_per_pct"] == pytest.approx(a["beta_inr_per_pct"] * 1000, rel=1e-4)
    assert c["beta_inr_per_pct"] == pytest.approx(a["beta_inr_per_pct"] / 2, rel=1e-3)
    neg = sp.corr_block(x, [-v for v in y], 3, 1.96, False)
    assert neg["pearson"] == -a["pearson"] and neg["spearman"] == -a["spearman"]


def test_significance_flag_flips_exactly_at_z_over_sqrt_n():
    x, y = [1, 2, 3, 4, 5, 6], [2, 1, 4, 3, 6, 5]
    r = sp.corr_block(x, y, 3, 1.96, False)["pearson"]
    n = len(x)
    z_edge = abs(r) * math.sqrt(n)
    assert sp.corr_block(x, y, 3, z_edge - 0.01, False)["significant"] is True
    assert sp.corr_block(x, y, 3, z_edge + 0.01, False)["significant"] is False


@pytest.mark.parametrize("n,expect_value", [(9, False), (10, True), (11, True)])
def test_correlation_gate_is_inclusive_at_min_n(n, expect_value):
    x = [float(i % 4) + 0.5 * (i % 3) for i in range(n)]
    y = [float((i * 7) % 5) for i in range(n)]
    blk = sp.corr_block(x, y, 10, 1.96, False)
    assert (blk["pearson"] is not None) is expect_value
    assert blk["reason"] == (None if expect_value else "insufficient_sample") and blk["min_required"] == 10
    if not expect_value:
        assert blk["spearman"] is None and blk["beta_inr_per_pct"] is None and blk["r2"] is None \
            and blk["significant"] is None


@pytest.mark.parametrize("k,n", [(0, 10), (1, 10), (5, 10), (9, 10), (10, 10), (3, 4), (17, 40), (60, 100)])
@pytest.mark.parametrize("z", [1.0, 1.96, 2.576])
def test_wilson_matches_bisected_score_interval(k, n, z):
    lo, hi = sp.wilson(k, n, z)
    blo, bhi = _wilson_bisect(k, n, z)
    assert lo == pytest.approx(blo, abs=1e-6) and hi == pytest.approx(bhi, abs=1e-6)
    assert -1e-9 <= lo <= k / n * 100 + 1e-9 and k / n * 100 - 1e-9 <= hi <= 100.0 + 1e-9


def _sd(ret, bias, close=None, prev=None, d="2026-10-01"):
    prev = prev if prev is not None else 20000.0
    close = close if close is not None else prev * (1 + ret / 100)
    return an.SpotDay(D(d), close, prev, ret, None, bias, [], 0.0)


def test_alignment_scoring_boundaries_units_and_by_bias_by_hand():
    c = cfg(spot_flat_band_pct=0.5, spot_rel_min_bias_days=1)
    days = [_sd(0.5, 10, 20100.0, 20000.0),       # |r| == band -> scored, with (bias>0, up)
            _sd(-0.5, 10, 19900.0, 20000.0),      # == band, against
            _sd(0.4999, 10),                      # below band -> flat market
            _sd(2.0, 0, 20400.0, 20000.0),        # flat book
            _sd(-1.0, -4, 19800.0, 20000.0),      # bearish book, down day -> with
            _sd(1.0, -4, 20200.0, 20000.0)]       # bearish book, up day -> against
    a = sp._alignment(c, days)
    assert (a["with_n"], a["against_n"], a["flat_market_n"], a["flat_book_n"]) == (2, 2, 1, 1)
    assert a["days_with_bias"] == 5
    assert a["with_units_pts"] == pytest.approx(10 * 100 + (-4) * (-200))             # 1000 + 800
    assert a["against_units_pts"] == pytest.approx(10 * (-100) + (-4) * 200)           # -1000 - 800
    assert a["net_units_pts"] == 0.0 and a["pct_with"] == 50.0
    assert a["by_bias"]["bullish"]["n"] == 3 and a["by_bias"]["bearish"]["n"] == 2
    assert a["by_bias"]["bullish"]["mean_ret_pct"] == pytest.approx((0.5 - 0.5 + 0.4999) / 3, abs=1e-3)
    assert a["by_bias"]["bearish"]["mean_ret_pct"] == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("scored,expect", [(9, "insufficient_sample"), (10, "with_market"), (11, "with_market")])
def test_alignment_min_days_gate_is_inclusive(scored, expect):
    days = [_sd(1.0, 5) for _ in range(scored)]
    assert sp._alignment(cfg(spot_rel_min_bias_days=10), days)["verdict"] == expect


def test_alignment_wilson_fields_equal_bisected_interval():
    days = [_sd(1.0, 5) for _ in range(7)] + [_sd(-1.0, 5) for _ in range(5)]
    a = sp._alignment(cfg(spot_rel_min_bias_days=1), days)
    blo, bhi = _wilson_bisect(7, 12, 1.96)
    assert a["pct_with_ci_low"] == pytest.approx(blo, abs=0.01) and a["pct_with_ci_high"] == pytest.approx(bhi, abs=0.01)
    assert a["verdict"] == "no_clear_lean"


# ── buckets: partitions, boundaries, ties ─────────────────────────────────────────────────────────

_PART_DAYS = _bdays("2026-09-01", 13)
_PART_CLOSES = [20000.0, 20100.0, 20050.0, 20250.0, 20250.0, 20000.0, 20500.0, 20000.0, 20010.0, 19900.0,
                19900.0, 20300.0, 20310.0]


def _part_book():
    return _daily_book(_PART_DAYS[1:], [10.0, -20.0, None, 30.0, -40.0, 50.0, -60.0, 0.0, 70.0, None, -80.0, 90.0])


def test_direction_and_big_move_buckets_partition_the_days_and_the_pnl():
    cx, b = _run(_part_book(), _pairs(_PART_DAYS, _PART_CLOSES), "2026-09-02", "2026-09-30",
                 c=cfg(spot_rel_min_bucket_days=1))
    rel, n = b["relationship"], b["totals"]["n_days"]
    total = b["totals"]["measured_realised"]
    assert n == 12
    for group in (rel["by_direction"], rel["expiry_days"]):
        assert sum(x["n_days"] for x in group) == n
        assert sum(x["total_pnl"] or 0.0 for x in group) == pytest.approx(total)
    other = next(x for x in rel["big_move"] if x["key"] == "other")
    assert rel["big_any"]["n_days"] + other["n_days"] == n
    assert rel["big_any"]["total_pnl"] + other["total_pnl"] == pytest.approx(total)
    flat = next(x for x in rel["by_direction"] if x["key"] == "flat")
    assert flat["n_days"] == 5                                  # -0.249%, 0.0%, +0.05%, 0.0%, +0.049%
    assert sum(x["n_closing_days"] for x in rel["by_direction"]) == b["totals"]["n_closing_days"]


def test_share_of_total_loss_sums_to_100_over_a_partition():
    cx, b = _run(_part_book(), _pairs(_PART_DAYS, _PART_CLOSES), "2026-09-02", "2026-09-30",
                 c=cfg(spot_rel_min_bucket_days=1))
    shares = [x["share_of_total_loss_pct"] for x in b["relationship"]["by_direction"]]
    assert sum(s for s in shares if s is not None) == pytest.approx(100.0, abs=0.05)
    hit = {x["key"]: x["hit_rate_pct"] for x in b["relationship"]["by_direction"]}
    assert all(v is None or 0.0 <= v <= 100.0 for v in hit.values())


def test_big_move_threshold_is_inclusive_and_just_below_is_not_big():
    closes = [20000.0, 20200.0, 20200.0 * 0.9899, 20200.0 * 0.9899 * 1.0101]     # +1.0%, -1.01%, +1.01%
    days = _bdays("2026-09-01", 4)
    cx, b = _run([fill("buy", 1, 1.0, days[1])], _pairs(days, closes), "2026-09-02", "2026-09-30")
    assert b["series"]["big_move_flag"][0] == 1                                    # +1.0000000000000009 >= 1.0
    cx2, b2 = _run([fill("buy", 1, 1.0, days[1])], _pairs(days, [20000.0, 20199.8, 20199.8, 20199.8]),
                   "2026-09-02", "2026-09-30")
    assert b2["series"]["big_move_flag"] == [0, 0, 0]                              # 0.999% is below
    assert b["series"]["reversal_flag"][1] == 1                                    # +1% then -1.01%: reversal


@pytest.mark.xfail(strict=True, reason="QA-D1: float error at exact band/threshold boundary")
def test_DEFECT_float_error_drops_an_exact_band_move_into_flat():
    """20000 -> 20050 is exactly +0.25% (the default band) but (c1/c0-1)*100 = 0.24999999999999467,
    so the day is classed flat and is not scored: the documented rule is 'r >= band' (inclusive)."""
    days = _bdays("2026-09-01", 3)
    book = [fill("buy", 1, 1.0, days[0])]
    cx, b = _run(book, _pairs(days, [20000.0, 20050.0, 20050.0]), "2026-09-02", "2026-09-30",
                 c=cfg(spot_rel_min_bucket_days=1))
    up = next(x for x in b["relationship"]["by_direction"] if x["key"] == "up")
    assert up["n_days"] == 1                                                       # documented: up if r >= band


@pytest.mark.xfail(strict=True, reason="QA-D2: flat band 0 puts a 0.00% day in BOTH up and down and scores it 'against'")
def test_DEFECT_zero_band_zero_return_day_is_double_counted():
    days = _bdays("2026-09-01", 4)
    book = [fill("buy", 1, 1.0, days[0])]
    cx, b = _run(book, _pairs(days, [20000.0, 20100.0, 20100.0, 20200.0]), "2026-09-02", "2026-09-30",
                 c=cfg(spot_flat_band_pct=0.0, spot_rel_min_bucket_days=1, spot_rel_min_bias_days=1))
    rel = b["relationship"]["by_direction"]
    assert sum(x["n_days"] for x in rel) == b["totals"]["n_days"]                  # a partition, never overlapping
    al = b["alignment"]
    assert al["with_n"] + al["against_n"] + al["flat_market_n"] + al["flat_book_n"] == b["totals"]["n_days"]
    assert al["against_n"] == 0                                                    # a 0.00% day cannot be 'against'


# ── roll-forward, after-last-spot, identity ───────────────────────────────────────────────────────


def test_weekend_closes_roll_forward_once_per_date_and_identity_holds():
    # spot: Thu 10-01, Fri 10-02, Mon 10-05, Tue 10-06 ; closes land on Sat 10-03 (x2) and Wed 10-07 (after last spot)
    closes = [("2026-10-01", 20000.0), ("2026-10-02", 20100.0), ("2026-10-05", 20000.0), ("2026-10-06", 20100.0)]
    fs = [fill("buy", 10, 10.0, "2026-10-02"), fill("sell", 4, 12.0, "2026-10-03"), fill("sell", 6, 13.0, "2026-10-03"),
          fill("buy", 10, 10.0, "2026-10-06"), fill("sell", 10, 9.0, "2026-10-07")]
    cx = ctx(fs, date_from="2026-10-02", date_to="2026-10-08", sp=spot(NIFTY=closes), c=cfg())
    b = sp.spot_vs_pnl(cx, [], ["NIFTY"])["underlyings"][0]
    s, t = b["series"], b["totals"]
    assert s["dates"] == ["2026-10-02", "2026-10-05", "2026-10-06"]
    assert s["realised_measured"] == [0.0, 26.0, 0.0]                              # 8 + 18 rolled onto Monday
    assert (t["pnl_rolled_days"], t["pnl_rolled_amount"]) == (1, 26.0)             # one date, summed
    assert (t["pnl_after_last_spot"], t["pnl_after_last_spot_count"]) == (-10.0, 1)
    assert sum(s["realised_measured"]) + sum(s["realised_estimate"]) + t["pnl_after_last_spot"] \
        == pytest.approx(t["measured_realised"] + t["estimated_realised"])
    assert s["cum_measured"][-1] == 26.0                                           # cumulative excludes after-last-spot


def test_close_before_first_return_day_lands_on_first_day_and_is_counted_as_rolled():
    closes = [("2026-10-05", 20000.0), ("2026-10-06", 20100.0), ("2026-10-07", 20000.0)]
    fs = [fill("buy", 1, 10.0, "2026-10-01"), fill("sell", 1, 15.0, "2026-10-02")]
    cx = ctx(fs, date_from="2026-10-01", date_to="2026-10-08", sp=spot(NIFTY=closes), c=cfg())
    b = sp.spot_vs_pnl(cx, [], ["NIFTY"])["underlyings"][0]
    assert b["series"]["realised_measured"][0] == 5.0 and b["totals"]["pnl_rolled_days"] == 1
    assert b["totals"]["pnl_after_last_spot"] == 0.0


def test_pnl_closed_before_date_from_is_excluded_from_totals_and_series():
    closes = _pairs(_bdays("2026-09-28", 8), [20000.0 + 10 * i for i in range(8)])
    fs = [fill("buy", 1, 10.0, "2026-09-28"), fill("sell", 1, 99.0, "2026-09-29"),      # closes before date_from
          fill("buy", 1, 10.0, "2026-10-01"), fill("sell", 1, 11.0, "2026-10-02")]
    cx = ctx(fs, date_from="2026-10-01", date_to="2026-10-09", sp=spot(NIFTY=closes), c=cfg())
    b = sp.spot_vs_pnl(cx, [], ["NIFTY"])["underlyings"][0]
    assert b["totals"]["measured_realised"] == 1.0 and sum(b["series"]["realised_measured"]) == 1.0


@pytest.mark.parametrize("include_est", [True, False])
def test_measured_plus_estimate_identity_and_toggle(include_est):
    days = _bdays("2026-10-01", 6)
    closes = _pairs(days, [20000.0, 20100.0, 20300.0, 20250.0, 20400.0, 20350.0])
    fs = [fill("buy", 1, 10.0, days[1]), fill("sell", 1, 14.0, days[2]),                       # +4 measured
          fill("sell", 10, 50.0, days[1], symbol="NIFTY26OCT20000CE", strike=20000.0, expiry=days[4])]   # expiry est
    cx = ctx(fs, date_from=days[0], date_to="2026-10-09", include_est=include_est, sp=spot(NIFTY=closes), c=cfg())
    b = sp.spot_vs_pnl(cx, [], ["NIFTY"])["underlyings"][0]
    s, t = b["series"], b["totals"]
    assert sum(s["realised_measured"]) + t["pnl_after_last_spot"] == pytest.approx(t["measured_realised"])
    est_sum = sum(s["realised_estimate"])
    if include_est:
        assert est_sum == pytest.approx(t["estimated_realised"]) and est_sum != 0.0
        assert s["cum_total"][-1] == pytest.approx(sum(s["realised_measured"]) + est_sum)
        assert b["relationship"]["all_days"]["basis_tag"] == "mixed"
    else:
        assert est_sum == 0.0 and t["estimated_realised"] == 0.0 and s["cum_total"] == s["cum_measured"]
        assert b["relationship"]["all_days"]["basis_tag"] == "measured"
        exp = {x["key"]: x for x in b["relationship"]["expiry_days"]}
        assert exp["expiry"]["total_estimate"] in (0.0, None)


def test_estimate_toggle_changes_correlation_input_only_by_the_estimate():
    days = _bdays("2026-09-01", 30)
    closes = _walk(30, 5)
    book = _daily_book(days[1:], [float((i % 7) * 10 - 20) for i in range(29)])
    book.append(fill("sell", 10, 50.0, days[3], symbol="NIFTY26SEP20000CE", strike=20000.0, expiry=days[20]))
    on = _run(book, _pairs(days, closes), days[1], "2026-10-30", include_est=True)[1]
    off = _run(book, _pairs(days, closes), days[1], "2026-10-30", include_est=False)[1]
    assert on["series"]["realised_measured"] == off["series"]["realised_measured"]
    assert on["relationship"]["all_days"]["pearson"] != off["relationship"]["all_days"]["pearson"]


# ── two underlyings: never summed, never mixed ─────────────────────────────────────────────────────


def _two_und_ctx():
    days = _bdays("2026-10-01", 6)
    sp_n = _pairs(days, [20000.0, 20200.0, 20000.0, 20400.0, 20400.0, 20600.0])
    sp_b = _pairs(days, [50000.0, 50500.0, 49500.0, 49500.0, 50000.0, 50000.0])
    fs = [fill("buy", 10, 10.0, days[0]), fill("sell", 10, 15.0, days[2]),                                   # NIFTY +50
          fill("sell", 5, 100.0, days[1], symbol="BANKNIFTY26OCT50000CE", underlying="BANKNIFTY", strike=50000.0),
          fill("buy", 5, 90.0, days[3], symbol="BANKNIFTY26OCT50000CE", underlying="BANKNIFTY", strike=50000.0)]  # +50
    cx = ctx(fs, date_from=days[0], date_to="2026-10-09", sp=spot(NIFTY=sp_n, BANKNIFTY=sp_b), c=cfg())
    return cx, days, sp_n, sp_b, fs


def test_underlyings_are_independent_blocks_and_equal_their_solo_runs():
    cx, days, sp_n, sp_b, fs = _two_und_ctx()
    both = sp.spot_vs_pnl(cx, [], ["NIFTY", "BANKNIFTY"])["underlyings"]
    n_only = [f for f in fs if f.underlying == "NIFTY"]
    b_only = [f for f in fs if f.underlying == "BANKNIFTY"]
    solo_n = sp.spot_vs_pnl(ctx(n_only, date_from=days[0], date_to="2026-10-09", sp=spot(NIFTY=sp_n), c=cfg()),
                            [], ["NIFTY"])["underlyings"][0]
    solo_b = sp.spot_vs_pnl(ctx(b_only, date_from=days[0], date_to="2026-10-09", sp=spot(BANKNIFTY=sp_b), c=cfg()),
                            [], ["BANKNIFTY"])["underlyings"][0]
    assert [x["underlying"] for x in both] == ["NIFTY", "BANKNIFTY"]
    assert both[0]["series"] == solo_n["series"] and both[0]["totals"] == solo_n["totals"]
    assert both[1]["series"] == solo_b["series"] and both[1]["totals"] == solo_b["totals"]
    assert both[0]["totals"]["measured_realised"] == 50.0 and both[1]["totals"]["measured_realised"] == 50.0
    assert both[0]["series"]["spot_close"] != both[1]["series"]["spot_close"]
    only_b = sp.spot_vs_pnl(cx, [], ["BANKNIFTY"])["underlyings"]
    assert [x["underlying"] for x in only_b] == ["BANKNIFTY"]


def test_bias_of_one_underlying_never_leaks_into_the_other():
    cx, days, *_ = _two_und_ctx()
    n, b = sp.spot_vs_pnl(cx, [], ["NIFTY", "BANKNIFTY"])["underlyings"]
    assert n["series"]["dates"][0] == "2026-10-02"
    assert n["series"]["bias_in"] == [10, 10, 0, 0, 0]                                   # long 10 CE only
    assert b["series"]["bias_in"] == [0, -5, -5, 0, 0]                                   # short 5 CE only (bearish)


def test_snapshot_never_mixes_underlyings():
    cx, *_ = _two_und_ctx()
    lines = [an.PnlLine("NIFTY26OCT20000CE", "NIFTY", "2026-10", D("2026-10-01"), D("2026-10-09"), 0.0, 10, "Long",
                        unrealized_pnl=100.0),
             an.PnlLine("BANKNIFTY26OCT50000CE", "BANKNIFTY", "2026-10", D("2026-10-01"), D("2026-10-09"), 0.0, 5,
                        "Short", unrealized_pnl=-7.0)]
    v = sp.spot_vs_pnl(ctx(cx.res.fills, date_from="2026-10-01", date_to="2026-10-12",
                           sp=cx.spot, c=cfg()), lines, ["NIFTY", "BANKNIFTY"])["underlyings"]
    assert v[0]["unrealised_snapshot"]["amount"] == 100.0 and v[0]["unrealised_snapshot"]["n_symbols"] == 1
    assert v[1]["unrealised_snapshot"]["amount"] == -7.0 and v[1]["unrealised_snapshot"]["n_symbols"] == 1


# ── truncation ───────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("n_days,dropped", [(30, 0), (31, 1), (45, 15)])
def test_truncation_boundary_with_the_real_validator_minimum(n_days, dropped):
    days = _bdays("2026-07-01", n_days + 1)
    closes = _walk(n_days + 1, 3)
    book = _daily_book(days[1:], [float((i % 5) * 7 - 10) for i in range(n_days)])
    pair = _pairs(days, closes)
    full = _run(book, pair, days[1], "2026-12-31", c=cfg(spot_series_max_points=400))[1]
    cut = _run(book, pair, days[1], "2026-12-31", c=cfg(spot_series_max_points=30))[1]
    assert cut["series"]["truncated"] is bool(dropped) and cut["series"]["dropped_days"] == dropped
    assert len(cut["series"]["dates"]) == min(n_days, 30) and cut["series"]["dates"] == full["series"]["dates"][dropped:]
    assert cut["series"]["cum_total"] == full["series"]["cum_total"][dropped:]       # cumulative still from window start
    assert cut["relationship"] == full["relationship"] and cut["alignment"] == full["alignment"]
    assert cut["totals"] == full["totals"]
    for k, v in cut["series"].items():
        if isinstance(v, list):
            assert len(v) == len(cut["series"]["dates"]), k                         # parallel arrays stay aligned


# ── sample-size gating ───────────────────────────────────────────────────────────────────────────


def test_bucket_gate_is_inclusive_and_gated_values_are_null_never_zero():
    def other_bucket(min_days):
        _, b = _run(_part_book(), _pairs(_PART_DAYS, _PART_CLOSES), "2026-09-02", "2026-09-30",
                    c=cfg(spot_rel_min_bucket_days=min_days))
        return next(x for x in b["relationship"]["big_move"] if x["key"] == "other")

    n = other_bucket(1)["n_days"]
    assert n >= 3
    at, above = other_bucket(n), other_bucket(n + 1)
    assert at["available"] is True and at["reason"] is None and at["total_pnl"] is not None
    assert above["available"] is False and above["reason"] == "insufficient_sample" and above["n_days"] == n
    for f in ("total_pnl", "total_measured", "total_estimate", "mean_pnl", "median_pnl", "hit_rate_pct",
              "share_of_total_loss_pct"):
        assert above[f] is None, f                                         # null, never a misleading 0
    assert above["min_required"] == n + 1


def test_gated_statistics_yield_only_the_low_sample_observation():
    cx, b = _run(_part_book(), _pairs(_PART_DAYS, _PART_CLOSES), "2026-09-02", "2026-09-30")   # defaults: 12 < 20 days
    ids = [o["id"] for o in b["observations"]]
    assert ids == ["low_sample"]
    assert b["relationship"]["all_days"]["reason"] == "insufficient_sample"
    assert b["alignment"]["verdict"] == "insufficient_sample"
    assert b["observations"][0]["text"].endswith(sp.MULTI_NOTE)


def test_multiple_comparison_reminder_appears_exactly_once_per_block():
    cx, b = _run(_part_book(), _pairs(_PART_DAYS, _PART_CLOSES), "2026-09-02", "2026-09-30",
                 c=cfg(spot_rel_min_bucket_days=1, spot_rel_min_bias_days=1, spot_rel_min_days=3,
                       spot_rel_min_closing_days=3, spot_obs_concentration_pct=0.0))
    texts = [o["text"] for o in b["observations"]]
    assert len(texts) >= 2 and sum(sp.MULTI_NOTE in t for t in texts) == 1 and sp.MULTI_NOTE in texts[-1]
    for o in b["observations"]:
        assert o["evidence"] and all({"label", "value", "source"} <= set(e) for e in o["evidence"])
        assert not re.search(r"\b(because|caused|due to|recommend|advise)\b", o["text"], re.I)


# ── unrealised snapshot (module level) ───────────────────────────────────────────────────────────────

_OPEN_CLOSES = _pairs(_bdays("2026-10-01", 8), [20000.0 + 10 * i for i in range(8)])      # last spot 10-12
_OPEN = [fill("buy", 10, 10.0, "2026-10-05", symbol="NIFTY26OCT20000CE", strike=20000.0),
         fill("buy", 10, 10.0, "2026-10-05", symbol="NIFTY26OCT20100CE", strike=20100.0),
         fill("buy", 10, 10.0, "2026-10-05", symbol="NIFTY26OCT20200CE", strike=20200.0)]


def _pl(sym, pf, pt, un, oq=10, ym="2026-10", und="NIFTY"):
    return an.PnlLine(sym, und, ym, D(pf), D(pt), 0.0, oq, "Long", unrealized_pnl=un)


def _snap(lines, c=None):
    cx = ctx(_OPEN, date_from="2026-10-01", date_to="2026-10-12", sp=spot(NIFTY=_OPEN_CLOSES), c=c or cfg())
    return sp.spot_vs_pnl(cx, lines, ["NIFTY"])["underlyings"][0]["unrealised_snapshot"]


def test_snapshot_uses_each_symbols_latest_period_and_max_as_of_over_symbols():
    s = _snap([_pl("NIFTY26OCT20000CE", "2026-10-01", "2026-10-07", 100.0),
               _pl("NIFTY26OCT20000CE", "2026-10-01", "2026-10-09", 250.0),          # supersedes, NOT added to 100
               _pl("NIFTY26OCT20100CE", "2026-10-01", "2026-10-08", -40.0),
               _pl("NIFTY26OCT20200CE", "2026-10-01", "2026-10-09", 60.0)])
    assert s["available"] and s["amount"] == 270.0 and s["n_symbols"] == 3 and s["as_of"] == "2026-10-09"
    assert s["fifo_open_symbols"] == 3 and s["symbols_missing_in_sheet"] == 0 and s["tag"] == "measured"


def test_snapshot_equal_period_to_prefers_the_later_period_from_and_is_order_independent():
    a = _pl("NIFTY26OCT20000CE", "2026-10-01", "2026-10-09", 500.0)
    b = _pl("NIFTY26OCT20000CE", "2026-10-05", "2026-10-09", 70.0)
    assert _snap([a, b])["amount"] == 70.0 and _snap([b, a])["amount"] == 70.0


def test_snapshot_negative_total_and_newest_null_does_not_fall_back_to_older_value():
    s = _snap([_pl("NIFTY26OCT20000CE", "2026-10-01", "2026-10-09", -300.0),
               _pl("NIFTY26OCT20100CE", "2026-10-01", "2026-10-07", 10.0),
               _pl("NIFTY26OCT20100CE", "2026-10-01", "2026-10-09", None)])         # newest has no mark
    assert s["amount"] == -300.0 and s["n_symbols"] == 1 and s["symbols_missing_in_sheet"] == 2


@pytest.mark.parametrize("sheet_to,stale,behind", [("2026-10-07", False, 5), ("2026-10-06", True, 6),
                                                    ("2026-10-12", False, 0), ("2026-10-14", False, -2)])
def test_snapshot_staleness_boundary_is_strictly_greater_than_the_configured_days(sheet_to, stale, behind):
    s = _snap([_pl("NIFTY26OCT20000CE", "2026-10-01", sheet_to, 1.0)], cfg(sheet_snapshot_stale_days=5))
    assert (s["stale"], s["days_behind_spot"]) == (stale, behind)
    assert s["available"] is True and s["reason"] == ("sheet_stale" if stale else None)


def test_snapshot_ignores_zero_open_quantity_and_other_underlying_lines():
    s = _snap([_pl("NIFTY26OCT20000CE", "2026-10-01", "2026-10-09", 999.0, oq=0),
               _pl("BANKNIFTY26OCT50000CE", "2026-10-01", "2026-10-09", 888.0, und="BANKNIFTY")])
    assert s["available"] is False and s["amount"] is None and s["reason"] == "no_pnl_sheet"


# ── what-if rules ────────────────────────────────────────────────────────────────────────────────


def _rules_for(fs, closes, date_from, date_to, c):
    cx = ctx(fs, date_from=date_from, date_to=date_to, sp=spot(NIFTY=closes), c=c)
    rs, vt = spot_rules(cx, sp.spot_vs_pnl(cx, [], ["NIFTY"]))
    return cx, {r["id"]: r for r in rs}, vt


def test_expiry_proximity_boundary_is_inclusive_of_n_days_and_includes_expiry_day():
    exp = "2026-10-09"
    fs = [fill("buy", 10, 50.0, "2026-10-07", symbol="NIFTY26OCT20000CE", strike=20000.0, expiry=exp),    # 2d: vetoed
          fill("buy", 10, 50.0, "2026-10-06", symbol="NIFTY26OCT20100CE", strike=20100.0, expiry=exp),    # 3d: kept
          fill("buy", 10, 50.0, "2026-10-09", symbol="NIFTY26OCT20200CE", strike=20200.0, expiry=exp),    # 0d: vetoed
          fill("sell", 10, 60.0, "2026-10-09", symbol="NIFTY26OCT20000CE", strike=20000.0, expiry=exp),
          fill("sell", 10, 60.0, "2026-10-09", symbol="NIFTY26OCT20100CE", strike=20100.0, expiry=exp),
          fill("sell", 10, 40.0, "2026-10-09", symbol="NIFTY26OCT20200CE", strike=20200.0, expiry=exp)]
    closes = _pairs(_bdays("2026-10-01", 8), [20000.0, 20010.0, 20020.0, 20030.0, 20040.0, 20050.0, 20060.0, 20070.0])
    c = cfg(suggestion_min_closed_trades=1)
    _, r, vt = _rules_for(fs, closes, "2026-10-01", "2026-10-12", c)
    assert len(vt["expiry_proximity_entries"]) == 2
    w = r["expiry_proximity_entries"]["what_if"]
    # baseline +100 +100 -100 = 100; vetoing the 2d (+100) and 0d (-100) entries removes net 0
    assert (w["baseline_pnl"], w["trades_removed"], w["delta"]) == (100.0, 2, 0.0)
    _, r0, vt0 = _rules_for(fs, closes, "2026-10-01", "2026-10-12", cfg(suggestion_min_closed_trades=1, expiry_proximity_days=0))
    assert len(vt0["expiry_proximity_entries"]) == 1                                  # only the expiry-day entry


def test_counter_move_previous_session_staleness_boundary():
    closes = [("2026-10-01", 20000.0), ("2026-10-02", 20400.0), ("2026-10-09", 20410.0), ("2026-10-12", 20420.0)]
    fs = [fill("sell", 10, 100.0, "2026-10-07", symbol="NIFTY26OCT20000CE", strike=20000.0, expiry="2026-10-27"),  # 5d
          fill("sell", 10, 100.0, "2026-10-08", symbol="NIFTY26OCT20100CE", strike=20100.0, expiry="2026-10-27"),  # 6d
          fill("buy", 10, 90.0, "2026-10-09", symbol="NIFTY26OCT20000CE", strike=20000.0, expiry="2026-10-27"),
          fill("buy", 10, 90.0, "2026-10-09", symbol="NIFTY26OCT20100CE", strike=20100.0, expiry="2026-10-27")]
    _, r, vt = _rules_for(fs, closes, "2026-10-01", "2026-10-12", cfg(suggestion_min_closed_trades=1))
    assert len(vt["counter_move_entries"]) == 1 and r["counter_move_entries"]["what_if"]["trades_removed"] == 1
    _, r2, _ = _rules_for(fs, closes, "2026-10-01", "2026-10-12", cfg(suggestion_min_closed_trades=1, spot_stale_days=7))
    assert r2["counter_move_entries"]["what_if"]["trades_removed"] == 2


def test_counter_move_threshold_just_below_is_not_a_sharp_move():
    closes = [("2026-10-01", 20000.0), ("2026-10-02", 20199.0), ("2026-10-05", 20200.0), ("2026-10-06", 20210.0)]
    fs = [fill("sell", 10, 100.0, "2026-10-05", symbol="NIFTY26OCT20000CE", strike=20000.0, expiry="2026-10-27"),
          fill("buy", 10, 90.0, "2026-10-06", symbol="NIFTY26OCT20000CE", strike=20000.0, expiry="2026-10-27")]
    _, r, _ = _rules_for(fs, closes, "2026-10-01", "2026-10-12", cfg(suggestion_min_closed_trades=1))
    assert r["counter_move_entries"]["status"] == "not_triggered"                  # +0.995% < 1.0%


_BOOK = [fill("buy", 100, 10.0, "2026-10-01"), fill("buy", 100, 10.0, "2026-10-02"),
         fill("buy", 100, 10.0, "2026-10-05"), fill("sell", 300, 12.0, "2026-10-06"),
         fill("sell", 5, 10.0, "2026-10-07", symbol="NIFTY26OCT20100CE", strike=20100.0),
         fill("buy", 5, 9.0, "2026-10-08", symbol="NIFTY26OCT20100CE", strike=20100.0)]
_BCLOSE = [("2026-09-30", 20000.0), ("2026-10-01", 20200.0), ("2026-10-02", 20400.0), ("2026-10-05", 20000.0),
           ("2026-10-06", 20100.0), ("2026-10-07", 19800.0), ("2026-10-08", 20000.0)]


def _suggest(monkeypatch=None, drop_spot=False):
    import rita.services.fno_trade_suggestions as mod
    if drop_spot:
        monkeypatch.setattr(mod, "spot_rules", lambda ctx_, view: ([], {}))
    cx = ctx(_BOOK, date_from="2026-10-01", date_to="2026-10-12", sp=spot(NIFTY=_BCLOSE),
             c=cfg(suggestion_min_closed_trades=1))
    lots = an.LotInfo()
    return suggestions(cx, an.overtrading(cx, []), an.buildup(cx, lots),
                       {"ledger": {"available": False}, "cash_series": [], "trap": {"days": 0},
                        "cash": {"min": None}, "stops": {"rows": []}}, lots)


def test_existing_suggestion_rules_are_unchanged_by_the_new_spot_rules(monkeypatch):
    full = _suggest()
    base = _suggest(monkeypatch, drop_spot=True)
    def old(out):
        return {r["id"]: r for r in out["rules"] if r["id"] not in SPOT_RULE_IDS}

    assert old(full) == old(base) and old(base)
    assert full["sample"] == base["sample"] and full["disclaimer"] == base["disclaimer"]
    assert {r["id"] for r in full["rules"]} - {r["id"] for r in base["rules"]} == set(SPOT_RULE_IDS)


def test_illustrative_and_non_veto_rules_never_enter_combined(monkeypatch):
    out = _suggest()
    inc = out["combined"]["rules_included"]
    assert "bias_hedge_illustrative" not in inc
    by = {r["id"]: r for r in out["rules"]}
    assert by["bias_hedge_illustrative"]["what_if"] is None and by["bias_hedge_illustrative"]["status"] == "illustrative"
    assert all(by[i]["what_if"] is not None and by[i]["status"] == "applicable" for i in inc)
    veto_titles = [by[i]["title"] for i in ("bias_limit", "expiry_proximity_entries", "counter_move_entries")
                   if by[i]["status"] != "insufficient_data"]
    assert all(t.startswith("What-if:") for t in veto_titles)
    assert by["bias_hedge_illustrative"]["title"].startswith("Illustrative:")
    assert [r["status"] for r in out["rules"]] == sorted((r["status"] for r in out["rules"]),
                                                          key=lambda s: {"applicable": 0, "not_triggered": 1,
                                                                         "insufficient_data": 2, "illustrative": 3}[s])
    # the combined what-if can only differ from the base run by the spot veto rules it now includes
    base = _suggest(monkeypatch, drop_spot=True)
    assert set(base["combined"]["rules_included"]) <= set(inc)


# ── service / API ────────────────────────────────────────────────────────────────────────────────


def _svc(db, c=None):
    s = FnoTradeAnalyticsService(db, today=TODAY)
    if c is not None:
        s._cfg = c
    return s


_SP = [("NIFTY", d, c_) for d, c_ in _BCLOSE] + [("NIFTY", "2026-10-09", 20100.0), ("NIFTY", "2026-10-12", 20200.0)]


def _set_unrealised(db, user_id, sym, value, period_to=None):
    from rita.models.fno_import import FnoPnlLineModel
    q = db.query(FnoPnlLineModel).filter_by(user_id=user_id, symbol=sym)
    for row in q:
        row.unrealized_pnl = value
        if period_to:
            row.period_to = D(period_to)
    db.commit()


def test_other_users_rows_never_leak_into_trades_pnl_lines_or_snapshot(db_session):
    mine = [fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 12.0, "2026-10-02")]
    theirs = [fill("buy", 1000, 10.0, "2026-10-01"), fill("sell", 1000, 20.0, "2026-10-05"),
              fill("buy", 10, 10.0, "2026-10-06", symbol="NIFTY26OCT20500CE", strike=20500.0)]
    seed(db_session, "me", mine, _SP,
         pnl_lines=[("NIFTY26OCT24000CE", "NIFTY", "2026-10", "2026-10-01", "2026-10-09", 20.0, 0, "Long")])
    seed(db_session, "them", theirs,
         pnl_lines=[("NIFTY26OCT20500CE", "NIFTY", "2026-10", "2026-10-01", "2026-10-09", 0.0, 10, "Long")])
    _set_unrealised(db_session, "them", "NIFTY26OCT20500CE", 123456.0)
    alone = _svc(db_session).spot_vs_pnl("me", AnalyticsParams())
    only_theirs = _svc(db_session).spot_vs_pnl("them", AnalyticsParams())
    nobody = _svc(db_session).spot_vs_pnl("nobody", AnalyticsParams())
    n = alone.underlyings[0]
    assert n.totals.measured_realised == 20.0                                       # 10 * (12 - 10), nothing of theirs
    assert n.unrealised_snapshot.available is False and n.unrealised_snapshot.amount is None
    assert only_theirs.underlyings[0].totals.measured_realised == 10000.0
    assert only_theirs.underlyings[0].unrealised_snapshot.amount == 123456.0
    assert nobody.available is False and nobody.reason == "no_data"
    assert "123456" not in json.dumps(alone.model_dump(), default=str)


def test_service_snapshot_filters_by_expiry_month_and_underlying_scope(db_session):
    seed(db_session, "u", _BOOK[:2] + [fill("buy", 10, 5.0, "2026-10-01", symbol="NIFTY26NOVCE", expiry="2026-11-24")],
         _SP, pnl_lines=[("NIFTY26OCT24000CE", "NIFTY", "2026-10", "2026-10-01", "2026-10-09", 0.0, 200, "Long"),
                         ("NIFTY26NOVCE", "NIFTY", "2026-11", "2026-10-01", "2026-10-09", 0.0, 10, "Long")])
    _set_unrealised(db_session, "u", "NIFTY26OCT24000CE", 70.0)
    _set_unrealised(db_session, "u", "NIFTY26NOVCE", 5.0)
    allm = _svc(db_session).spot_vs_pnl("u", AnalyticsParams()).underlyings[0].unrealised_snapshot
    octo = _svc(db_session).spot_vs_pnl("u", AnalyticsParams(expiry_month=10)).underlyings[0].unrealised_snapshot
    nov = _svc(db_session).spot_vs_pnl("u", AnalyticsParams(expiry_month=11)).underlyings[0].unrealised_snapshot
    assert (allm.amount, octo.amount, nov.amount) == (75.0, 70.0, 5.0)


def test_service_estimate_toggle_is_echoed_and_changes_only_estimated_fields(db_session):
    fs = [fill("buy", 1, 10.0, "2026-10-01"), fill("sell", 1, 14.0, "2026-10-02"),
          fill("sell", 10, 50.0, "2026-10-01", symbol="NIFTY26OCT20000CE", strike=20000.0, expiry="2026-10-08")]
    seed(db_session, "u", fs, _SP)
    on = _svc(db_session).spot_vs_pnl("u", AnalyticsParams(include_expiry_estimate=True))
    off = _svc(db_session).spot_vs_pnl("u", AnalyticsParams(include_expiry_estimate=False))
    assert on.filter.include_expiry_estimate is True and off.filter.include_expiry_estimate is False
    a, b = on.underlyings[0], off.underlyings[0]
    assert a.totals.measured_realised == b.totals.measured_realised == 4.0
    assert a.totals.estimated_realised != 0.0 and b.totals.estimated_realised == 0.0
    assert a.series.realised_measured == b.series.realised_measured


def test_expiry_month_scope_apr_to_nov_filter_and_symbol_isolation(db_session):
    apr = fill("buy", 10, 10.0, "2026-10-01", symbol="NIFTY26APR20000CE", strike=20000.0, expiry="2026-04-28")
    apr2 = fill("sell", 10, 13.0, "2026-10-02", symbol="NIFTY26APR20000CE", strike=20000.0, expiry="2026-04-28")
    dec = fill("buy", 10, 1.0, "2026-10-01", symbol="NIFTY26DEC20000CE", strike=20000.0, expiry="2026-12-29")
    dec2 = fill("sell", 10, 9.0, "2026-10-02", symbol="NIFTY26DEC20000CE", strike=20000.0, expiry="2026-12-29")
    seed(db_session, "u", [apr, apr2, dec, dec2], _SP)
    svc = _svc(db_session)
    assert svc.spot_vs_pnl("u", AnalyticsParams(expiry_month=4)).underlyings[0].totals.measured_realised == 30.0
    # December is not a configured expiry month: its fills never enter any scope
    assert svc.spot_vs_pnl("u", AnalyticsParams()).underlyings[0].totals.measured_realised == 30.0
    assert svc.spot_vs_pnl("u", AnalyticsParams(expiry_month=12)).reason == "no_trades_in_scope"
    assert svc.spot_vs_pnl("u", AnalyticsParams(expiry_month=5)).reason == "no_trades_in_scope"      # configured, empty


@pytest.mark.parametrize("months", [[4], [11], [1, 12], [4, 5, 6, 7, 8, 9, 10, 11]])
def test_expiry_months_validator_accepts_valid_lists(months):
    assert TradeAnalysisSettings(expiry_months=months).expiry_months == months


@pytest.mark.parametrize("months", [[0], [13], [12, 13], [-1, 5], [4, 4], [11, 4], [4, 6, 5]])
def test_expiry_months_validator_rejects_out_of_range_dupes_and_unsorted(months):
    with pytest.raises(ValidationError):
        TradeAnalysisSettings(expiry_months=months)


def test_before_after_reconciliation_old_scope_vs_widened_scope_via_service(db_session):
    old_sym = [fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 12.0, "2026-10-02"),
               fill("buy", 10, 20.0, "2026-10-05"), fill("sell", 10, 17.0, "2026-10-06")]
    new_sym = [fill("buy", 10, 5.0, "2026-10-01", symbol="NIFTY26AUG20000CE", strike=20000.0, expiry="2026-08-25"),
               fill("sell", 10, 9.0, "2026-10-06", symbol="NIFTY26AUG20000CE", strike=20000.0, expiry="2026-08-25"),
               fill("buy", 3, 5.0, "2026-10-07", symbol="NIFTY26JUN20000CE", strike=20000.0, expiry="2026-06-30")]
    seed(db_session, "u", old_sym + new_sym, _SP)
    before = _svc(db_session, cfg(expiry_months=[9, 10, 11]))
    after = _svc(db_session, cfg(expiry_months=[4, 5, 6, 7, 8, 9, 10, 11]))

    def rows(svc):
        return {r.symbol: r for r in svc.foundation("u", AnalyticsParams()).reconciliation.rows}

    rb, ra = rows(before), rows(after)
    assert set(ra) - set(rb) == {"NIFTY26AUG20000CE", "NIFTY26JUN20000CE"} and set(rb) <= set(ra)
    assert rb, "old scope must still show its own symbol"
    for sym, row in rb.items():
        assert ra[sym].fifo_measured == row.fifo_measured and ra[sym].gap_measured == row.gap_measured

    vb = before.spot_vs_pnl("u", AnalyticsParams()).underlyings[0]
    va = after.spot_vs_pnl("u", AnalyticsParams()).underlyings[0]
    assert vb.totals.measured_realised == 10 * 2.0 + 10 * -3.0
    assert va.totals.measured_realised == vb.totals.measured_realised + 10 * 4.0          # exactly the Aug symbol
    # days on which the new symbol did nothing keep identical P&L
    for i, d in enumerate(va.series.dates):
        j = vb.series.dates.index(d)
        if d != "2026-10-06":
            assert va.series.realised_measured[i] == vb.series.realised_measured[j]
    assert vb.series.dates == va.series.dates                                              # spot axis unaffected
    assert before.spot_vs_pnl("u", AnalyticsParams()).filter.expiry_months == [9, 10, 11]
    assert after.spot_vs_pnl("u", AnalyticsParams()).filter.expiry_months == [4, 5, 6, 7, 8, 9, 10, 11]


@pytest.fixture()
def api_user(client, db_session):
    from rita.api.experience import fno_trade_analytics as router_mod
    from rita.auth import get_current_user
    from rita.main import app
    u = MagicMock()
    u.id = "u-qa"
    app.dependency_overrides[get_current_user] = lambda: u
    app.dependency_overrides[router_mod._get_service] = lambda: FnoTradeAnalyticsService(db_session, today=TODAY)
    yield u
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(router_mod._get_service, None)


URL = "/api/v1/experience/fno/trade-analysis/analytics/spot-vs-pnl"
_ENVELOPE = {"available", "reason", "message", "as_of", "filter", "definition", "assumptions", "quality", "tags"}


@pytest.mark.parametrize("qs,code", [("expiry_month=0", 422), ("expiry_month=13", 422), ("underlying=FINNIFTY", 422),
                                     ("date_from=notadate", 422), ("include_expiry_estimate=maybe", 422),
                                     ("expiry_month=4", 200), ("expiry_month=11", 200), ("underlying=ALL", 200),
                                     ("underlying=BANKNIFTY", 200)])
def test_api_parameter_validation_matrix(client, api_user, db_session, qs, code):
    seed(db_session, "u-qa", _BOOK[:2], _SP)
    assert client.get(f"{URL}?{qs}").status_code == code


def test_api_envelope_always_present_even_when_unavailable_and_lots_param_never_calls_middleware(
        client, api_user, db_session, monkeypatch):
    from rita.services import kite_middleware_client as kmc

    def boom(*a, **k):
        raise AssertionError("middleware must not be called by spot-vs-pnl")

    for name in dir(kmc):
        if name.startswith("fetch") or name.startswith("get_") or name == "nfo_master":
            if callable(getattr(kmc, name)):
                monkeypatch.setattr(kmc, name, boom)
    empty = client.get(f"{URL}?include_lots=true")
    assert empty.status_code == 200 and _ENVELOPE <= set(empty.json()) and empty.json()["available"] is False
    seed(db_session, "u-qa", _BOOK[:2], _SP)
    r = client.get(f"{URL}?include_lots=true&expiry_month=12")
    assert r.status_code == 200 and r.json()["reason"] == "no_trades_in_scope" and _ENVELOPE <= set(r.json())
    ok = client.get(f"{URL}?include_lots=true").json()
    assert ok["available"] is True and _ENVELOPE | {"underlyings", "improvement", "info", "delta1_note"} <= set(ok)


def test_api_payload_has_no_null_where_null_is_not_a_valid_sentinel(client, api_user, db_session):
    days = _bdays("2026-09-01", 31)
    closes = _walk(31, 11)
    book = _daily_book(days[1:], [float((i % 6) * 9 - 15) for i in range(30)])
    seed(db_session, "u-qa", book, [("NIFTY", d, c_) for d, c_ in zip(days, closes)])
    j = client.get(f"{URL}?date_from=2026-09-02&date_to=2026-10-14").json()
    assert j["available"] is True
    u = j["underlyings"][0]
    assert u["available"] and u["series"]["dates"]
    for k, v in u["series"].items():
        if isinstance(v, list):
            assert None not in v and len(v) == len(u["series"]["dates"]), k
    for k in ("measured_realised", "estimated_realised", "pnl_rolled_days", "pnl_rolled_amount", "pnl_after_last_spot",
              "pnl_after_last_spot_count", "n_days", "n_closing_days"):
        assert u["totals"][k] is not None, k
    for blk in (u["relationship"]["all_days"], u["relationship"]["closing_days"]):
        assert (blk["pearson"] is None) == (blk["reason"] is not None)
        assert (blk["spearman"] is None) == (blk["pearson"] is None) or blk["reason"] == "no_variation"
    for b in (u["relationship"]["by_direction"] + u["relationship"]["big_move"] + u["relationship"]["expiry_days"]
              + [u["relationship"]["big_any"]]):
        assert b["available"] is (b["reason"] is None)
        assert (b["total_pnl"] is None) == (not b["available"])
    al = u["alignment"]
    assert al["verdict"] in {"with_market", "against_market", "no_clear_lean", "insufficient_sample"} and al["caveat"]
    assert u["unrealised_snapshot"]["tag"] == "measured" and u["unrealised_snapshot"]["amount"] is None
    assert all(o["text"] and o["evidence"] for o in u["observations"]) and len(u["observations"]) <= 6
    assert j["improvement"]["disclaimer"] and {r["id"] for r in j["improvement"]["rules"]} <= set(SPOT_RULE_IDS)
    for rl in j["improvement"]["related"]:
        assert rl["rule_id"] in SPOT_RULE_IDS and rl["observation_id"]
    sch.SpotVsPnlResponse.model_validate(j)


def test_api_is_get_only_and_unauthenticated_is_rejected(client):
    assert client.get(URL).status_code == 401
    for verb in ("post", "put", "patch", "delete"):
        assert getattr(client, verb)(URL).status_code in (401, 403, 405)


# ── frontend static contract and hostile-string rendering ──────────────────────────────────────────

JS = (ROOT / "dashboard/js/fno/trade-analytics.js").read_text()
HTML = (ROOT / "dashboard/fno.html").read_text()
MAIN = (ROOT / "dashboard/js/fno/main.js").read_text()
_SPOT_JS = JS[JS.index("// ── F42 P4: Spot vs P&L"):JS.index("const _RENDER = {")]


def test_every_spot_dom_id_exists_exactly_once_and_ids_used_by_js_are_in_html():
    ids = set(re.findall(r'id="(ta-(?:an-spotpnl|cv-spot|panel-spotpnl)[\w-]*)"', HTML))
    assert {"ta-panel-spotpnl", "ta-an-spotpnl-body", "ta-an-spotpnl-def", "ta-an-spotpnl-grid",
            "ta-an-spotpnl-obs", "ta-an-spotpnl-rules"} <= ids
    for i in ids:
        assert HTML.count(f'id="{i}"') == 1, i
    literal = set(re.findall(r"'(ta-(?:an-spotpnl|panel-spotpnl)[\w-]*)'", _SPOT_JS))
    templ = set()
    for stem in re.findall(r"`(ta-(?:an-spotpnl|cv-spot)[\w-]*)\$\{(?:i|slot)\}`", _SPOT_JS):
        templ |= {f"{stem}{n}" for n in (0, 1)}
    assert literal <= ids and templ <= ids and templ
    assert len(re.findall(r'id="ta-panel-spotpnl"', HTML)) == 1 and len(re.findall(r"<details", HTML)) >= 1
    html_all_ids = re.findall(r'\bid="([^"]+)"', HTML)
    dup = {i for i in html_all_ids if html_all_ids.count(i) > 1 and i.startswith("ta-")}
    assert not dup, dup


def test_spot_card_inline_handlers_are_bound_on_window_and_card_is_a_closed_details():
    card = HTML[HTML.rindex("<details", 0, HTML.index('id="ta-panel-spotpnl"')):HTML.index('id="ta-panel-margintrap"')]
    handlers = set(re.findall(r'\bon\w+="([A-Za-z_]\w*)\(', card))
    assert handlers == {"taAnSpotToggle", "taAnToggleInfo"}
    for h in handlers:
        assert f"window.{h} = {h}" in MAIN
    head = re.search(r'<details[^>]*id="ta-panel-spotpnl"[^>]*>', HTML).group(0)
    assert "open" not in head.replace("ontoggle", "").split()
    assert card.count("<details") == card.count("</details>")
    assert 'taAnToggleInfo(\'spotpnl\')' in card


def test_spot_functions_wrap_every_server_string_in_esc():
    server_fields = r"(?:\.text|\.title|\.key|\.reason|\.as_of|\.underlying|\.disclaimer|\.message|\.rule_id|" \
                    r"\.observation_id|\.caveat|\.delta1_note|\.label|\.source|\.basis_tag|\.verdict)"
    unsafe = []
    for m in re.finditer(r"\$\{([^${}]*(?:\{[^{}]*\}[^${}]*)*)\}", _SPOT_JS):
        expr = m.group(1)
        if re.search(server_fields, expr) and not re.search(r"_esc\(|_need\(|_note\(|_unavail\(|_verdict\(|_badge\(|_spotVerdictLine\(", expr):
            unsafe.append(expr.strip())
    # chart.js labels / numeric lookups are allowed to be bare: they are not innerHTML
    unsafe = [e for e in unsafe if not re.search(r"\.(?:as_of|underlying)\b.*\bclose\b", e)]
    assert not unsafe, unsafe
    assert not re.search(r"innerHTML\s*=", _SPOT_JS)                       # only the shared setEl helper writes HTML


_NODE = shutil.which("node")

_HOSTILE = r"""
import { taAnSpotToggle } from './js/fno/trade-analytics.js';
await taAnSpotToggle(true); await new Promise(r => setTimeout(r, 20));
console.log(JSON.stringify({els: globalThis.__t.els, labels: globalThis.__t.labels}));
"""


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_hostile_server_strings_are_escaped_in_every_rendered_fragment(tmp_path):
    days = _bdays("2026-09-01", 31)
    closes = _walk(31, 4)
    book = _daily_book(days[1:], [float((i % 6) * 9 - 15) for i in range(30)]) + \
        [fill("buy", 10, 10.0, days[10], symbol="NIFTY26OCT20000CE", strike=20000.0)]
    cx = ctx(book, date_from=days[1], date_to="2026-10-30", sp=spot(NIFTY=_pairs(days, closes)),
             c=cfg(spot_rel_min_bucket_days=1, spot_rel_min_bias_days=1, spot_rel_min_days=3,
                   spot_rel_min_closing_days=3, suggestion_min_closed_trades=1))
    view = sp.spot_vs_pnl(cx, [], ["NIFTY"])
    rs, _ = spot_rules(cx, view)
    evil = "<img src=x onerror=alert(1)>"
    payload = {"available": True, "reason": None, "message": evil, "as_of": evil, "filter": {}, "definition": evil,
               "assumptions": [evil], "quality": {}, "tags": {"measured": [evil], "estimated": [evil]},
               **view, "improvement": {"disclaimer": evil, "baseline_pnl": 0.0, "rules": rs,
                                       "related": [{"observation_id": evil, "rule_id": evil}]}}
    u = payload["underlyings"][0]
    u["underlying"] = evil
    u["unrealised_snapshot"].update({"available": True, "amount": 5.0, "as_of": evil, "stale": True})
    u["alignment"]["caveat"] = evil
    for o in u["observations"]:
        o["text"] = evil
        for e in o["evidence"]:
            e["label"] = e["source"] = evil
    for r in payload["improvement"]["rules"]:
        r["title"] = r["threshold_basis"] = evil
        r["caveats"] = [evil]
        for e in r.get("evidence") or []:
            e["label"] = e["source"] = evil
    payload["info"] = {"definition": evil, "assumptions": [evil]}
    fno = tmp_path / "js/fno"
    shared = tmp_path / "js/shared"
    fno.mkdir(parents=True)
    shared.mkdir(parents=True)
    (tmp_path / "package.json").write_text('{"type":"module"}')
    (fno / "trade-analytics.js").write_text(JS)
    (fno / "api.js").write_text("export async function api(u){ return globalThis.__t.payload; }")
    (shared / "utils.js").write_text("export function setEl(id,h){ globalThis.__t.els[id]=h; }")
    (shared / "charts.js").write_text("export function mkChart(id,c){ globalThis.__t.labels.push(...c.data.datasets.map(d=>d.label)); }"
                                      " export function destroyChart(id){}")
    (fno / "trade-analysis.js").write_text(
        "export const _esc = v => String(v == null ? '' : v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');"
        "export const _num = (v, d = 0) => v == null ? '—' : Number(v).toFixed(d);"
        "export const _pnl = v => v == null ? '—' : Number(v).toFixed(0);"
        "export const taGetFilters=()=>({underlying:'ALL',month:''});")
    (tmp_path / "run.mjs").write_text(
        f"globalThis.__t={{els:{{}},labels:[],payload:{json.dumps(payload, default=str)}}};"
        "globalThis.document={getElementById:()=>({style:{},checked:false,value:''})};"
        "globalThis.Chart=function(){};"
        "await import('./harness.mjs');")
    (tmp_path / "harness.mjs").write_text(_HOSTILE)
    r = subprocess.run([_NODE, "run.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["els"].get("ta-an-spotpnl-obs") and out["els"].get("ta-an-spotpnl-rules")
    for el, html in out["els"].items():
        assert "<img" not in html and "onerror=alert(1)>" not in html.replace("&lt;img src=x onerror=alert(1)&gt;", ""), el
    assert any("&lt;img" in html for html in out["els"].values())
