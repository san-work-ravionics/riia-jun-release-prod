"""RITA Core — ASTA Signal Labeler (Feature 37)

Rule engine that evaluates four ASTA trading setups against a DataFrame
enriched by ``asta_indicators.compute_asta_indicators()``:

    1. SMM Double Screen — simplest; Tide direction + Wave oscillator + any
       single confirmation (candlestick / volume / EMA cross / chart pattern).
    2. GEO PAN Triple Screen — stricter multi-timeframe trend-following.
    3. GEO PAN Swing Trader — DB/DT reversal at BB extremes.
    4. GEO PAN Momentum BB — BB Challenge with trendline-break proxy.

Each setup produces a signal per candle: BUY, SELL, or HOLD, along with a
confidence score (0–1) based on how many mandatory + optional conditions are
satisfied.

Multi-timeframe mapping: Tide = Monthly (tide_*), Wave = Weekly (wave_*),
Ripple = Daily (no prefix).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import structlog

log = structlog.get_logger(__name__)


@dataclass
class SetupResult:
    signal: str           # BUY, SELL, HOLD
    setup: str            # triple_screen, swing_db_dt, momentum_bb
    confidence: float     # 0.0 – 1.0
    mandatory_met: int
    mandatory_total: int
    optional_met: int
    optional_total: int


# ── Helper: safe column check ────────────────────────────────────────────────

def _col(row: pd.Series, col_name: str, default=False):
    """Safely get a column value, returning default if missing or NaN."""
    val = row.get(col_name)
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return default
    return val


# ── Setup S: SMM Double Screen ────────────────────────────────────────────────

def _eval_smm_buy(row: pd.Series) -> SetupResult:
    """Evaluate SMM Double Screen Buy conditions.

    Mandatory (both must be true = "Bull Hat"):
        1. Tide: TI Uptick or Flat-after-Down (trend is up)
        2. Wave: Oscillator giving Buy signal (Stochastic PCO or RSI > 40)

    Confirmations (ANY one triggers entry):
        C1. Bullish candlestick (green candle, engulf, piercing, hammer, morning star)
        C2. Heavy volume on green candle
        C3. 5 EMA PCO with 13 or 26 EMA in last 3 periods
        C4. Bullish chart pattern (DB, Inv H&S, Rounding Bottom, Flag BO, Fake BD)

    Boosters:
        Fib retracement, divergence
    """
    mandatory = []

    # M1: Tide TI Uptick or Flat-after-Down
    tide_ti_uptick = _col(row, "tide_macd_hist_uptick")
    tide_uptrend = _col(row, "trend_hh_hl")
    mandatory.append(bool(tide_ti_uptick or tide_uptrend))

    # M2: Wave oscillator Buy signal — Stochastic PCO (K crosses above D)
    wave_stoch_pco = _col(row, "stoch_pco")
    wave_stoch_oversold_pco = _col(row, "stoch_oversold_pco")
    mandatory.append(bool(wave_stoch_pco or wave_stoch_oversold_pco))

    mandatory_met = sum(mandatory)

    # Confirmations — any one is enough
    confirmations = []

    # C1: Bullish candlestick pattern (not just green candle)
    cdl_bull = (
        _col(row, "cdl_bullish_engulf")
        or _col(row, "cdl_piercing")
        or _col(row, "cdl_hammer")
        or _col(row, "cdl_morning_star")
    )
    confirmations.append(bool(cdl_bull))

    # C2: Heavy volume on green candle
    green_candle = _col(row, "Close", 0) > _col(row, "Open", 0)
    vol_confirm = bool(green_candle and _col(row, "volume_above_avg"))
    confirmations.append(vol_confirm)

    # C3: EMA crossover (ignore if Morning/Evening Star or DB/DT)
    is_star = _col(row, "cdl_morning_star") or _col(row, "cdl_evening_star")
    is_db_dt = _col(row, "pattern_double_bottom") or _col(row, "pattern_double_top")
    ema_cross = bool(
        not is_star and not is_db_dt
        and (_col(row, "ema_5_cross_13_up") or _col(row, "ema_5_cross_26_up"))
    )
    confirmations.append(ema_cross)

    # C4: Bullish chart pattern
    chart_pattern = bool(_col(row, "pattern_double_bottom"))
    confirmations.append(chart_pattern)

    confirmations_met = sum(confirmations)
    has_confirmation = confirmations_met > 0

    # Boosters
    boosters = []
    boosters.append(bool(_col(row, "fib_below_618")))
    boosters.append(bool(_col(row, "rsi_bullish_div") or _col(row, "stoch_bullish_div")))
    boosters.append(bool(_col(row, "stoch_oversold_pco")))
    boosters_met = sum(boosters)

    # Signal: both mandatories + at least one confirmation
    signal = "BUY" if (mandatory_met == 2 and has_confirmation) else "HOLD"

    total_possible = len(mandatory) + len(confirmations) + len(boosters)
    score = mandatory_met + confirmations_met + boosters_met
    confidence = score / total_possible if total_possible > 0 else 0.0

    return SetupResult(
        signal=signal, setup="smm_double_screen",
        confidence=round(confidence, 3),
        mandatory_met=mandatory_met, mandatory_total=len(mandatory),
        optional_met=confirmations_met + boosters_met,
        optional_total=len(confirmations) + len(boosters),
    )


def _eval_smm_sell(row: pd.Series) -> SetupResult:
    """Evaluate SMM Double Screen Sell conditions (mirror of Buy)."""
    mandatory = []

    tide_ti_downtick = _col(row, "tide_macd_hist_downtick")
    tide_downtrend = _col(row, "trend_lh_ll")
    mandatory.append(bool(tide_ti_downtick or tide_downtrend))

    # M2: Wave oscillator Sell signal — Stochastic NCO (K crosses below D)
    wave_stoch_nco = _col(row, "stoch_nco")
    wave_stoch_overbought_nco = _col(row, "stoch_overbought_nco")
    mandatory.append(bool(wave_stoch_nco or wave_stoch_overbought_nco))

    mandatory_met = sum(mandatory)

    confirmations = []

    # C1: Bearish candlestick pattern (not just red candle)
    cdl_bear = (
        _col(row, "cdl_bearish_engulf")
        or _col(row, "cdl_dark_cloud")
        or _col(row, "cdl_shooting_star")
        or _col(row, "cdl_evening_star")
    )
    confirmations.append(bool(cdl_bear))

    # C2: Heavy volume on red candle
    red_candle = _col(row, "Close", 0) < _col(row, "Open", 0)
    vol_confirm = bool(red_candle and _col(row, "volume_above_avg"))
    confirmations.append(vol_confirm)

    is_star = _col(row, "cdl_morning_star") or _col(row, "cdl_evening_star")
    is_db_dt = _col(row, "pattern_double_bottom") or _col(row, "pattern_double_top")
    ema_cross = bool(
        not is_star and not is_db_dt
        and (_col(row, "ema_5_cross_13_down") or _col(row, "ema_5_cross_26_down"))
    )
    confirmations.append(ema_cross)

    chart_pattern = bool(_col(row, "pattern_double_top"))
    confirmations.append(chart_pattern)

    confirmations_met = sum(confirmations)
    has_confirmation = confirmations_met > 0

    boosters = []
    boosters.append(bool(_col(row, "fib_below_618")))
    boosters.append(bool(_col(row, "rsi_bearish_div") or _col(row, "stoch_bearish_div")))
    boosters.append(bool(_col(row, "stoch_overbought_nco")))
    boosters_met = sum(boosters)

    signal = "SELL" if (mandatory_met == 2 and has_confirmation) else "HOLD"

    total_possible = len(mandatory) + len(confirmations) + len(boosters)
    score = mandatory_met + confirmations_met + boosters_met
    confidence = score / total_possible if total_possible > 0 else 0.0

    return SetupResult(
        signal=signal, setup="smm_double_screen",
        confidence=round(confidence, 3),
        mandatory_met=mandatory_met, mandatory_total=len(mandatory),
        optional_met=confirmations_met + boosters_met,
        optional_total=len(confirmations) + len(boosters),
    )


# ── Setup A: Triple Screen ───────────────────────────────────────────────────

def _eval_triple_screen_buy(row: pd.Series) -> SetupResult:
    """Evaluate Triple Screen Buy conditions.

    Mandatory (Tide + Wave + Ripple):
        1. Tide: uptrend (HH+HL) OR TI uptick/flat-after-down
        2. Wave: retracement against uptrend (price pulling back in Tide trend)
        3. Wave: bullish chart pattern (DB with BKP, FBD of support)
        4. Ripple: bullish candlestick pattern
    """
    mandatory = []

    # M1: Tide in uptrend OR Tide MACD histogram uptick
    tide_uptrend = _col(row, "trend_hh_hl")
    tide_ti_uptick = _col(row, "tide_macd_hist_uptick")
    mandatory.append(bool(tide_uptrend or tide_ti_uptick))

    # M2: Wave showing retracement — price below wave EMA but Tide still up
    wave_rsi_below_50 = _col(row, "wave_rsi_14", 50) < 50
    fib_ok = _col(row, "fib_below_618")
    mandatory.append(bool(wave_rsi_below_50 or fib_ok))

    # M3: Bullish chart pattern on Wave/Daily
    db = _col(row, "pattern_double_bottom")
    mandatory.append(bool(db))

    # M4: Ripple bullish candlestick
    cdl_bull = (
        _col(row, "cdl_bullish_engulf")
        or _col(row, "cdl_piercing")
        or _col(row, "cdl_morning_star")
        or _col(row, "cdl_hammer")
    )
    mandatory.append(bool(cdl_bull))

    mandatory_met = sum(mandatory)

    # Optional boosters
    optional = []
    optional.append(bool(_col(row, "bb_lower_challenge")))
    optional.append(bool(
        _col(row, "ema_5_cross_13_up") or _col(row, "ema_5_cross_26_up")
    ))
    optional.append(bool(_col(row, "rsi_14", 0) > 40))
    optional.append(bool(_col(row, "rsi_cross_above_60")))
    optional.append(bool(_col(row, "stoch_pco")))
    optional.append(bool(_col(row, "stoch_oversold_pco")))
    optional.append(bool(_col(row, "fib_below_618")))
    optional.append(bool(_col(row, "volume_above_avg")))
    optional.append(bool(_col(row, "rsi_bullish_div") or _col(row, "stoch_bullish_div")))
    optional_met = sum(optional)

    signal = "BUY" if mandatory_met == len(mandatory) else "HOLD"
    total_possible = len(mandatory) + len(optional)
    confidence = (mandatory_met + optional_met) / total_possible if total_possible > 0 else 0.0

    return SetupResult(
        signal=signal, setup="triple_screen",
        confidence=round(confidence, 3),
        mandatory_met=mandatory_met, mandatory_total=len(mandatory),
        optional_met=optional_met, optional_total=len(optional),
    )


def _eval_triple_screen_sell(row: pd.Series) -> SetupResult:
    mandatory = []

    tide_downtrend = _col(row, "trend_lh_ll")
    tide_ti_downtick = _col(row, "tide_macd_hist_downtick")
    mandatory.append(bool(tide_downtrend or tide_ti_downtick))

    wave_rsi_above_50 = _col(row, "wave_rsi_14", 50) > 50
    fib_ok = _col(row, "fib_below_618")
    mandatory.append(bool(wave_rsi_above_50 or fib_ok))

    dt = _col(row, "pattern_double_top")
    mandatory.append(bool(dt))

    cdl_bear = (
        _col(row, "cdl_bearish_engulf")
        or _col(row, "cdl_dark_cloud")
        or _col(row, "cdl_evening_star")
        or _col(row, "cdl_shooting_star")
    )
    mandatory.append(bool(cdl_bear))

    mandatory_met = sum(mandatory)

    optional = []
    optional.append(bool(_col(row, "bb_upper_challenge")))
    optional.append(bool(
        _col(row, "ema_5_cross_13_down") or _col(row, "ema_5_cross_26_down")
    ))
    optional.append(bool(_col(row, "rsi_14", 100) < 60))
    optional.append(bool(_col(row, "rsi_cross_below_40")))
    optional.append(bool(_col(row, "stoch_nco")))
    optional.append(bool(_col(row, "stoch_overbought_nco")))
    optional.append(bool(_col(row, "fib_below_618")))
    optional.append(bool(_col(row, "volume_above_avg")))
    optional.append(bool(_col(row, "rsi_bearish_div") or _col(row, "stoch_bearish_div")))
    optional_met = sum(optional)

    signal = "SELL" if mandatory_met == len(mandatory) else "HOLD"
    total_possible = len(mandatory) + len(optional)
    confidence = (mandatory_met + optional_met) / total_possible if total_possible > 0 else 0.0

    return SetupResult(
        signal=signal, setup="triple_screen",
        confidence=round(confidence, 3),
        mandatory_met=mandatory_met, mandatory_total=len(mandatory),
        optional_met=optional_met, optional_total=len(optional),
    )


# ── Setup B: Swing Trader — Double Bottom/Top ────────────────────────────────

def _eval_swing_buy(row: pd.Series) -> SetupResult:
    """Evaluate Swing Trader Buy conditions (DB / Fake Breakdown).

    Mandatory:
        1. Tide: BBNC on downside (BB squeeze)
        2. Wave: DB or FBD chart pattern
        3. Wave: Bullish reversal candle
    """
    mandatory = []

    tide_squeeze = _col(row, "tide_bb_squeeze") if "tide_bb_squeeze" in row.index else False
    tide_lower_half = not _col(row, "tide_bb_price_upper_half", True)
    mandatory.append(bool(tide_squeeze or tide_lower_half))

    db = _col(row, "pattern_double_bottom")
    mandatory.append(bool(db))

    cdl_bull = (
        _col(row, "cdl_bullish_engulf")
        or _col(row, "cdl_piercing")
        or _col(row, "cdl_morning_star")
    )
    mandatory.append(bool(cdl_bull))

    mandatory_met = sum(mandatory)

    optional = []
    optional.append(bool(_col(row, "bb_lower_challenge")))
    optional.append(bool(_col(row, "volume_above_avg")))
    optional.append(bool(_col(row, "macd_hist_uptick")))
    optional.append(bool(_col(row, "rsi_14", 0) > 40))
    optional.append(bool(_col(row, "stoch_pco")))
    optional.append(bool(_col(row, "di_pco")))
    optional.append(bool(_col(row, "rsi_bullish_div") or _col(row, "stoch_bullish_div")))
    optional_met = sum(optional)

    signal = "BUY" if mandatory_met == len(mandatory) else "HOLD"
    total_possible = len(mandatory) + len(optional)
    confidence = (mandatory_met + optional_met) / total_possible if total_possible > 0 else 0.0

    return SetupResult(
        signal=signal, setup="swing_db_dt",
        confidence=round(confidence, 3),
        mandatory_met=mandatory_met, mandatory_total=len(mandatory),
        optional_met=optional_met, optional_total=len(optional),
    )


def _eval_swing_sell(row: pd.Series) -> SetupResult:
    mandatory = []

    tide_squeeze = _col(row, "tide_bb_squeeze") if "tide_bb_squeeze" in row.index else False
    tide_upper_half = _col(row, "tide_bb_price_upper_half", False)
    mandatory.append(bool(tide_squeeze or tide_upper_half))

    dt = _col(row, "pattern_double_top")
    mandatory.append(bool(dt))

    cdl_bear = (
        _col(row, "cdl_bearish_engulf")
        or _col(row, "cdl_dark_cloud")
        or _col(row, "cdl_evening_star")
    )
    mandatory.append(bool(cdl_bear))

    mandatory_met = sum(mandatory)

    optional = []
    optional.append(bool(_col(row, "bb_upper_challenge")))
    optional.append(bool(_col(row, "volume_above_avg")))
    optional.append(bool(_col(row, "macd_hist_downtick")))
    optional.append(bool(_col(row, "rsi_14", 100) < 60))
    optional.append(bool(_col(row, "stoch_nco")))
    optional.append(bool(_col(row, "di_nco")))
    optional.append(bool(_col(row, "rsi_bearish_div") or _col(row, "stoch_bearish_div")))
    optional_met = sum(optional)

    signal = "SELL" if mandatory_met == len(mandatory) else "HOLD"
    total_possible = len(mandatory) + len(optional)
    confidence = (mandatory_met + optional_met) / total_possible if total_possible > 0 else 0.0

    return SetupResult(
        signal=signal, setup="swing_db_dt",
        confidence=round(confidence, 3),
        mandatory_met=mandatory_met, mandatory_total=len(mandatory),
        optional_met=optional_met, optional_total=len(optional),
    )


# ── Setup C: Momentum — BB Challenge with Trendline Break ────────────────────

def _eval_momentum_buy(row: pd.Series) -> SetupResult:
    """Evaluate Momentum Buy conditions (BB Challenge + Trendline Break).

    Mandatory:
        1. Tide: BBUC or Price in upper half of BB
        2. Tide: TI Uptick (MACD hist uptick)
        3. Tide & Wave: RSI > 50
        4. Wave: BBUC (BB upper challenge on wave timeframe)
    """
    mandatory = []

    tide_bbuc = _col(row, "tide_bb_upper_challenge", False)
    tide_upper = _col(row, "tide_bb_price_upper_half", False)
    mandatory.append(bool(tide_bbuc or tide_upper))

    tide_ti_up = _col(row, "tide_macd_hist_uptick", False)
    mandatory.append(bool(tide_ti_up))

    tide_rsi = _col(row, "tide_rsi_14", 0)
    wave_rsi = _col(row, "wave_rsi_14", 0)
    mandatory.append(bool(tide_rsi > 50 and wave_rsi > 50))

    wave_bbuc = _col(row, "wave_bb_upper_challenge", False)
    mandatory.append(bool(wave_bbuc))

    mandatory_met = sum(mandatory)

    optional = []
    optional.append(bool(_col(row, "volume_above_avg")))
    optional.append(bool(
        _col(row, "ema_5_cross_13_up") or _col(row, "ema_5_cross_26_up")
    ))
    optional.append(bool(_col(row, "di_pco")))
    optional.append(bool(_col(row, "adx_above_15")))
    optional.append(bool(_col(row, "price_above_50ema")))
    optional.append(bool(_col(row, "rsi_cross_above_60")))
    optional_met = sum(optional)

    signal = "BUY" if mandatory_met == len(mandatory) else "HOLD"
    total_possible = len(mandatory) + len(optional)
    confidence = (mandatory_met + optional_met) / total_possible if total_possible > 0 else 0.0

    return SetupResult(
        signal=signal, setup="momentum_bb",
        confidence=round(confidence, 3),
        mandatory_met=mandatory_met, mandatory_total=len(mandatory),
        optional_met=optional_met, optional_total=len(optional),
    )


def _eval_momentum_sell(row: pd.Series) -> SetupResult:
    mandatory = []

    tide_bbdc = _col(row, "tide_bb_lower_challenge", False)
    tide_lower = not _col(row, "tide_bb_price_upper_half", True)
    mandatory.append(bool(tide_bbdc or tide_lower))

    tide_ti_down = _col(row, "tide_macd_hist_downtick", False)
    mandatory.append(bool(tide_ti_down))

    tide_rsi = _col(row, "tide_rsi_14", 100)
    wave_rsi = _col(row, "wave_rsi_14", 100)
    mandatory.append(bool(tide_rsi < 50 and wave_rsi < 50))

    wave_bbdc = _col(row, "wave_bb_lower_challenge", False)
    mandatory.append(bool(wave_bbdc))

    mandatory_met = sum(mandatory)

    optional = []
    optional.append(bool(_col(row, "volume_above_avg")))
    optional.append(bool(
        _col(row, "ema_5_cross_13_down") or _col(row, "ema_5_cross_26_down")
    ))
    optional.append(bool(_col(row, "di_nco")))
    optional.append(bool(_col(row, "adx_above_15")))
    optional.append(bool(not _col(row, "price_above_50ema", True)))
    optional.append(bool(_col(row, "rsi_cross_below_40")))
    optional_met = sum(optional)

    signal = "SELL" if mandatory_met == len(mandatory) else "HOLD"
    total_possible = len(mandatory) + len(optional)
    confidence = (mandatory_met + optional_met) / total_possible if total_possible > 0 else 0.0

    return SetupResult(
        signal=signal, setup="momentum_bb",
        confidence=round(confidence, 3),
        mandatory_met=mandatory_met, mandatory_total=len(mandatory),
        optional_met=optional_met, optional_total=len(optional),
    )


# ── Stop-loss and target computation ─────────────────────────────────────────

def _compute_stop_loss(row: pd.Series, signal: str, setup: str) -> float:
    """Compute stop-loss price based on setup type and signal direction."""
    atr = _col(row, "atr_14", 0.0)
    close = _col(row, "Close", 0.0)

    if signal == "BUY":
        sl_low = _col(row, "swing_low", close)
        if np.isnan(sl_low):
            sl_low = _col(row, "Low", close)
        return float(min(sl_low, close - 1.5 * atr))
    elif signal == "SELL":
        sl_high = _col(row, "swing_high", close)
        if np.isnan(sl_high):
            sl_high = _col(row, "High", close)
        return float(max(sl_high, close + 1.5 * atr))
    return 0.0


def _compute_target(row: pd.Series, signal: str) -> float:
    """Compute target price using Fibonacci levels and support/resistance."""
    close = _col(row, "Close", 0.0)
    atr = _col(row, "atr_14", 0.0)

    fib_618 = _col(row, "fib_618", np.nan)
    fib_382 = _col(row, "fib_382", np.nan)

    if signal == "BUY":
        if not np.isnan(fib_382):
            return float(max(fib_382, close + 2.0 * atr))
        return float(close + 2.5 * atr)
    elif signal == "SELL":
        if not np.isnan(fib_618):
            return float(min(fib_618, close - 2.0 * atr))
        return float(close - 2.5 * atr)
    return 0.0


# ── Main labeling function ───────────────────────────────────────────────────

def label_asta_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all four ASTA setups (SMM + 3 GEO PAN) to a DataFrame enriched by
    ``compute_asta_indicators()``.

    For each row, evaluates all 6 sub-setups (3 buy + 3 sell) and picks the
    one with the highest confidence score. If no setup has all mandatory
    conditions met, the row is labeled HOLD.

    Returns the input DataFrame with added columns:
        asta_signal       — BUY / SELL / HOLD
        asta_setup        — triple_screen / swing_db_dt / momentum_bb / none
        asta_confidence   — 0.0 to 1.0
        asta_mandatory_met — count of mandatory conditions met (best setup)
        asta_mandatory_total — total mandatory conditions (best setup)
        asta_optional_met — count of optional conditions met (best setup)
        asta_optional_total — total optional conditions (best setup)
        asta_stop_loss    — stop-loss price
        asta_target       — target price
    """
    log.info("asta_labeler.label", rows=len(df))

    signals = []
    setups = []
    confidences = []
    mand_met_list = []
    mand_total_list = []
    opt_met_list = []
    opt_total_list = []
    stop_losses = []
    targets = []

    evaluators = [
        _eval_smm_buy, _eval_smm_sell,
        _eval_triple_screen_buy, _eval_triple_screen_sell,
        _eval_swing_buy, _eval_swing_sell,
        _eval_momentum_buy, _eval_momentum_sell,
    ]

    for i in range(len(df)):
        row = df.iloc[i]
        best: SetupResult | None = None

        for evaluator in evaluators:
            result = evaluator(row)
            if result.signal == "HOLD":
                continue
            if best is None or result.confidence > best.confidence:
                best = result

        if best is not None and best.signal != "HOLD":
            signals.append(best.signal)
            setups.append(best.setup)
            confidences.append(best.confidence)
            mand_met_list.append(best.mandatory_met)
            mand_total_list.append(best.mandatory_total)
            opt_met_list.append(best.optional_met)
            opt_total_list.append(best.optional_total)
            stop_losses.append(_compute_stop_loss(row, best.signal, best.setup))
            targets.append(_compute_target(row, best.signal))
        else:
            signals.append("HOLD")
            setups.append("none")
            confidences.append(0.0)
            mand_met_list.append(0)
            mand_total_list.append(0)
            opt_met_list.append(0)
            opt_total_list.append(0)
            stop_losses.append(0.0)
            targets.append(0.0)

    out = df.copy()
    out["asta_signal"] = signals
    out["asta_setup"] = setups
    out["asta_confidence"] = confidences
    out["asta_mandatory_met"] = mand_met_list
    out["asta_mandatory_total"] = mand_total_list
    out["asta_optional_met"] = opt_met_list
    out["asta_optional_total"] = opt_total_list
    out["asta_stop_loss"] = stop_losses
    out["asta_target"] = targets

    buy_count = sum(1 for s in signals if s == "BUY")
    sell_count = sum(1 for s in signals if s == "SELL")
    hold_count = sum(1 for s in signals if s == "HOLD")
    total = len(signals)
    log.info(
        "asta_labeler.done",
        buy=buy_count, sell=sell_count, hold=hold_count,
        buy_pct=round(buy_count / total * 100, 1) if total else 0,
        sell_pct=round(sell_count / total * 100, 1) if total else 0,
    )

    return out
