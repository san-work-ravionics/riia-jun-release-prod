"""F42 P3 Code Review advisories 1, 2, 3, 5 — regression tests (synthetic data only)."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from rita.config import TradeAnalysisSettings
from rita.services import fno_trade_analytics as an
from rita.services.fno_trade_analytics_service import AnalyticsParams, FnoTradeAnalyticsService
from rita.services.fno_trade_suggestions import suggestions
from tests.unit.f42_p3_helpers import D, cfg, ctx, fill, seed

W = dict(date_from="2026-10-01", date_to="2026-10-12")
NO_MARGIN = {"ledger": {"available": False}, "cash_series": [], "trap": {"days": 0},
             "cash": {"min": None}, "stops": {"rows": []}}


def _suggest(fs, c):
    cx = ctx(fs, c=c, **W)
    lots = an.LotInfo()
    return suggestions(cx, an.overtrading(cx, []), an.buildup(cx, lots), NO_MARGIN, lots)


def _rule(out, rid):
    return next(r for r in out["rules"] if r["id"] == rid)


# ── 1. qty_cap_per_expiry releases expired symbols ──────────────────────────────

def _qty_cap_book(a_expiry: str):
    a = dict(symbol="NIFTY26OCT24000CE", expiry=a_expiry)
    b = dict(symbol="NIFTY26OCT24100CE", strike=24100.0, expiry="2026-10-27")
    fs = [fill("buy", 100, 10.0, "2026-10-01", **a),
          fill("buy", 30, 10.0, "2026-10-07", **b), fill("sell", 30, 12.0, "2026-10-08", **b)]
    k = dict(symbol="BANKNIFTY26NOV50000CE", underlying="BANKNIFTY", expiry="2026-11-24")
    return fs + [fill("buy", 40, 10.0, "2026-10-01", **k), fill("sell", 40, 10.0, "2026-10-02", **k)]


def test_qty_cap_releases_lots_held_to_expiry():
    # Weekly A (expires 10-06) is bought and never closed; weekly B shares the 2026-10 expiry month
    # and is traded after A has expired.  A must not count against B's entry.
    out = _suggest(_qty_cap_book("2026-10-06"), cfg(suggestion_min_closed_trades=1, suggestion_percentile=1))
    r = _rule(out, "qty_cap_per_expiry")
    assert r["status"] == "applicable" and r["parameter"]["value"] == 40
    # only A's oversized entry (100 vs cap 40) is vetoed; B's 30 units are not
    assert r["what_if"]["trades_removed"] == 1 and r["what_if"]["units_removed"] == 60.0


def test_qty_cap_still_counts_unexpired_symbols_in_same_group():
    # Control: while A has not expired it still counts against B (behaviour unchanged).
    out = _suggest(_qty_cap_book("2026-10-27"), cfg(suggestion_min_closed_trades=1, suggestion_percentile=1))
    assert _rule(out, "qty_cap_per_expiry")["what_if"]["trades_removed"] == 2


# ── 2. thresholds live in TradeAnalysisSettings ─────────────────────────────────

def test_threshold_defaults_unchanged():
    c = TradeAnalysisSettings()
    assert c.holding_bucket_edges_minutes == [5, 30, 120]
    assert (c.spot_stale_days, c.spot_pad_days) == (5, 7)
    assert (c.ledger_sign_tolerance_frac, c.ledger_sign_min_tolerance_inr, c.ledger_sign_match_cutoff) == (
        0.001, 1.0, 0.6)
    assert c.stop_multiple_step == 0.25


@pytest.mark.parametrize("kw", [
    {"holding_bucket_edges_minutes": [30, 5, 120]}, {"holding_bucket_edges_minutes": [5, 30]},
    {"ledger_sign_match_cutoff": 0.5}, {"ledger_sign_match_cutoff": 1.5}, {"spot_pad_days": -1},
    {"stop_multiple_step": 0}])
def test_threshold_validators_reject_bad_values(kw):
    with pytest.raises(ValidationError):
        TradeAnalysisSettings(**kw)


def test_holding_bucket_edges_come_from_config():
    fs = [fill("buy", 10, 10.0, "2026-10-01", "09:31"), fill("sell", 10, 11.0, "2026-10-01", "09:51")]  # 20 min
    default = an.overtrading(ctx(fs, **W), [])["holding"]["buckets"]
    assert {b["label"]: b["count"] for b in default}["5-30m"] == 1
    custom = an.overtrading(ctx(fs, c=cfg(holding_bucket_edges_minutes=[10, 15, 90]), **W), [])["holding"]["buckets"]
    counts = {b["label"]: b["count"] for b in custom}
    assert list(counts)[:4] == ["<10m", "10-15m", "15m-90m", ">90m same-day"]
    assert counts[">90m same-day"] == 0 and counts["15m-90m"] == 1


def test_ledger_sign_thresholds_are_parameters():
    def row(d, cred, bal, i):
        return an.LedgerRow(D(d), 0.0, cred, bal, i)
    # 3 flow days: two match "+flow" (sign +1), one does not -> 66.67 % agreement
    rows = [row("2026-10-01", 5, 100.0, 0), row("2026-10-02", 5, 105.0, 1), row("2026-10-05", 5, 110.0, 2),
            row("2026-10-06", 5, 999.0, 3)]
    assert an.detect_balance_sign(rows) == (1, 66.67)
    assert an.detect_balance_sign(rows, cutoff=0.7) == (None, 66.67)
    near = [row("2026-10-01", 1000, 100.0, 0), row("2026-10-02", 1000, 1100.4, 1)]   # off by 0.4 (0.04 %)
    assert an.detect_balance_sign(near)[0] == 1
    assert an.detect_balance_sign(near, tol_frac=0.0001, min_tol=0.1)[0] is None


def test_stop_multiple_step_comes_from_config():
    fs = []
    for d, exit_px in (("2026-10-01", 25.0), ("2026-10-02", 15.0)):
        fs += [fill("sell", 100, 10.0, d, "10:00"), fill("buy", 100, exit_px, d, "10:31")]
    base = dict(suggestion_min_closed_trades=1)
    assert _rule(_suggest(fs, cfg(**base)), "stop_discipline")["parameter"]["value"] == 1.0
    assert _rule(_suggest(fs, cfg(stop_multiple_step=0.75, **base)), "stop_discipline")["parameter"]["value"] == 0.75


def test_market_turn_stale_days_come_from_config():
    sp = {"NIFTY": [("2026-10-01", 24000.0), ("2026-10-02", 24500.0)]}
    from tests.unit.f42_p3_helpers import spot
    fs = [fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 11.0, "2026-10-02", "11:00")]
    kw = dict(date_from="2026-10-01", date_to="2026-10-12", sp=spot(**sp))
    # last spot 10-02, as_of 10-12: 10 days old -> stale with the 5-day default, fresh with 15
    assert an.market_turn(ctx(fs, **kw))["spot"]["stale"] is True
    assert an.market_turn(ctx(fs, c=cfg(spot_stale_days=15), **kw))["spot"]["stale"] is False


def test_spot_pad_days_come_from_config(db_session):
    seed(db_session, "u", [fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 11.0, "2026-10-02", "11:00")])
    svc = FnoTradeAnalyticsService(db_session, today=date(2026, 10, 12))
    seen = []
    real = svc._market.find_closes
    svc._market.find_closes = lambda u, s, e: (seen.append(s), real(u, s, e))[1]
    svc.foundation("u", AnalyticsParams())
    assert seen == [date(2026, 6, 24)]            # window start 07-01 minus the default 7-day pad
    seen.clear()
    svc._cfg = cfg(spot_pad_days=2)
    svc.foundation("u", AnalyticsParams())
    assert seen == [date(2026, 6, 29)]


# ── 3. pre-history closes are disclosed ─────────────────────────────────────────

def test_pre_history_close_is_disclosed_without_changing_fifo_numbers(db_session):
    # A buy that really covered a short opened before the first import: FIFO has no earlier opening,
    # so it opens a long lot.  The numbers must not change, but the envelope must say so and the
    # reconciliation must count the symbol.
    fs = [fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 12.0, "2026-10-02", "11:00")]
    pnl = [("NIFTY26OCT24000CE", "NIFTY", "2026-10", "2026-04-01", "2026-10-12", 80.0, 0, "Long")]
    seed(db_session, "u", fs, pnl_lines=pnl)
    svc = FnoTradeAnalyticsService(db_session, today=date(2026, 10, 12))
    out = svc.foundation("u", AnalyticsParams())
    assert any("no earlier imported opening" in a for a in out.assumptions)
    assert out.fifo_totals.measured_pnl == 20.0                  # unchanged FIFO result
    t = out.reconciliation.totals
    assert t.pre_history_symbols == 1 and t.gap_measured == 60.0
    # every panel carries the assumption
    assert any("no earlier imported opening" in a for a in svc.overtrading("u", AnalyticsParams()).assumptions)


# ── 5. overlapping sheet periods are not double counted ─────────────────────────

def _line(sym, pf, pt, realised, open_q=0, typ=None):
    return an.PnlLine(sym, "NIFTY", "2026-10", D(pf), D(pt), realised, open_q, typ)


def test_reconciliation_dedupes_overlapping_sheet_periods():
    sym = "NIFTY26OCT24000CE"
    fs = [fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 12.0, "2026-10-02", "11:00")]   # +20
    lines = [_line(sym, "2026-04-01", "2026-10-05", 20.0), _line(sym, "2026-09-01", "2026-10-05", 20.0)]
    rec = an.reconciliation(ctx(fs, **W), lines)
    row = rec["rows"][0]
    assert row["fifo_measured"] == 20.0 and row["sheet_realised"] == 20.0 and row["gap_measured"] == 0.0
    t = rec["totals"]
    assert (t["fifo_measured"], t["sheet_realised"], t["sheet_lines_overlap_dropped"]) == (20.0, 20.0, 1)


def test_reconciliation_overlap_keeps_gap_visible_and_disjoint_periods_still_sum():
    sym = "NIFTY26OCT24000CE"
    fs = [fill("buy", 10, 10.0, "2026-10-01"), fill("sell", 10, 12.0, "2026-10-02", "11:00"),    # +20
          fill("buy", 10, 10.0, "2026-10-06"), fill("sell", 10, 13.0, "2026-10-07", "11:00")]    # +30
    # cumulative export overlapping a narrower one; sheet says 70 vs FIFO 50 -> gap 20 must show
    over = [_line(sym, "2026-04-01", "2026-10-12", 70.0), _line(sym, "2026-10-01", "2026-10-05", 20.0)]
    rec = an.reconciliation(ctx(fs, **W), over)
    assert rec["rows"][0]["fifo_measured"] == 50.0 and rec["rows"][0]["gap_measured"] == 20.0
    assert rec["totals"]["gap_measured"] == 20.0
    # disjoint periods are both kept
    disj = [_line(sym, "2026-10-01", "2026-10-05", 20.0), _line(sym, "2026-10-06", "2026-10-12", 30.0)]
    rec2 = an.reconciliation(ctx(fs, **W), disj)
    assert rec2["rows"][0]["sheet_realised"] == 50.0 and rec2["totals"]["sheet_lines_overlap_dropped"] == 0
    assert rec2["rows"][0]["gap_measured"] == 0.0
