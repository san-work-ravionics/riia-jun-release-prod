"""Unit tests for rita.core.market_regime (Feature 32, Phase 3.6).

Covers bull/bear/sideways classification on synthetic constructed data and
the short-data edge case (< window+1 rows -> all sideways, no crash).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rita.core.market_regime import (
    REGIME_BEAR,
    REGIME_BULL,
    REGIME_SIDEWAYS,
    classify_regimes,
)


def _make_price_path(prices: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=len(prices), freq="D")
    close = pd.Series(prices, index=idx)
    daily_return = close.pct_change().fillna(0.0)
    return pd.DataFrame({"Close": close, "daily_return": daily_return}, index=idx)


def test_short_data_all_sideways_no_crash():
    """Edge case: fewer than window+1 rows must not raise, and label everything sideways."""
    df = _make_price_path([100.0 + i for i in range(10)])  # 10 rows, window default 20
    out = classify_regimes(df, window=20)
    assert "market_regime" in out.columns
    assert (out["market_regime"] == REGIME_SIDEWAYS).all()


def test_exactly_window_rows_all_sideways():
    df = _make_price_path([100.0] * 20)  # == window, < window + 1
    out = classify_regimes(df, window=20)
    assert (out["market_regime"] == REGIME_SIDEWAYS).all()


def test_strong_uptrend_low_vol_classified_bull():
    """Smooth, steady uptrend (low realized vol relative to its own history) -> bull."""
    n = 120
    prices = [100.0 * (1.002 ** i) for i in range(n)]  # smooth +0.2%/day compounding
    df = _make_price_path(prices)
    out = classify_regimes(df, window=20)
    # Later bars (after enough history for a stable expanding median) should be bull.
    tail = out["market_regime"].iloc[60:]
    assert (tail == REGIME_BULL).mean() > 0.5, f"expected mostly bull, got {tail.value_counts()}"


def test_downtrend_high_vol_classified_bear():
    """Sharp, volatile downtrend (trend<0, vol above its own expanding median) -> bear."""
    rng = np.random.default_rng(42)
    n = 120
    prices = [100.0]
    for i in range(1, n):
        # Steady decline (-0.3%/day) with an amplitude ramp so later vol > earlier vol,
        # pushing later realized_vol above the expanding median of earlier (calmer) vol.
        noise_scale = 0.002 + 0.02 * (i / n)
        step = -0.003 + rng.normal(0, noise_scale)
        prices.append(prices[-1] * (1 + step))
    df = _make_price_path(prices)
    out = classify_regimes(df, window=20)
    tail = out["market_regime"].iloc[90:]
    assert (tail == REGIME_BEAR).mean() > 0.3, f"expected a meaningful bear share, got {tail.value_counts()}"


def test_flat_market_classified_sideways():
    """Flat trend (< 0.1%/day) -> sideways regardless of vol comparator."""
    rng = np.random.default_rng(7)
    n = 120
    prices = [100.0]
    for _ in range(1, n):
        # Zero-drift small noise: trend should stay well under the 0.1%/day threshold.
        prices.append(prices[-1] * (1 + rng.normal(0, 0.001)))
    df = _make_price_path(prices)
    out = classify_regimes(df, window=20)
    tail = out["market_regime"].iloc[40:]
    assert (tail == REGIME_SIDEWAYS).mean() > 0.5, f"expected mostly sideways, got {tail.value_counts()}"


def test_regime_column_never_null():
    df = _make_price_path([100.0 + i * 0.5 for i in range(50)])
    out = classify_regimes(df, window=20)
    assert out["market_regime"].isna().sum() == 0
    assert set(out["market_regime"].unique()).issubset({REGIME_BULL, REGIME_BEAR, REGIME_SIDEWAYS})


def test_classify_regimes_returns_copy_not_mutating_input():
    df = _make_price_path([100.0 + i for i in range(50)])
    original_cols = list(df.columns)
    out = classify_regimes(df, window=20)
    assert list(df.columns) == original_cols  # input untouched
    assert "market_regime" in out.columns
    assert out is not df


def test_derives_daily_return_when_missing():
    idx = pd.date_range("2020-01-01", periods=60, freq="D")
    close = pd.Series([100.0 + i for i in range(60)], index=idx)
    df = pd.DataFrame({"Close": close}, index=idx)  # no daily_return column
    out = classify_regimes(df, window=20)
    assert "market_regime" in out.columns
    assert out["market_regime"].isna().sum() == 0


# ── QA Agent: additional edge-case coverage ──────────────────────────────────


def test_all_nan_close_values_all_sideways():
    """Edge case: all-NaN Close values must not raise and label everything sideways."""
    idx = pd.date_range("2020-01-01", periods=60, freq="D")
    df = pd.DataFrame({
        "Close": np.full(60, np.nan),
        "daily_return": np.full(60, np.nan),
    }, index=idx)
    out = classify_regimes(df, window=20)
    assert "market_regime" in out.columns
    assert (out["market_regime"] == REGIME_SIDEWAYS).all()


def test_constant_close_all_sideways():
    """Constant price -> zero daily_return -> zero SMA trend -> flat threshold
    met -> all sideways. Must not divide by zero in trend computation."""
    df = _make_price_path([100.0] * 60)
    out = classify_regimes(df, window=20)
    # After warm-up, trend is 0.0 -> flat -> sideways (pre-window rows are also sideways)
    assert (out["market_regime"] == REGIME_SIDEWAYS).all()


def test_single_regime_pure_bull():
    """A smooth, sustained uptrend with low noise should produce only bull
    labels (or bull + initial sideways warm-up). No bear labels expected."""
    n = 200
    prices = [100.0 * (1.001 ** i) for i in range(n)]
    df = _make_price_path(prices)
    out = classify_regimes(df, window=20)
    # After the expanding-median has stabilized (~2x window), should be all bull or sideways
    tail = out["market_regime"].iloc[80:]
    assert REGIME_BEAR not in tail.values, f"pure uptrend should have no bear labels, got {tail.value_counts()}"
