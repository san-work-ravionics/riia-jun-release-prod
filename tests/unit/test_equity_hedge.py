"""Unit tests for equity_hedge_scenarios (Feature 25 — ASML Equity Hedge).

Tests cover:
- Happy path: realistic 25-row ASML DataFrame → verify full response shape.
- Edge case 1: insufficient data (fewer than 5 rows) → ValueError raised.
- Edge case 2: zero-variance data (all Close prices identical) → no raise;
  vol falls back to 0.25; valid dict returned.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_asml_df(n_rows: int = 25, price: float | None = None) -> pd.DataFrame:
    """Return a DataFrame of ASML daily OHLCV data with a DatetimeIndex.

    If *price* is given, every Close row is that constant value (zero-variance).
    Otherwise prices drift upward from ~700 to ~750 over *n_rows* rows.
    """
    start = pd.Timestamp("2025-01-01")
    # Use business-day offsets so the index resembles real trading data
    idx = pd.bdate_range(start=start, periods=n_rows)

    if price is not None:
        closes = np.full(n_rows, float(price))
    else:
        closes = np.linspace(700.0, 750.0, n_rows)

    df = pd.DataFrame(
        {
            "Close": closes,
            "Open":  closes * 0.995,
            "High":  closes * 1.005,
            "Low":   closes * 0.990,
            "Volume": np.full(n_rows, 100_000.0),
        },
        index=idx,
    )
    return df


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEquityHedgeScenariosHappyPath:
    """Happy-path test: 25-row realistic DataFrame, standard call."""

    PATCH_TARGET = "rita.core.portfolio_engine._load_with_indicators"

    def test_top_level_keys_present(self):
        df = _make_asml_df(25)
        with patch(self.PATCH_TARGET, return_value=df):
            from rita.core.portfolio_engine import equity_hedge_scenarios
            result = equity_hedge_scenarios("ASML", 10, "2025-01-01", "2025-01-31")

        assert set(result.keys()) == {"portfolio", "hedge_scenarios"}

    def test_portfolio_keys(self):
        df = _make_asml_df(25)
        with patch(self.PATCH_TARGET, return_value=df):
            from rita.core.portfolio_engine import equity_hedge_scenarios
            result = equity_hedge_scenarios("ASML", 10, "2025-01-01", "2025-01-31")

        p = result["portfolio"]
        required = {"start_price", "end_price", "return_pct", "vol_30d_pct", "daily"}
        assert required.issubset(set(p.keys())), (
            f"Missing portfolio keys: {required - set(p.keys())}"
        )

    def test_hedge_scenarios_top_level_keys(self):
        df = _make_asml_df(25)
        with patch(self.PATCH_TARGET, return_value=df):
            from rita.core.portfolio_engine import equity_hedge_scenarios
            result = equity_hedge_scenarios("ASML", 10, "2025-01-01", "2025-01-31")

        hs = result["hedge_scenarios"]
        assert set(hs.keys()) == {"mild_bearish", "strong_bearish", "payoff_curves", "data_source"}

    def test_payoff_curves_array_length_33(self):
        df = _make_asml_df(25)
        with patch(self.PATCH_TARGET, return_value=df):
            from rita.core.portfolio_engine import equity_hedge_scenarios
            result = equity_hedge_scenarios("ASML", 10, "2025-01-01", "2025-01-31")

        pc = result["hedge_scenarios"]["payoff_curves"]
        for key in ("price_range", "unhedged", "covered_call", "protective_put"):
            assert len(pc[key]) == 33, (
                f"payoff_curves['{key}'] has {len(pc[key])} elements, expected 33"
            )

    def test_daily_series_non_empty(self):
        df = _make_asml_df(25)
        with patch(self.PATCH_TARGET, return_value=df):
            from rita.core.portfolio_engine import equity_hedge_scenarios
            result = equity_hedge_scenarios("ASML", 10, "2025-01-01", "2025-01-31")

        daily = result["portfolio"]["daily"]
        assert len(daily) > 0, "daily series should not be empty"
        # Each row must have date, price, value
        first = daily[0]
        assert "date" in first and "price" in first and "value" in first

    def test_return_pct_numerically_correct(self):
        df = _make_asml_df(25)
        with patch(self.PATCH_TARGET, return_value=df):
            from rita.core.portfolio_engine import equity_hedge_scenarios
            result = equity_hedge_scenarios("ASML", 10, "2025-01-01", "2025-01-31")

        p = result["portfolio"]
        expected = round((p["end_price"] - p["start_price"]) / p["start_price"] * 100, 4)
        assert abs(p["return_pct"] - expected) < 0.001

    def test_mild_bearish_fields_present(self):
        df = _make_asml_df(25)
        with patch(self.PATCH_TARGET, return_value=df):
            from rita.core.portfolio_engine import equity_hedge_scenarios
            result = equity_hedge_scenarios("ASML", 10, "2025-01-01", "2025-01-31")

        mb = result["hedge_scenarios"]["mild_bearish"]
        required = {"strategy", "strike_label", "premium_per_share", "total_premium_eur",
                    "max_value_eur", "breakeven_price", "description"}
        assert required.issubset(set(mb.keys())), (
            f"Missing mild_bearish keys: {required - set(mb.keys())}"
        )

    def test_strong_bearish_fields_present(self):
        df = _make_asml_df(25)
        with patch(self.PATCH_TARGET, return_value=df):
            from rita.core.portfolio_engine import equity_hedge_scenarios
            result = equity_hedge_scenarios("ASML", 10, "2025-01-01", "2025-01-31")

        sb = result["hedge_scenarios"]["strong_bearish"]
        required = {"strategy", "strike_label", "premium_per_share", "total_premium_eur",
                    "floor_value_eur", "breakeven_price", "description"}
        assert required.issubset(set(sb.keys())), (
            f"Missing strong_bearish keys: {required - set(sb.keys())}"
        )


class TestEquityHedgeScenariosEdgeCaseInsufficientData:
    """Edge case 1: fewer than 5 trading rows → ValueError."""

    PATCH_TARGET = "rita.core.portfolio_engine._load_with_indicators"

    def test_raises_value_error_on_2_rows(self):
        df = _make_asml_df(2)
        with patch(self.PATCH_TARGET, return_value=df):
            from rita.core.portfolio_engine import equity_hedge_scenarios
            with pytest.raises(ValueError, match="Insufficient data"):
                equity_hedge_scenarios("ASML", 10, "2025-01-01", "2025-01-31")

    def test_raises_value_error_on_4_rows(self):
        df = _make_asml_df(4)
        with patch(self.PATCH_TARGET, return_value=df):
            from rita.core.portfolio_engine import equity_hedge_scenarios
            with pytest.raises(ValueError, match="Insufficient data"):
                equity_hedge_scenarios("ASML", 10, "2025-01-01", "2025-01-31")

    def test_does_not_raise_on_5_rows(self):
        """Boundary: exactly 5 rows should succeed (>= 5 required)."""
        df = _make_asml_df(5)
        with patch(self.PATCH_TARGET, return_value=df):
            from rita.core.portfolio_engine import equity_hedge_scenarios
            result = equity_hedge_scenarios("ASML", 10, "2025-01-01", "2025-01-31")
        assert "portfolio" in result


class TestEquityHedgeScenariosEdgeCaseZeroVariance:
    """Edge case 2: all Close prices identical → vol falls back to 0.25; no raise."""

    PATCH_TARGET = "rita.core.portfolio_engine._load_with_indicators"

    def test_does_not_raise(self):
        df = _make_asml_df(25, price=750.0)
        with patch(self.PATCH_TARGET, return_value=df):
            from rita.core.portfolio_engine import equity_hedge_scenarios
            # Must not raise even though log-return std = 0
            result = equity_hedge_scenarios("ASML", 10, "2025-01-01", "2025-01-31")
        assert result is not None

    def test_vol_fallback_is_25_pct(self):
        """vol_30d_pct should be 25.0 when all prices are identical (sigma=0 → fallback)."""
        df = _make_asml_df(25, price=750.0)
        with patch(self.PATCH_TARGET, return_value=df):
            from rita.core.portfolio_engine import equity_hedge_scenarios
            result = equity_hedge_scenarios("ASML", 10, "2025-01-01", "2025-01-31")

        # sigma falls back to 0.25 → vol_30d_pct = 25.0
        assert abs(result["portfolio"]["vol_30d_pct"] - 25.0) < 0.001, (
            f"Expected vol_30d_pct=25.0 (fallback), got {result['portfolio']['vol_30d_pct']}"
        )

    def test_returns_valid_dict_structure(self):
        df = _make_asml_df(25, price=750.0)
        with patch(self.PATCH_TARGET, return_value=df):
            from rita.core.portfolio_engine import equity_hedge_scenarios
            result = equity_hedge_scenarios("ASML", 10, "2025-01-01", "2025-01-31")

        assert "portfolio" in result
        assert "hedge_scenarios" in result
        pc = result["hedge_scenarios"]["payoff_curves"]
        assert len(pc["price_range"]) == 33
