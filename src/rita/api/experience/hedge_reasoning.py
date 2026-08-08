"""Experience Layer — Hedge Reasoning endpoint (Feature 31 Phase 1).

ADR-001 Tier 3: read-only composition, no writes, no side effects.
Returns a 7-step deterministic reasoning chain for hedge recommendations.

GET /api/v1/experience/fno/hedge-reasoning?instrument=ASML&n_shares=10
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from fastapi import APIRouter, HTTPException, Query

from rita.config import get_settings
from rita.core.investment_horizons import INVESTMENT_HORIZONS
from rita.schemas.hedge_reasoning import HedgeReasoningResponse, ReasoningStep

log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/experience/fno",
    tags=["experience:hedge-reasoning"],
)

# ── Market data cache — keyed by instrument id ────────────────────────────────
_market_cache: dict[str, dict[str, Any]] = {}


def _get_df(instrument: str):
    """Load and cache the indicators DataFrame for the given instrument.

    Mirrors the caching pattern from chat.py: find_instrument_csv +
    load_ohlcv_csv + calculate_indicators, keyed on file mtime.
    """
    import pandas as pd
    from rita.core.data_loader import load_ohlcv_csv
    from rita.core.data_understanding import find_instrument_csv
    from rita.core.technical_analyzer import calculate_indicators

    inst = instrument.upper()
    settings = get_settings()

    primary_path = str(find_instrument_csv(inst))
    manual_path = Path(settings.data.input_dir) / "DAILY-DATA" / f"{inst.lower()}_manual.csv"

    mtime_primary = os.path.getmtime(primary_path)
    mtime_manual = os.path.getmtime(str(manual_path)) if manual_path.exists() else 0.0
    mtime_key = (mtime_primary, mtime_manual)

    cached = _market_cache.get(inst)
    if cached is not None and cached["mtime_key"] == mtime_key:
        return cached["df"]

    raw = load_ohlcv_csv(primary_path)
    if manual_path.exists():
        manual = load_ohlcv_csv(str(manual_path))
        raw = pd.concat([raw, manual])
        raw = raw[~raw.index.duplicated(keep="last")].sort_index()

    df = calculate_indicators(raw)
    _market_cache[inst] = {"df": df, "mtime_key": mtime_key}
    log.info(
        "hedge_reasoning.csv_reloaded",
        instrument=inst,
        primary=primary_path,
        rows=len(df),
    )
    return df


# ── Black-Scholes helpers (imported from portfolio_hedge.py) ──────────────────
def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2))) / 2.0


def _bs_call_pct(
    vol_annual_pct: float,
    strike_pct: float,
    r: float = 0.065,
    t_months: float = 12.0,
) -> float:
    """OTM call premium as % of spot (Black-Scholes).

    strike_pct positive = OTM call: +7.5 -> K = spot * 1.075.
    """
    S = 1.0
    K = max(0.01, 1.0 + strike_pct / 100.0)
    T = t_months / 12.0
    sigma = max(0.001, vol_annual_pct / 100.0)
    try:
        d1 = (math.log(S / K) + (r + sigma**2 / 2.0) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        call = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
        return round(max(0.0, call * 100), 3)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _bs_put_pct(
    vol_annual_pct: float,
    strike_pct: float,
    r: float = 0.065,
    t_months: float = 12.0,
) -> float:
    """Put premium as % of spot (Black-Scholes).

    strike_pct negative = OTM put: -7.5 -> K = spot * 0.925.
    """
    S = 1.0
    K = max(0.01, 1.0 + strike_pct / 100.0)
    T = t_months / 12.0
    sigma = max(0.001, vol_annual_pct / 100.0)
    try:
        d1 = (math.log(S / K) + (r + sigma**2 / 2.0) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        put = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
        return round(max(0.0, put * 100), 3)
    except (ValueError, ZeroDivisionError):
        return 0.0


# ── Step builder functions ────────────────────────────────────────────────────


def _build_step_regime(df) -> dict:
    """Step 1 — REGIME ANALYST: detect market regime from EMA ratio."""
    from rita.core.technical_analyzer import detect_regime

    regime_data = detect_regime(df)
    regime = regime_data["regime"]
    ema_ratio = regime_data["ema_ratio"]
    bear_days = regime_data["consecutive_bear_days"]

    threshold_note = "above" if ema_ratio >= 0.99 else "below"
    strategy_hint = (
        "premium-selling strategies (covered call)"
        if regime == "BULL"
        else "premium-buying strategies (protective put)"
    )

    narrative = (
        f"Analysing EMA-26/EMA-50 ratio... "
        f"Current ratio is {ema_ratio:.5f}, {threshold_note} the 0.99 threshold "
        f"with {bear_days} consecutive bear days. "
        f"Market regime: {regime}. "
        f"This favours {strategy_hint}."
    )

    return {
        "agent": "REGIME_ANALYST",
        "title": "Market Regime Analysis",
        "narrative": narrative,
        "data": {
            "ema_ratio": ema_ratio,
            "consecutive_bear_days": bear_days,
            "regime": regime,
            "model": regime_data["model"],
        },
        "verdict": regime,
    }


def _build_step_technicals(df) -> dict:
    """Step 2 — TECHNICAL ANALYST: read current technical indicators."""
    from rita.core.technical_analyzer import get_market_summary

    summary = get_market_summary(df)

    rsi = summary["rsi_14"]
    rsi_state = summary["rsi_signal"]
    macd_val = summary["macd"]
    macd_state = summary["macd_signal"]
    bb_pct = summary["bb_pct_b"]
    bb_state = summary["bb_position"]
    trend = summary["trend_score"]
    trend_state = summary["trend"]
    atr = summary["atr_14"]
    close = summary["close"]
    atr_pct = round(atr / close * 100, 2) if close else 0.0
    atr_state = summary["sentiment_proxy"]

    # Count bullish signals (aligned with sentiment scorer definitions)
    signals = [rsi_state, macd_state, bb_state, trend_state, atr_state]
    bullish_count = sum(
        1
        for s in signals
        if s in ("bullish", "uptrend", "oversold", "near_lower_band", "complacent")
    )

    narrative = (
        f"Reading current indicators... "
        f"RSI-14: {rsi:.1f} ({rsi_state}). "
        f"MACD: {macd_val:+.4f} ({macd_state}). "
        f"Bollinger %B: {bb_pct:.3f} ({bb_state.replace('_', ' ')}). "
        f"Trend Score: {trend:+.3f} ({trend_state}). "
        f"ATR: {atr_pct:.1f}% of price ({atr_state})."
    )

    return {
        "agent": "TECHNICAL_ANALYST",
        "title": "Technical Indicator Reading",
        "narrative": narrative,
        "data": {
            "rsi": rsi,
            "rsi_state": rsi_state,
            "macd": macd_val,
            "macd_state": macd_state,
            "bollinger_pct_b": bb_pct,
            "bollinger_state": bb_state,
            "trend_score": trend,
            "trend_state": trend_state,
            "atr_pct": atr_pct,
            "atr_state": atr_state,
        },
        "verdict": f"{bullish_count}/5 bullish",
    }


def _build_step_sentiment(summary: dict) -> dict:
    """Step 3 — SENTIMENT SCORER: weight 5 signals into a total score."""
    from rita.core.technical_analyzer import get_sentiment_score

    scored = get_sentiment_score(summary)
    signals = scored["signals"]
    total = scored["total_score"]
    max_score = scored["max_score"]
    overall = scored["overall_sentiment"]

    # Build signal breakdown narrative
    signal_parts = []
    weight_map = {"trend": 2, "macd": 1, "rsi": 1, "bollinger": 1, "volatility": 1}
    for name, weight in weight_map.items():
        sig = signals[name]
        score = sig["score"]
        if name == "trend":
            score_display = score  # already weighted by 2 in the function
        else:
            score_display = score
        signal_parts.append(f"{name.capitalize()}: {sig['value']} ({score_display:+d})")

    narrative = (
        f"Weighing 5 technical signals... "
        f"{'. '.join(signal_parts)}. "
        f"Total: {total:+d}/{max_score} -> {overall} sentiment."
    )

    return {
        "agent": "SENTIMENT_SCORER",
        "title": "Sentiment Score Calculation",
        "narrative": narrative,
        "data": {
            "signals": {
                k: {"value": v["value"], "score": v["score"], "weight": weight_map[k]}
                for k, v in signals.items()
            },
            "total_score": total,
            "max_score": max_score,
            "overall_sentiment": overall,
        },
        "verdict": f"{total:+d}/{max_score} {overall}",
    }


def _build_step_allocation(summary: dict, scored: dict) -> dict:
    """Step 4 — ALLOCATION ENGINE: map sentiment to allocation with overrides."""
    from rita.core.strategy_engine import get_allocation_recommendation

    alloc = get_allocation_recommendation(summary, scored)
    rec = alloc["recommendation"]
    alloc_pct = alloc["allocation_pct"]
    rationale = alloc["rationale"]
    override_applied = alloc["override_applied"]
    override_reason = alloc["override_reason"]

    # Build override rule status list
    override_rules = [
        {
            "rule": "Fearful volatility + FULL",
            "status": "triggered" if (override_applied and "fearful" in (override_reason or "").lower()) else "pass",
        },
        {
            "rule": "Downtrend + FULL",
            "status": "triggered" if (override_applied and "downtrend" in (override_reason or "").lower() and "fearful" not in (override_reason or "").lower()) else "pass",
        },
        {
            "rule": "Downtrend + fearful",
            "status": "triggered" if (override_applied and "downtrend" in (override_reason or "").lower() and "fearful" in (override_reason or "").lower()) else "pass",
        },
        {
            "rule": "Overbought RSI + upper Bollinger",
            "status": "triggered" if (override_applied and "overbought" in (override_reason or "").lower()) else "pass",
        },
    ]

    override_note = ""
    if override_applied:
        override_note = f" Override applied: {override_reason}."
    else:
        override_note = " No overrides triggered."

    position_note = (
        " You are fully invested — you have a position to hedge."
        if rec in ("FULL", "HALF")
        else " No position to hedge — allocation is zero."
    )

    narrative = (
        f"Sentiment score {scored['total_score']:+d} -> {rec} allocation ({alloc_pct}% invested). "
        f"Checking override rules...{override_note}{position_note}"
    )

    return {
        "agent": "ALLOCATION_ENGINE",
        "title": "Allocation Recommendation",
        "narrative": narrative,
        "data": {
            "recommendation": rec,
            "allocation_pct": alloc_pct,
            "rationale": rationale,
            "override_rules": override_rules,
            "override_applied": override_applied,
        },
        "verdict": f"{rec} ({alloc_pct}%)",
    }


def _build_step_volatility(df, ann_vol_override: float | None = None) -> dict:
    """Step 5 — VOLATILITY ASSESSOR: realised vol + premium assessment."""
    closes = df["Close"].dropna()

    # 253-day annualised vol
    if len(closes) >= 253:
        daily_rets_253 = np.log(closes.iloc[-253:] / closes.iloc[-253:].shift(1)).dropna()
        ann_vol_253 = float(daily_rets_253.std() * math.sqrt(252) * 100)
    else:
        daily_rets_all = np.log(closes / closes.shift(1)).dropna()
        ann_vol_253 = float(daily_rets_all.std() * math.sqrt(252) * 100) if len(daily_rets_all) > 1 else 25.0

    # 30-day annualised vol
    if len(closes) >= 30:
        daily_rets_30 = np.log(closes.iloc[-30:] / closes.iloc[-30:].shift(1)).dropna()
        ann_vol_30 = float(daily_rets_30.std() * math.sqrt(252) * 100)
    else:
        ann_vol_30 = ann_vol_253

    # Apply override if provided
    if ann_vol_override is not None and ann_vol_override > 0:
        ann_vol_253 = ann_vol_override
        ann_vol_30 = ann_vol_override

    # Floor: clamp to 0.1% minimum
    ann_vol_253 = max(0.1, ann_vol_253)
    ann_vol_30 = max(0.1, ann_vol_30)

    # Handle NaN
    if not math.isfinite(ann_vol_253):
        ann_vol_253 = 25.0
    if not math.isfinite(ann_vol_30):
        ann_vol_30 = 25.0

    ann_vol_253 = round(ann_vol_253, 2)
    ann_vol_30 = round(ann_vol_30, 2)

    # Vol regime classification
    if ann_vol_253 < 20:
        vol_regime = "low"
        premium_assessment = "cheap"
    elif ann_vol_253 <= 35:
        vol_regime = "normal"
        premium_assessment = "fair"
    else:
        vol_regime = "elevated"
        premium_assessment = "rich"

    # 1-year return
    return_1y: float | None = None
    if len(closes) >= 253:
        close_now = float(closes.iloc[-1])
        close_1y = float(closes.iloc[-253])
        if close_1y > 0:
            return_1y = round((close_now / close_1y - 1) * 100, 2)

    vol_note = {
        "low": "When vol is low, option premiums are cheap — this favours buying premium (protective put) for inexpensive insurance.",
        "normal": "Vol is in the normal range — option premiums are fairly priced. Strategy choice depends on regime and allocation.",
        "elevated": "When vol is elevated, option premiums are rich — this favours selling premium (covered call) to collect income.",
    }

    narrative = (
        f"Measuring volatility profile... "
        f"253-day realised vol: {ann_vol_253:.1f}%. "
        f"30-day realised vol: {ann_vol_30:.1f}%. "
        f"Vol regime: {vol_regime.upper()}. "
        f"{vol_note[vol_regime]}"
    )
    if return_1y is not None:
        narrative += f" 1-year return: {return_1y:+.1f}%."

    return {
        "agent": "VOLATILITY_ASSESSOR",
        "title": "Volatility & Premium Assessment",
        "narrative": narrative,
        "data": {
            "ann_vol_253d": ann_vol_253,
            "ann_vol_30d": ann_vol_30,
            "vol_regime": vol_regime,
            "premium_assessment": premium_assessment,
            "return_1y_pct": return_1y,
        },
        "verdict": f"{vol_regime.capitalize()} — premiums {premium_assessment}",
    }


def _build_step_goal_analyst(df) -> dict:
    """Step 6 — GOAL ANALYST: classify horizon fit from price data and compute hedge trigger."""
    closes = df["Close"].dropna()

    short_cfg = INVESTMENT_HORIZONS["short_term"]
    medium_cfg = INVESTMENT_HORIZONS["medium_term"]
    long_cfg = INVESTMENT_HORIZONS["long_term"]

    short_annual = short_cfg["min_return_pct"]
    medium_annual = medium_cfg["min_return_pct"]
    long_annual = long_cfg["min_return_pct"]

    short_monthly = short_annual / 12.0
    medium_monthly = ((1 + medium_annual / 100) ** (1 / 12) - 1) * 100
    long_monthly = ((1 + long_annual / 100) ** (1 / 12) - 1) * 100

    monthly_returns = closes.resample("ME").last().pct_change().dropna() * 100
    months_above = float((monthly_returns >= short_monthly).sum() / len(monthly_returns) * 100) if len(monthly_returns) > 0 else 0.0

    cagr_5y: float | None = None
    if len(closes) >= medium_cfg["lookback_td"]:
        start_5y = float(closes.iloc[-medium_cfg["lookback_td"]])
        end_5y = float(closes.iloc[-1])
        if start_5y > 0:
            cagr_5y = round(((end_5y / start_5y) ** (1 / medium_cfg["years"]) - 1) * 100, 2)

    if months_above >= 40:
        horizon_fit = "short_term"
        horizon_label = short_cfg["label"]
        annual_target = short_annual
        monthly_target = round(short_monthly, 2)
    elif cagr_5y is not None and cagr_5y >= medium_annual:
        horizon_fit = "medium_term"
        horizon_label = medium_cfg["label"]
        annual_target = medium_annual
        monthly_target = round(medium_monthly, 2)
    else:
        horizon_fit = "long_term"
        horizon_label = long_cfg["label"]
        annual_target = long_annual
        monthly_target = round(long_monthly, 2)

    trading_days_1m = 21
    if len(closes) >= trading_days_1m + 1:
        close_now = float(closes.iloc[-1])
        close_1m_ago = float(closes.iloc[-trading_days_1m])
        actual_monthly_return = round((close_now / close_1m_ago - 1) * 100, 2) if close_1m_ago > 0 else 0.0
    else:
        actual_monthly_return = 0.0

    excess = round(actual_monthly_return - monthly_target, 2)

    if actual_monthly_return >= monthly_target:
        hedge_trigger = "triggered"
        hedge_budget = round(max(0, excess), 2)
    else:
        hedge_trigger = "not_triggered"
        hedge_budget = 0.0

    pct_note = f"{months_above:.0f}% of months delivered >={short_monthly:.2f}%"
    if hedge_trigger == "triggered":
        trigger_note = (
            f"Hedge trigger: ACTIVE — lock in gains with hedge budget of {hedge_budget:.2f}%."
        )
    else:
        trigger_note = (
            "Hedge trigger: INACTIVE — target not yet met."
        )

    narrative = (
        f"Classifying from historical returns... "
        f"{pct_note} — {horizon_fit.replace('_', ' ')} fit "
        f"(target: {annual_target:.0f}%/yr -> {monthly_target:.2f}%/mo). "
        f"Last month return: {actual_monthly_return:+.2f}%. "
        f"Target: {monthly_target:.2f}%. Excess: {excess:+.2f}%. "
        f"{trigger_note}"
    )

    trigger_label = "TRIGGERED" if hedge_trigger == "triggered" else "NOT TRIGGERED"
    excess_str = f" {excess:+.2f}%" if hedge_trigger == "triggered" else ""
    verdict = f"{horizon_label} — {trigger_label}{excess_str}"

    return {
        "agent": "GOAL_ANALYST",
        "title": "Goal-Relative Return Analysis",
        "narrative": narrative,
        "data": {
            "horizon_fit": horizon_fit,
            "horizon_label": horizon_label,
            "annual_target_pct": annual_target,
            "monthly_target_pct": monthly_target,
            "months_above_target_pct": round(months_above, 1),
            "cagr_5y_pct": cagr_5y,
            "actual_monthly_return_pct": actual_monthly_return,
            "excess_pct": excess,
            "hedge_trigger": hedge_trigger,
            "hedge_budget_pct": hedge_budget,
        },
        "verdict": verdict,
    }


def _build_step_hedge(
    regime: str,
    allocation: str,
    vol_data: dict,
    spot: float,
    n_shares: int,
    goal_data: dict | None = None,
) -> dict:
    """Step 7 — HEDGE ADVISOR: decision matrix + BS pricing."""
    ann_vol = vol_data["ann_vol_253d"]
    vol_regime = vol_data["vol_regime"]

    goal_triggered = goal_data is not None and goal_data.get("hedge_trigger") == "triggered"

    if allocation == "HOLD":
        primary = "no_hedge"
        primary_rationale = "No position to protect — allocation is HOLD (0% invested)."
        secondary = None
        secondary_rationale = None
    elif goal_triggered:
        primary = "put_buy"
        monthly_target = goal_data["monthly_target_pct"]
        primary_rationale = (
            f"Goal target achieved (excess {goal_data['excess_pct']:+.2f}%). "
            f"Recommending protective put costing <= hedge budget to lock in "
            f"net return of {monthly_target:.2f}%."
        )
        secondary = None
        secondary_rationale = None
    elif regime == "BULL":
        primary = "call_sell"
        primary_rationale = (
            f"Collect {'rich' if vol_regime == 'elevated' else 'moderate'} premium "
            f"in bull market; cap upside at 1 sigma OTM."
        )
        secondary = "put_buy"
        secondary_rationale = "Tail-risk insurance if conviction in upside weakens."
    else:  # BEAR
        primary = "put_buy"
        primary_rationale = (
            f"Protect downside in bear market; "
            f"{'vol makes puts expensive but necessary' if vol_regime == 'elevated' else 'cheaper protection while downside is likely'}."
        )
        secondary = "call_sell"
        secondary_rationale = "Generate income from covered calls to offset put cost."

    # Strike at 1 sigma OTM (approx 7.5% for typical vol)
    sigma_pct = min(ann_vol / math.sqrt(12), 15.0)  # 1-month 1-sigma as % of spot
    strike_pct = round(sigma_pct, 2)

    # BS pricing
    if allocation == "HOLD":
        call_sell_data = {
            "strike_label": "n/a",
            "strike_pct": 0.0,
            "premium_pct": 0.0,
            "premium_eur": 0.0,
            "max_value_eur": 0.0,
            "breakeven": 0.0,
        }
        put_buy_data = {
            "strike_label": "n/a",
            "strike_pct": 0.0,
            "premium_pct": 0.0,
            "premium_eur": 0.0,
            "floor_value_eur": 0.0,
            "breakeven": 0.0,
        }
    else:
        call_prem_pct = _bs_call_pct(ann_vol, strike_pct)
        put_prem_pct = _bs_put_pct(ann_vol, -strike_pct)
        position_value = spot * n_shares

        call_prem_eur = round(position_value * call_prem_pct / 100, 2)
        put_prem_eur = round(position_value * put_prem_pct / 100, 2)

        call_strike_price = round(spot * (1 + strike_pct / 100), 2)
        put_strike_price = round(spot * (1 - strike_pct / 100), 2)

        call_sell_data = {
            "strike_label": f"+{strike_pct:.1f}% OTM",
            "strike_pct": strike_pct,
            "premium_pct": call_prem_pct,
            "premium_eur": call_prem_eur,
            "max_value_eur": round(call_strike_price * n_shares + call_prem_eur, 2),
            "breakeven": round(spot - call_prem_eur / n_shares, 2) if n_shares > 0 else spot,
        }
        put_buy_data = {
            "strike_label": f"-{strike_pct:.1f}% OTM",
            "strike_pct": -strike_pct,
            "premium_pct": put_prem_pct,
            "premium_eur": round(-put_prem_eur, 2),
            "floor_value_eur": round(put_strike_price * n_shares - put_prem_eur, 2),
            "breakeven": round(spot + put_prem_eur / n_shares, 2) if n_shares > 0 else spot,
        }

    goal_not_triggered = goal_data is not None and goal_data.get("hedge_trigger") == "not_triggered"

    if allocation == "HOLD":
        narrative = (
            "Allocation is HOLD (0% invested) — no position to hedge. "
            "No hedge recommendation generated."
        )
    elif goal_triggered:
        monthly_target = goal_data["monthly_target_pct"]
        rec_label = "PUT BUY (protective put)"
        narrative = (
            f"Goal target achieved (excess {goal_data['excess_pct']:+.2f}%). "
            f"Recommending protective put costing <= hedge budget to lock in "
            f"net return of {monthly_target:.2f}%. "
            f"Buy 1 sigma OTM puts at -{strike_pct:.1f}% strike. "
            f"Cost {put_buy_data['premium_pct']:.1f}% premium "
            f"(EUR {abs(put_buy_data['premium_eur']):,.2f} on position). "
            f"Floor at EUR {put_buy_data['floor_value_eur']:,.2f}. "
            f"Breakeven: EUR {put_buy_data['breakeven']:,.2f}."
        )
    else:
        rec_label = "CALL SELL (covered call)" if primary == "call_sell" else "PUT BUY (protective put)"
        narrative = (
            f"Given {regime} regime + {allocation} allocation + {vol_regime} volatility "
            f"-> Primary recommendation: {rec_label}. "
        )
        if goal_not_triggered:
            narrative += (
                f"Monthly target not yet met "
                f"(actual {goal_data['actual_monthly_return_pct']:.2f}% "
                f"vs target {goal_data['monthly_target_pct']:.2f}%). "
                f"No goal-based hedge trigger — falling back to regime analysis. "
            )
        if primary == "call_sell":
            narrative += (
                f"Sell 1 sigma OTM calls at +{strike_pct:.1f}% strike. "
                f"Collect {call_sell_data['premium_pct']:.1f}% premium "
                f"(EUR {call_sell_data['premium_eur']:,.2f} on position). "
                f"Cap upside at EUR {call_sell_data['max_value_eur']:,.2f}. "
                f"Breakeven: EUR {call_sell_data['breakeven']:,.2f}. "
            )
        else:
            narrative += (
                f"Buy 1 sigma OTM puts at -{strike_pct:.1f}% strike. "
                f"Cost {put_buy_data['premium_pct']:.1f}% premium "
                f"(EUR {abs(put_buy_data['premium_eur']):,.2f} on position). "
                f"Floor at EUR {put_buy_data['floor_value_eur']:,.2f}. "
                f"Breakeven: EUR {put_buy_data['breakeven']:,.2f}. "
            )
        if secondary:
            narrative += f"Secondary: {secondary.upper().replace('_', ' ')} for "
            narrative += (
                "tail-risk insurance."
                if secondary == "put_buy"
                else "income generation to offset put cost."
            )

    verdict = primary.upper().replace("_", " ") if primary != "no_hedge" else "NO HEDGE"

    return {
        "agent": "HEDGE_ADVISOR",
        "title": "Hedge Recommendation",
        "narrative": narrative,
        "data": {
            "primary_recommendation": primary,
            "primary_rationale": primary_rationale,
            "secondary_recommendation": secondary,
            "secondary_rationale": secondary_rationale,
            "call_sell": call_sell_data,
            "put_buy": put_buy_data,
        },
        "verdict": verdict,
    }


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get(
    "/hedge-reasoning",
    response_model=HedgeReasoningResponse,
    summary="7-step deterministic hedge reasoning chain",
)
def get_hedge_reasoning(
    instrument: str = Query(..., description="Instrument identifier (e.g. ASML, NIFTY, NVIDIA)"),
    n_shares: int = Query(default=10, ge=1, description="Number of shares for EUR calculations"),
    ann_vol_override: float | None = Query(
        default=None,
        ge=0.1,
        description="Override annual volatility percentage (for what-if analysis)",
    ),
) -> HedgeReasoningResponse:
    """Compute a 7-step hedge reasoning chain for the given instrument.

    Each step maps to an existing RITA core function. No LLM calls.
    Read-only — no database writes. All values are indicative.
    """
    inst = instrument.upper()

    try:
        df = _get_df(inst)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"Unknown instrument: {inst}") from exc

    if len(df) < 30:
        raise HTTPException(
            status_code=422,
            detail=f"Insufficient data for {inst}: need at least 30 rows, got {len(df)}.",
        )

    required_cols = {"Open", "High", "Low", "Close", "Volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing OHLCV columns for {inst}: {', '.join(sorted(missing))}.",
        )

    spot = float(df["Close"].dropna().iloc[-1])

    step1 = _build_step_regime(df)
    regime = step1["data"]["regime"]

    step2 = _build_step_technicals(df)

    from rita.core.technical_analyzer import get_market_summary, get_sentiment_score

    summary = get_market_summary(df)
    step3 = _build_step_sentiment(summary)
    scored = get_sentiment_score(summary)

    step4 = _build_step_allocation(summary, scored)
    allocation = step4["data"]["recommendation"]

    step5 = _build_step_volatility(df, ann_vol_override)
    vol_data = step5["data"]

    step6 = _build_step_goal_analyst(df)
    goal_data = step6["data"]

    step7 = _build_step_hedge(regime, allocation, vol_data, spot, n_shares, goal_data)
    recommendation = step7["data"]["primary_recommendation"]

    total_score = scored["total_score"]
    if abs(total_score) >= 4:
        confidence = "high"
    elif abs(total_score) >= 2:
        confidence = "moderate"
    else:
        confidence = "low"

    steps = [
        ReasoningStep(**step1),
        ReasoningStep(**step2),
        ReasoningStep(**step3),
        ReasoningStep(**step4),
        ReasoningStep(**step5),
        ReasoningStep(**step6),
        ReasoningStep(**step7),
    ]

    return HedgeReasoningResponse(
        instrument=inst,
        timestamp=datetime.now(timezone.utc),
        steps=steps,
        recommendation=recommendation,
        confidence=confidence,
        spot_price=round(spot, 2),
        data_source="black_scholes",
    )
