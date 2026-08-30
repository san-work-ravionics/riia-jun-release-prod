"""RITA Core — ASTA GEO PAN Indicator Engine (Feature 37)

Computes all technical indicators required by the three ASTA GEO PAN
trading setups (Triple Screen, Swing Trader DB/DT, Momentum BB Challenge).

Reuses ``technical_analyzer.calculate_indicators()`` for the base set
(RSI, MACD, BB, ATR, EMA 5/13/26/50/200, trend_score, ema_ratio,
daily_return), then adds ASTA-specific indicators on top.

Multi-timeframe: Tide = Monthly, Wave = Weekly, Ripple = Daily.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import structlog
import ta

from rita.core.technical_analyzer import calculate_indicators

log = structlog.get_logger(__name__)


# ── Swing-point detection ────────────────────────────────────────────────────

def _detect_swing_points(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """Identify swing highs and swing lows using a rolling window.

    A swing high is a bar whose High is the highest in a 2*lookback+1 window.
    A swing low is a bar whose Low is the lowest in a 2*lookback+1 window.
    """
    out = df.copy()
    window = 2 * lookback + 1

    rolling_max = out["High"].rolling(window, center=True).max()
    rolling_min = out["Low"].rolling(window, center=True).min()

    out["swing_high"] = np.where(out["High"] == rolling_max, out["High"], np.nan)
    out["swing_low"] = np.where(out["Low"] == rolling_min, out["Low"], np.nan)

    return out


def _trend_structure(df: pd.DataFrame) -> pd.DataFrame:
    """Classify trend structure based on the last two swing highs and lows.

    Sets boolean columns: trend_hh_hl (uptrend), trend_lh_ll (downtrend).
    """
    out = df.copy()
    sh = out["swing_high"].dropna()
    sl = out["swing_low"].dropna()

    trend_hh_hl = pd.Series(False, index=out.index)
    trend_lh_ll = pd.Series(False, index=out.index)

    for i in range(len(out)):
        idx = out.index[i]
        prev_sh = sh[sh.index <= idx]
        prev_sl = sl[sl.index <= idx]

        if len(prev_sh) >= 2 and len(prev_sl) >= 2:
            last_2_highs = prev_sh.iloc[-2:]
            last_2_lows = prev_sl.iloc[-2:]
            hh = last_2_highs.iloc[-1] > last_2_highs.iloc[-2]
            hl = last_2_lows.iloc[-1] > last_2_lows.iloc[-2]
            lh = last_2_highs.iloc[-1] < last_2_highs.iloc[-2]
            ll = last_2_lows.iloc[-1] < last_2_lows.iloc[-2]
            trend_hh_hl.iloc[i] = hh and hl
            trend_lh_ll.iloc[i] = lh and ll

    out["trend_hh_hl"] = trend_hh_hl
    out["trend_lh_ll"] = trend_lh_ll
    return out


# ── Fibonacci retracement ────────────────────────────────────────────────────

def _fibonacci_levels(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Fibonacci retracement percentage of the last completed swing wave.

    For each bar, finds the most recent swing high and swing low, determines
    the wave direction, and computes where the current price sits relative
    to 38.2%, 50%, and 61.8% retracement levels.
    """
    out = df.copy()
    fib_pct = pd.Series(np.nan, index=out.index)
    fib_382 = pd.Series(np.nan, index=out.index)
    fib_500 = pd.Series(np.nan, index=out.index)
    fib_618 = pd.Series(np.nan, index=out.index)

    sh = out["swing_high"].dropna()
    sl = out["swing_low"].dropna()

    for i in range(len(out)):
        idx = out.index[i]
        prev_sh = sh[sh.index <= idx]
        prev_sl = sl[sl.index <= idx]

        if len(prev_sh) < 1 or len(prev_sl) < 1:
            continue

        last_high_idx = prev_sh.index[-1]
        last_low_idx = prev_sl.index[-1]
        last_high = prev_sh.iloc[-1]
        last_low = prev_sl.iloc[-1]

        wave_range = last_high - last_low
        if wave_range <= 0:
            continue

        fib_382.iloc[i] = last_high - 0.382 * wave_range
        fib_500.iloc[i] = last_high - 0.500 * wave_range
        fib_618.iloc[i] = last_high - 0.618 * wave_range

        if last_high_idx > last_low_idx:
            retracement = (last_high - out["Close"].iloc[i]) / wave_range
        else:
            retracement = (out["Close"].iloc[i] - last_low) / wave_range

        fib_pct.iloc[i] = retracement

    out["fib_382"] = fib_382
    out["fib_500"] = fib_500
    out["fib_618"] = fib_618
    out["fib_pct"] = fib_pct
    return out


# ── Candlestick pattern detection ────────────────────────────────────────────

def _candlestick_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """Detect key candlestick patterns from OHLC data.

    Returns boolean columns for each pattern.
    """
    out = df.copy()
    op, h, lo, c = out["Open"], out["High"], out["Low"], out["Close"]
    body = (c - op).abs()
    upper_shadow = h - pd.concat([op, c], axis=1).max(axis=1)
    lower_shadow = pd.concat([op, c], axis=1).min(axis=1) - lo
    avg_body = body.rolling(10).mean()

    out["cdl_bullish_engulf"] = (
        (c.shift(1) < op.shift(1)) &  # prev bearish
        (c > op) &                      # current bullish
        (op <= c.shift(1)) &            # open <= prev close
        (c >= op.shift(1))              # close >= prev open
    )

    out["cdl_bearish_engulf"] = (
        (c.shift(1) > op.shift(1)) &  # prev bullish
        (c < op) &                      # current bearish
        (op >= c.shift(1)) &            # open >= prev close
        (c <= op.shift(1))              # close <= prev open
    )

    out["cdl_piercing"] = (
        (c.shift(1) < op.shift(1)) &                    # prev bearish
        (c > op) &                                        # current bullish
        (op < c.shift(1)) &                               # open below prev close
        (c > (op.shift(1) + c.shift(1)) / 2) &           # close above midpoint
        (c < op.shift(1))                                  # close below prev open
    )

    out["cdl_dark_cloud"] = (
        (c.shift(1) > op.shift(1)) &                    # prev bullish
        (c < op) &                                        # current bearish
        (op > c.shift(1)) &                               # open above prev close
        (c < (op.shift(1) + c.shift(1)) / 2) &           # close below midpoint
        (c > op.shift(1))                                  # close above prev open
    )

    out["cdl_hammer"] = (
        (lower_shadow >= body * 2) &
        (upper_shadow <= body * 0.3) &
        (body > 0)
    )

    out["cdl_shooting_star"] = (
        (upper_shadow >= body * 2) &
        (lower_shadow <= body * 0.3) &
        (body > 0)
    )

    # Morning Star: 3-bar pattern (bearish, small body, bullish)
    small_body = body < avg_body * 0.5
    out["cdl_morning_star"] = (
        (c.shift(2) < op.shift(2)) &      # bar -2 bearish
        small_body.shift(1) &              # bar -1 small body
        (c > op) &                          # bar 0 bullish
        (c > (op.shift(2) + c.shift(2)) / 2)  # close above midpoint of bar -2
    )

    out["cdl_evening_star"] = (
        (c.shift(2) > op.shift(2)) &      # bar -2 bullish
        small_body.shift(1) &              # bar -1 small body
        (c < op) &                          # bar 0 bearish
        (c < (op.shift(2) + c.shift(2)) / 2)  # close below midpoint of bar -2
    )

    return out


# ── Crossover and divergence detection ───────────────────────────────────────

def _crossover_flags(df: pd.DataFrame, lookback: int = 3) -> pd.DataFrame:
    """Detect EMA, RSI, Stochastic, and DI crossovers within a lookback window."""
    out = df.copy()

    def _crossed_above(fast: pd.Series, slow: pd.Series, n: int) -> pd.Series:
        cross = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        return cross.rolling(n, min_periods=1).max().astype(bool)

    def _crossed_below(fast: pd.Series, slow: pd.Series, n: int) -> pd.Series:
        cross = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        return cross.rolling(n, min_periods=1).max().astype(bool)

    # EMA crossovers
    out["ema_5_cross_13_up"] = _crossed_above(out["ema_5"], out["ema_13"], lookback)
    out["ema_5_cross_13_down"] = _crossed_below(out["ema_5"], out["ema_13"], lookback)
    out["ema_5_cross_26_up"] = _crossed_above(out["ema_5"], out["ema_26"], lookback)
    out["ema_5_cross_26_down"] = _crossed_below(out["ema_5"], out["ema_26"], lookback)

    # RSI level crosses
    rsi = out["rsi_14"]
    out["rsi_cross_above_40"] = _crossed_above(rsi, pd.Series(40.0, index=rsi.index), lookback)
    out["rsi_cross_above_60"] = _crossed_above(rsi, pd.Series(60.0, index=rsi.index), lookback)
    out["rsi_cross_below_60"] = _crossed_below(rsi, pd.Series(60.0, index=rsi.index), lookback)
    out["rsi_cross_below_40"] = _crossed_below(rsi, pd.Series(40.0, index=rsi.index), lookback)

    # Stochastic crossovers
    out["stoch_pco"] = _crossed_above(out["stoch_k"], out["stoch_d"], lookback)
    out["stoch_nco"] = _crossed_below(out["stoch_k"], out["stoch_d"], lookback)
    out["stoch_oversold_pco"] = out["stoch_pco"] & (out["stoch_k"].shift(1) < 20)
    out["stoch_overbought_nco"] = out["stoch_nco"] & (out["stoch_k"].shift(1) > 80)

    # DI crossovers
    out["di_pco"] = _crossed_above(out["di_plus"], out["di_minus"], lookback)
    out["di_nco"] = _crossed_below(out["di_plus"], out["di_minus"], lookback)

    # MACD histogram direction
    out["macd_hist_uptick"] = out["macd_hist"] > out["macd_hist"].shift(1)
    out["macd_hist_downtick"] = out["macd_hist"] < out["macd_hist"].shift(1)

    return out


def _divergence_detection(df: pd.DataFrame) -> pd.DataFrame:
    """Detect bullish and bearish divergences between price and RSI/Stochastic.

    Bullish divergence: price makes lower low but indicator makes higher low.
    Bearish divergence: price makes higher high but indicator makes lower high.
    """
    out = df.copy()
    out["rsi_bullish_div"] = False
    out["rsi_bearish_div"] = False
    out["stoch_bullish_div"] = False
    out["stoch_bearish_div"] = False

    sl = out["swing_low"].dropna()
    sh = out["swing_high"].dropna()

    for col_prefix, indicator_col in [("rsi", "rsi_14"), ("stoch", "stoch_k")]:
        for i in range(len(sl)):
            if i < 1:
                continue
            idx_curr = sl.index[i]
            idx_prev = sl.index[i - 1]
            price_ll = out.loc[idx_curr, "Low"] < out.loc[idx_prev, "Low"]
            ind_hl = out.loc[idx_curr, indicator_col] > out.loc[idx_prev, indicator_col]
            if price_ll and ind_hl:
                out.loc[idx_curr, f"{col_prefix}_bullish_div"] = True

        for i in range(len(sh)):
            if i < 1:
                continue
            idx_curr = sh.index[i]
            idx_prev = sh.index[i - 1]
            price_hh = out.loc[idx_curr, "High"] > out.loc[idx_prev, "High"]
            ind_lh = out.loc[idx_curr, indicator_col] < out.loc[idx_prev, indicator_col]
            if price_hh and ind_lh:
                out.loc[idx_curr, f"{col_prefix}_bearish_div"] = True

    return out


# ── Double Bottom / Double Top detection ─────────────────────────────────────

def _detect_db_dt(df: pd.DataFrame, tolerance_pct: float = 0.02,
                  min_candles_between: int = 8) -> pd.DataFrame:
    """Detect Double Bottom and Double Top patterns from swing points.

    DB: two swing lows within ``tolerance_pct`` of each other, with at least
    ``min_candles_between`` bars between them.
    DT: same logic for swing highs.
    """
    out = df.copy()
    out["pattern_double_bottom"] = False
    out["pattern_double_top"] = False

    sl = out["swing_low"].dropna()
    sh = out["swing_high"].dropna()

    for i in range(1, len(sl)):
        idx_curr = sl.index[i]
        idx_prev = sl.index[i - 1]
        candles_between = out.index.get_loc(idx_curr) - out.index.get_loc(idx_prev)
        if candles_between < min_candles_between:
            continue
        price_diff_pct = abs(sl.iloc[i] - sl.iloc[i - 1]) / sl.iloc[i - 1]
        if price_diff_pct <= tolerance_pct:
            out.loc[idx_curr, "pattern_double_bottom"] = True

    for i in range(1, len(sh)):
        idx_curr = sh.index[i]
        idx_prev = sh.index[i - 1]
        candles_between = out.index.get_loc(idx_curr) - out.index.get_loc(idx_prev)
        if candles_between < min_candles_between:
            continue
        price_diff_pct = abs(sh.iloc[i] - sh.iloc[i - 1]) / sh.iloc[i - 1]
        if price_diff_pct <= tolerance_pct:
            out.loc[idx_curr, "pattern_double_top"] = True

    return out


# ── Multi-timeframe resampling ───────────────────────────────────────────────

def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample daily OHLCV to a coarser timeframe (W for weekly, ME for monthly)."""
    resampled = df.resample(rule).agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna(subset=["Close"])
    return resampled


def _compute_timeframe_indicators(df_daily: pd.DataFrame, rule: str,
                                   prefix: str) -> pd.DataFrame:
    """Resample daily data, compute indicators on the coarser timeframe,
    and forward-fill back onto the daily index with a column prefix."""
    resampled = _resample_ohlcv(df_daily, rule)
    resampled_with_ind = calculate_indicators(resampled)

    stoch = ta.momentum.StochasticOscillator(
        high=resampled_with_ind["High"], low=resampled_with_ind["Low"],
        close=resampled_with_ind["Close"], window=14, smooth_window=3,
    )
    resampled_with_ind["stoch_k"] = stoch.stoch()
    resampled_with_ind["stoch_d"] = stoch.stoch_signal()

    adx_ind = ta.trend.ADXIndicator(
        high=resampled_with_ind["High"], low=resampled_with_ind["Low"],
        close=resampled_with_ind["Close"], window=14,
    )
    resampled_with_ind["adx"] = adx_ind.adx()
    resampled_with_ind["di_plus"] = adx_ind.adx_pos()
    resampled_with_ind["di_minus"] = adx_ind.adx_neg()

    resampled_with_ind["bb_width"] = (
        (resampled_with_ind["bb_upper"] - resampled_with_ind["bb_lower"])
        / resampled_with_ind["bb_mid"]
    )

    cols_to_keep = [
        "rsi_14", "macd_hist", "bb_upper", "bb_lower", "bb_mid", "bb_pct_b",
        "bb_width", "ema_5", "ema_13", "ema_26", "ema_50",
        "trend_score", "stoch_k", "stoch_d", "adx", "di_plus", "di_minus",
        "Close",
    ]
    cols_available = [c for c in cols_to_keep if c in resampled_with_ind.columns]
    tf_data = resampled_with_ind[cols_available]

    prefixed = tf_data.rename(columns={c: f"{prefix}{c}" for c in cols_available})
    return prefixed.reindex(df_daily.index, method="ffill")


# ── Main entry point ─────────────────────────────────────────────────────────

def compute_asta_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all ASTA GEO PAN indicators on a daily OHLCV DataFrame.

    Expects standard RITA columns: Open, High, Low, Close, Volume.

    Pipeline:
        1. calculate_indicators() — base set (RSI, MACD, BB, ATR, EMAs)
        2. Stochastic, ADX/DI, BB width — daily (Ripple)
        3. Swing points, trend structure, Fibonacci
        4. Candlestick patterns
        5. Crossover flags, divergences
        6. DB/DT chart pattern detection
        7. Volume analysis
        8. Derived condition flags
        9. Multi-timeframe: Wave (weekly) and Tide (monthly) indicators
    """
    log.info("asta_indicators.compute", rows=len(df))

    # Step 1: base indicators from technical_analyzer
    out = calculate_indicators(df)

    # Step 2: Stochastic, ADX/DI, BB width (daily / Ripple)
    stoch = ta.momentum.StochasticOscillator(
        high=out["High"], low=out["Low"], close=out["Close"],
        window=14, smooth_window=3,
    )
    out["stoch_k"] = stoch.stoch()
    out["stoch_d"] = stoch.stoch_signal()

    adx_ind = ta.trend.ADXIndicator(
        high=out["High"], low=out["Low"], close=out["Close"], window=14,
    )
    out["adx"] = adx_ind.adx()
    out["di_plus"] = adx_ind.adx_pos()
    out["di_minus"] = adx_ind.adx_neg()

    out["bb_width"] = (out["bb_upper"] - out["bb_lower"]) / out["bb_mid"]

    # Step 3: Swing points, trend structure, Fibonacci
    out = _detect_swing_points(out)
    out = _trend_structure(out)
    out = _fibonacci_levels(out)

    # Step 4: Candlestick patterns
    out = _candlestick_patterns(out)

    # Step 5: Crossover flags and divergences
    out = _crossover_flags(out)
    out = _divergence_detection(out)

    # Step 6: DB/DT chart patterns
    out = _detect_db_dt(out)

    # Step 7: Volume analysis
    if "Volume" in out.columns and not out["Volume"].isna().all():
        out["vol_sma_20"] = out["Volume"].rolling(20).mean()
        out["vol_ratio"] = out["Volume"] / out["vol_sma_20"]
        out["volume_above_avg"] = out["vol_ratio"] > 1.2
    else:
        out["vol_sma_20"] = np.nan
        out["vol_ratio"] = np.nan
        out["volume_above_avg"] = False

    # Step 8: Derived condition flags
    out["bb_upper_challenge"] = out["High"] >= out["bb_upper"] * 0.995
    out["bb_lower_challenge"] = out["Low"] <= out["bb_lower"] * 1.005
    bb_width_min = out["bb_width"].rolling(20).min()
    out["bb_squeeze"] = out["bb_width"] < bb_width_min * 1.1
    out["bb_price_upper_half"] = out["Close"] > out["bb_mid"]
    out["price_above_50ema"] = out["Close"] > out["ema_50"]
    out["fib_below_618"] = out["fib_pct"].fillna(1.0) < 0.618
    out["adx_above_15"] = out["adx"] > 15

    # Step 9: Multi-timeframe indicators
    wave_cols = _compute_timeframe_indicators(df, "W", "wave_")
    tide_cols = _compute_timeframe_indicators(df, "ME", "tide_")
    out = pd.concat([out, wave_cols, tide_cols], axis=1)

    # Tide-level derived flags
    if "tide_bb_upper" in out.columns:
        out["tide_bb_upper_challenge"] = out["Close"] >= out["tide_bb_upper"] * 0.995
        out["tide_bb_lower_challenge"] = out["Close"] <= out["tide_bb_lower"] * 1.005
        if "tide_bb_width" in out.columns:
            tide_bw_min = out["tide_bb_width"].rolling(6).min()
            out["tide_bb_squeeze"] = out["tide_bb_width"] < tide_bw_min * 1.1
        out["tide_bb_price_upper_half"] = out["Close"] > out["tide_bb_mid"]
        out["tide_macd_hist_uptick"] = out["tide_macd_hist"] > out["tide_macd_hist"].shift(1)
        out["tide_macd_hist_downtick"] = out["tide_macd_hist"] < out["tide_macd_hist"].shift(1)

    # Wave-level derived flags
    if "wave_bb_upper" in out.columns:
        out["wave_bb_upper_challenge"] = out["Close"] >= out["wave_bb_upper"] * 0.995
        out["wave_bb_lower_challenge"] = out["Close"] <= out["wave_bb_lower"] * 1.005
        if "wave_bb_width" in out.columns:
            wave_bw_min = out["wave_bb_width"].rolling(10).min()
            out["wave_bb_squeeze"] = out["wave_bb_width"] < wave_bw_min * 1.1
        out["wave_bb_price_upper_half"] = out["Close"] > out["wave_bb_mid"]

    log.info("asta_indicators.done", total_columns=len(out.columns))
    return out
