"""F44 P4 — ``fno.sigma_levels`` parity with the FnO position-value bands (same pure helpers, same
253-close window): for one share the levels equal ``PositionValueService.build`` bands; the
per-month band is anchored at the previous month's last close with that date's trailing σ.
Statistical, not a model."""
# ruff: noqa: F811 — pytest fixtures imported from a sibling module are redefined as test params
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from rita.models.market_data import MarketDataCacheModel
from rita.models.user import UserModel
from rita.models.user_portfolio import UserPortfolioModel
from rita.models.user_portfolio_key import UserPortfolioKeyModel
from rita.services.position_value_service import (
    VOL_WINDOW_CLOSES,
    PositionValueService,
    ann_vol_pct_from_closes,
    build_bands,
)

from .f44_p4_helpers import journey_db  # noqa: F401 — fixture

DATES = pd.bdate_range("2025-01-02", "2026-06-30")


@pytest.fixture
def px_db(journey_db):
    db = journey_db
    closes = 800.0 * np.cumprod(1 + 0.0004 + np.random.default_rng(42).normal(0, 0.012, len(DATES)))
    for d, c in zip(DATES, closes):
        db.add(MarketDataCacheModel(cache_id=f"ASML-{d.date()}", date=d.date(), underlying="ASML", open=c, high=c,
                                    low=c, close=float(c), recorded_at=datetime(2026, 7, 1)))
    db.add(UserModel(id="alice"))
    db.add(UserPortfolioKeyModel(key_id="k1", user_id="alice"))
    db.add(UserPortfolioModel(portfolio_id="p", key_id="k1", name="p", currency="EUR", location="europe",
                              holdings=[{"instrument_id": "ASML", "allocation_pct": 100, "shares": 1}],
                              is_active=True))
    db.commit()
    return db, pd.Series(closes, index=DATES)


def test_levels_equal_position_value_bands(px_db):
    db, closes = px_db
    svc = PositionValueService(db)
    sig = svc.sigma_levels("asml", 12)
    pv = svc.build(db.get(UserModel, "alice"), "ASML", 12, None).items[0]
    assert sig.status == "ok" and pv.status == "ok"
    assert sig.ann_vol_pct == pv.ann_vol_pct and sig.monthly_sigma_pct == pv.monthly_sigma_pct
    assert sig.levels.entry == pv.bands.anchor_value
    assert sig.levels.plus_1sigma == pv.bands.plus_1sigma_value
    assert sig.levels.minus_1sigma == pv.bands.minus_1sigma_value
    assert sig.lookback_returns == VOL_WINDOW_CLOSES - 1 == 252
    assert sig.currency == "EUR" and sig.as_of == DATES[-1].date()
    assert len(sig.closes) == len(pv.daily)


def test_monthly_band_anchored_at_previous_month_end(px_db):
    db, closes = px_db
    sig = PositionValueService(db).sigma_levels("ASML", 6)
    m = next(x for x in sig.monthly if x.month == "2026-03")
    prev = closes[closes.index < pd.Timestamp("2026-03-01")]
    vol = ann_vol_pct_from_closes(list(prev.iloc[-VOL_WINDOW_CLOSES:]))
    b = build_bands(prev.iloc[-1], prev.index[-1].date(), vol)
    assert (m.anchor_close, m.plus_1sigma, m.minus_1sigma, m.ann_vol_pct) == (
        b.anchor_value, b.plus_1sigma_value, b.minus_1sigma_value, vol)
    assert [x.month for x in sig.monthly] == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]


def test_unknown_instrument_is_no_price_data(journey_db):
    out = PositionValueService(journey_db).sigma_levels("NOPE")
    assert out.status == "no_price_data" and out.levels is None
