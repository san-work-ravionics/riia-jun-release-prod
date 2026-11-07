"""F45 Phase A: bucket breakdown — target and actual must cover the same period."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace as NS

import pytest

from rita.services.jarvis_page_service import JarvisPageService


def _svc(perf, instruments) -> JarvisPageService:
    svc = object.__new__(JarvisPageService)
    svc.portfolio = lambda location: NS(perf=perf, instruments=instruments)  # type: ignore[method-assign]
    return svc


def _inputs(**kw):
    base = dict(idx_rate=0.07, idx_monthly=400, eq_rate=0.10, eq_monthly=400,
                com_rate=0.04, com_monthly=100, alt_rate=0.05, alt_monthly=100)
    base.update(kw)
    return NS(**base)


def _by_key(result):
    return {b.key: b for b in result}


def test_target_uses_the_return_period_not_jan1_to_today():
    # Saved 7 Nov, latest close 13 Nov -> 6 days of return. A 10%/yr target over 6 days is ~0.16%,
    # so a 0.1% return is on pace. (Pro-rating from 1 Jan would give ~8.5% and flag At Risk.)
    perf = NS(year_start=date(2026, 11, 7), as_of=date(2026, 11, 13))
    inst = [NS(instrument_id="ASRNL", allocation_pct=20.0, ret=0.001)]
    eq = _by_key(_svc(perf, inst)._bucket_breakdown("europe", _inputs()))["eq"]
    assert eq.target_to_date == pytest.approx(0.10 * 6 / 365.0, abs=1e-9)
    assert eq.gap == pytest.approx(0.001 - 0.10 * 6 / 365.0, abs=1e-9)
    assert eq.at_risk is False


def test_full_year_period_matches_annual_rate():
    perf = NS(year_start=date(2026, 1, 1), as_of=date(2026, 12, 31))
    inst = [NS(instrument_id="BANKNIFTY", allocation_pct=60.0, ret=0.07)]
    idx = _by_key(_svc(perf, inst)._bucket_breakdown("india", _inputs()))["idx"]
    assert idx.target_to_date == pytest.approx(0.07 * 364 / 365.0, abs=1e-9)
    assert [i.instrument_id for i in idx.instruments] == ["BANKNIFTY"]


def test_at_risk_when_gap_exceeds_threshold_over_same_period():
    perf = NS(year_start=date(2026, 1, 1), as_of=date(2026, 12, 31))
    inst = [NS(instrument_id="ASML", allocation_pct=20.0, ret=0.01)]
    eq = _by_key(_svc(perf, inst)._bucket_breakdown("europe", _inputs()))["eq"]
    assert eq.gap < -0.02
    assert eq.at_risk is True


def test_stale_prices_before_save_date_gives_zero_target_and_no_status():
    # as_of (latest close) is before the save date: nothing to measure -> no status, never At Risk.
    perf = NS(year_start=date(2026, 11, 7), as_of=date(2026, 9, 18))
    inst = [NS(instrument_id="ASRNL", allocation_pct=20.0, ret=None)]
    eq = _by_key(_svc(perf, inst)._bucket_breakdown("europe", _inputs()))["eq"]
    assert eq.target_to_date == 0.0
    assert eq.ytd_return is None and eq.gap is None and eq.at_risk is None


def test_falls_back_to_calendar_year_without_perf():
    inst = [NS(instrument_id="ASRNL", allocation_pct=20.0, ret=None)]
    eq = _by_key(_svc(None, inst)._bucket_breakdown("europe", _inputs()))["eq"]
    today = date.today()
    expected = 0.10 * (today - date(today.year, 1, 1)).days / 365.0
    assert eq.target_to_date == pytest.approx(expected, abs=1e-9)


def test_no_instruments_still_returns_all_buckets_with_no_status():
    perf = NS(year_start=date(2026, 11, 7), as_of=date(2026, 11, 13))
    out = _svc(perf, [])._bucket_breakdown("europe", _inputs())
    assert [b.key for b in out] == ["idx", "eq", "com", "alt"]
    assert all(b.at_risk is None and b.ytd_return is None for b in out)


def test_zero_elapsed_days_is_no_status_not_on_track():
    # Saved on a day with no later close: the period is 0 days, ret is 0.0 and target is 0.0 -> the
    # gap is 0 but nothing has been measured, so the bucket is neither on track nor at risk.
    perf = NS(year_start=date(2026, 11, 6), as_of=date(2026, 11, 6))
    inst = [NS(instrument_id="ASRNL", allocation_pct=20.0, ret=0.0)]
    eq = _by_key(_svc(perf, inst)._bucket_breakdown("europe", _inputs()))["eq"]
    assert eq.target_to_date == 0.0 and eq.ytd_return == 0.0 and eq.gap == 0.0
    assert eq.at_risk is None
