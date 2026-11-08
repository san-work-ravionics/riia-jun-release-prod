"""F45 Phase B: per-bucket monthly rows — cumulative target vs cumulative actual."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from rita.services.bucket_status_service import compute_bucket_breakdown, month_key
from rita.services.jarvis_page_service import JarvisPageService
from rita.services.portfolio_pnl_service import PortfolioPnlService

PERF = NS(year_start=date(2026, 1, 1), as_of=date(2026, 4, 15))
INPUTS = NS(idx_rate=0.07, idx_monthly=1, eq_rate=0.12, eq_monthly=1, com_rate=0.04, com_monthly=1,
            alt_rate=0.05, alt_monthly=1)


def _eq(**kw):
    return NS(instrument_id="E1", allocation_pct=kw.get("alloc", 50.0), ret=kw.get("ret", 0.05))


def test_month_key_is_calendar_month_end_capped_at_latest_close():
    last = date(2026, 4, 15)
    assert month_key(date(2026, 1, 9), last) == date(2026, 1, 31)
    assert month_key(date(2026, 2, 27), last) == date(2026, 2, 28)
    assert month_key(date(2026, 12, 3), date(2026, 12, 31)) == date(2026, 12, 31)
    assert month_key(date(2026, 4, 2), last) == last              # the running month ends at the latest close


def test_monthly_rows_pair_cumulative_target_with_weighted_actual():
    series = {"E1": {date(2026, 1, 31): 0.02, date(2026, 2, 28): 0.01, date(2026, 4, 15): 0.05},
              "E2": {date(2026, 1, 31): 0.04, date(2026, 2, 28): 0.03, date(2026, 4, 15): 0.07}}
    insts = [_eq(alloc=30.0), NS(instrument_id="E2", allocation_pct=10.0, ret=0.07)]
    eq = next(b for b in compute_bucket_breakdown(insts, PERF, INPUTS, month_returns=series) if b.key == "eq")
    assert [m.month for m in eq.monthly] == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 4, 15)]
    jan = eq.monthly[0]
    assert jan.actual == pytest.approx((30 * 0.02 + 10 * 0.04) / 40)
    assert jan.target == pytest.approx(0.12 * 30 / 365)                       # 1 Jan -> 31 Jan
    assert eq.monthly[-1].target == pytest.approx(eq.target_to_date)         # last row = the headline target
    assert eq.monthly[-1].actual == pytest.approx(eq.ytd_return)             # ...and the headline actual


def test_month_without_prices_has_no_actual_but_keeps_the_target():
    series = {"E1": {date(2026, 1, 31): 0.01, date(2026, 4, 15): 0.05}}
    series["E2"] = {date(2026, 3, 31): 0.02}
    insts = [_eq(), NS(instrument_id="E2", allocation_pct=10.0, ret=0.02)]
    eq = next(b for b in compute_bucket_breakdown(insts, PERF, INPUTS, month_returns=series) if b.key == "eq")
    assert [m.month.month for m in eq.monthly] == [1, 3, 4]                  # Feb has no row for anyone
    assert all(m.target > 0 for m in eq.monthly)


def test_a_month_is_at_risk_when_more_than_two_points_behind_its_target():
    series = {"E1": {date(2026, 1, 31): 0.0, date(2026, 2, 28): -0.03}}
    eq = next(b for b in compute_bucket_breakdown([_eq()], PERF, INPUTS, month_returns=series) if b.key == "eq")
    # Jan: target 0.99%, actual 0.0% -> gap -0.99 pts (within 2).  Feb: target 1.90%, actual -3.0% -> gap -4.9 pts.
    assert [m.at_risk for m in eq.monthly] == [False, True]


def test_no_series_means_no_monthly_rows_and_headline_is_unchanged():
    out = compute_bucket_breakdown([_eq()], PERF, INPUTS)
    assert all(b.monthly == [] for b in out)
    assert next(b for b in out if b.key == "eq").ytd_return == pytest.approx(0.05)


def test_page_service_pins_the_running_month_to_the_instrument_ytd(monkeypatch):
    seen = {}

    def fake(self, ids, start, end):
        seen["args"] = (ids, start, end)
        return {"E1": {date(2026, 1, 31): 0.01, end: 0.99}}                    # 0.99 must be overwritten

    monkeypatch.setattr(PortfolioPnlService, "month_end_returns", fake)
    svc = object.__new__(JarvisPageService)
    svc._db = None
    out = svc._bucket_month_returns([_eq(ret=0.05), NS(instrument_id="X", allocation_pct=1, ret=None)], PERF, "europe")
    assert out["E1"][PERF.as_of] == 0.05
    assert seen["args"] == (["E1"], PERF.year_start, PERF.as_of)               # instruments without a return are skipped


def test_page_service_monthly_failure_degrades_to_no_rows(monkeypatch):
    monkeypatch.setattr(PortfolioPnlService, "month_end_returns", lambda *a: (_ for _ in ()).throw(KeyError("x")))
    svc = object.__new__(JarvisPageService)
    svc._db = None
    assert svc._bucket_month_returns([_eq()], PERF, "europe") is None


def test_month_end_returns_uses_last_bar_of_each_month_and_the_first_bar_as_base(monkeypatch):
    idx = pd.to_datetime(["2025-12-31", "2026-01-15", "2026-01-30", "2026-02-27", "2026-03-10"])
    closes = pd.Series([100.0, 110.0, 120.0, 90.0, 150.0], index=idx)
    svc = object.__new__(PortfolioPnlService)
    svc._closes = lambda iid, s, e: closes if iid == "E1" else pd.Series(dtype=float)
    out = svc.month_end_returns(["E1", "NOPRICE"], date(2026, 1, 1), date(2026, 3, 10))
    assert "NOPRICE" not in out
    assert out["E1"] == {date(2026, 1, 31): pytest.approx(0.20), date(2026, 2, 28): pytest.approx(-0.10),
                         date(2026, 3, 10): pytest.approx(0.50)}
