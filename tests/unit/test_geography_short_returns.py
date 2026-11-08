"""F45: geography-overview carries true 5-day and 21-day returns for the Jarvis weekly / monthly panels."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from .test_f28_portfolio_builder import _cache_rec, _get_response, _make_inst


def _series(underlying: str, closes: list[float]) -> list:
    start = date(2026, 1, 1)
    return [_cache_rec(underlying, c, start + timedelta(days=i)) for i, c in enumerate(closes)]


def _instrument(body: dict, inst_id: str) -> dict:
    return next(i for r in body["regions"] for i in r["instruments"] if i["id"] == inst_id)


def test_weekly_and_monthly_returns_use_5_and_21_trading_days_back():
    closes = [100.0 + i for i in range(40)]          # 100 .. 139
    resp, body = _get_response(_series("NIFTY", closes), [_make_inst("NIFTY", "IN", "NIFTY 50")])
    assert resp.status_code == 200, resp.text
    n = _instrument(body, "NIFTY")
    assert n["return_1w_pct"] == pytest.approx((139.0 / 134.0 - 1) * 100, abs=1e-3)
    assert n["return_1m_pct"] == pytest.approx((139.0 / 118.0 - 1) * 100, abs=1e-3)


def test_short_history_gives_null_not_a_guess():
    resp, body = _get_response(_series("NIFTY", [100.0, 101.0, 102.0]), [_make_inst("NIFTY", "IN", "NIFTY 50")])
    n = _instrument(body, "NIFTY")
    assert n["return_1w_pct"] is None and n["return_1m_pct"] is None
    assert n["daily_return_pct"] is not None            # existing field unchanged


def test_instrument_without_prices_has_null_short_returns():
    resp, body = _get_response([], [_make_inst("NIFTY", "IN", "NIFTY 50")])
    n = _instrument(body, "NIFTY")
    assert n["return_1w_pct"] is None and n["return_1m_pct"] is None
