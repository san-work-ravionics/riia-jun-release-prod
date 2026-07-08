"""RITA Core — Market Regime Classification (Feature 32, Phase 3.6)

Classifies each bar of OHLCV data into Bull / Bear / Sideways so the RL
diagnostic scorecard (``rl_scorecard.py``) can report PER-REGIME metrics
(F3 Market Regime Performance, F5 Baseline Relative per regime, T5 Per-Regime
Action Distribution) — a model that scores well overall but fails in bear
markets is dangerous, and an aggregate Sharpe alone hides that.

Method (REQUIREMENTS.md Phase 3.6 — "Market regime classification method"):
  * Bull:     20-day SMA trend > 0   AND 20-day realized vol < expanding median vol
  * Bear:     20-day SMA trend < 0   AND 20-day realized vol > expanding median vol
  * Sideways: abs(20-day SMA trend) < 0.1%/day (flat)  OR neither bull/bear met

Computed on OHLCV data BEFORE env construction (design decision) — an
"expanding" (not rolling/trailing-window) median volatility comparator is used
so the classification at bar t never looks at data beyond t (no forward-looking
bias, edge case 5 in the Architect design).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import structlog

log = structlog.get_logger(__name__)

REGIME_BULL = "bull"
REGIME_BEAR = "bear"
REGIME_SIDEWAYS = "sideways"

# Flat-trend threshold: |SMA-trend| below this (per-day, fractional) is
# classified Sideways regardless of the vol comparator.
_FLAT_TREND_THRESHOLD = 0.001  # 0.1% per day


def classify_regimes(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Add a ``market_regime`` categorical column (bull/bear/sideways) to ``df``.

    Args:
        df: OHLCV(+indicators) DataFrame. Must have a ``Close`` column and
            (if present) a ``daily_return`` column; ``daily_return`` is derived
            from ``Close`` if missing.
        window: SMA-trend and realized-vol lookback window (default 20 — one
            trading month).

    Returns:
        A COPY of ``df`` with an added ``market_regime`` column
        (values: "bull" | "bear" | "sideways").

    Edge case (short data, <window+1 rows): every bar is labelled "sideways"
    (insufficient history to compute a trend/vol signal) rather than raising —
    callers (rl_scorecard.py F3/F5/T5) treat this as "insufficient_data".
    """
    out = df.copy()

    if len(out) < window + 1:
        out["market_regime"] = REGIME_SIDEWAYS
        log.warning("market_regime.insufficient_data", rows=len(out), window=window)
        return out

    if "daily_return" in out.columns:
        daily_return = out["daily_return"].astype(float)
    else:
        daily_return = out["Close"].astype(float).pct_change()

    # 20-day SMA trend: fractional slope of the SMA over the window, expressed
    # as a per-day rate so it is comparable to the 0.1%/day flat threshold.
    sma = out["Close"].astype(float).rolling(window=window, min_periods=window).mean()
    trend = (sma - sma.shift(window)) / (sma.shift(window).replace(0, np.nan)) / window

    # 20-day realized volatility (std of daily returns over the window).
    realized_vol = daily_return.rolling(window=window, min_periods=window).std()

    # Expanding median volatility — only uses data up to and including bar t,
    # so the comparator never looks ahead. min_periods=window so the very first
    # eligible bars have a stable-enough sample.
    expanding_median_vol = realized_vol.expanding(min_periods=window).median()

    regime = pd.Series(REGIME_SIDEWAYS, index=out.index, dtype=object)

    valid = trend.notna() & realized_vol.notna() & expanding_median_vol.notna()
    is_flat = trend.abs() < _FLAT_TREND_THRESHOLD
    is_bull = valid & ~is_flat & (trend > 0) & (realized_vol < expanding_median_vol)
    is_bear = valid & ~is_flat & (trend < 0) & (realized_vol > expanding_median_vol)

    regime[is_bull] = REGIME_BULL
    regime[is_bear] = REGIME_BEAR
    # Everything else (including the pre-window warm-up rows, flat-trend rows,
    # and "neither bull nor bear" rows) stays REGIME_SIDEWAYS — matches the
    # REQUIREMENTS definition ("OR neither bull nor bear criteria met").

    out["market_regime"] = regime.astype(str)

    counts = out["market_regime"].value_counts().to_dict()
    log.debug("market_regime.classified", window=window, counts=counts)
    return out
