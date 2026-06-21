"""Experience Layer — Hedge Reasoning endpoint (Feature 31 Phase 1).

ADR-001 Tier 3: read-only composition, no writes, no side effects.
Returns a 6-step deterministic reasoning chain for hedge recommendations.

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
from rita.schemas.hedge_reasoning import HedgeReasoningResponse, PayoffCurves, ReasoningStep

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


def _build_step_hedge(
    regime: str,
    allocation: str,
    vol_data: dict,
    spot: float,
    n_shares: int,
) -> dict:
    """Step 6 — HEDGE ADVISOR: decision matrix + BS pricing."""
    ann_vol = vol_data["ann_vol_253d"]
    vol_regime = vol_data["vol_regime"]

    # Decision matrix: regime x allocation x vol
    if allocation == "HOLD":
        primary = "no_hedge"
        primary_rationale = "No position to protect — allocation is HOLD (0% invested)."
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

    # Build narrative
    if allocation == "HOLD":
        narrative = (
            "Allocation is HOLD (0% invested) — no position to hedge. "
            "No hedge recommendation generated."
        )
    else:
        rec_label = "CALL SELL (covered call)" if primary == "call_sell" else "PUT BUY (protective put)"
        narrative = (
            f"Given {regime} regime + {allocation} allocation + {vol_regime} volatility "
            f"-> Primary recommendation: {rec_label}. "
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


def _build_payoff_curves(
    spot: float,
    n_shares: int,
    ann_vol: float,
    strike_pct: float,
) -> PayoffCurves:
    """Build 33-point payoff comparison grid: unhedged, call_sell, put_buy."""
    price_range = np.linspace(spot * 0.75, spot * 1.25, 33)

    call_prem_pct = _bs_call_pct(ann_vol, strike_pct) / 100.0
    put_prem_pct = _bs_put_pct(ann_vol, -strike_pct) / 100.0

    call_strike = spot * (1 + strike_pct / 100)
    put_strike = spot * (1 - strike_pct / 100)

    premium_call_per_share = spot * call_prem_pct
    premium_put_per_share = spot * put_prem_pct

    unhedged = []
    call_sell = []
    put_buy = []

    for p in price_range:
        # Unhedged: simple long stock P&L
        uh = (p - spot) * n_shares
        unhedged.append(round(uh, 2))

        # Covered call: long stock + short call
        stock_pnl = (p - spot) * n_shares
        call_pnl = -(max(p - call_strike, 0) - premium_call_per_share) * n_shares
        call_sell.append(round(stock_pnl + call_pnl, 2))

        # Protective put: long stock + long put
        put_pnl = (max(put_strike - p, 0) - premium_put_per_share) * n_shares
        put_buy.append(round(stock_pnl + put_pnl, 2))

    return PayoffCurves(
        price_range=[round(float(p), 2) for p in price_range],
        unhedged=unhedged,
        call_sell=call_sell,
        put_buy=put_buy,
    )


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get(
    "/hedge-reasoning",
    response_model=HedgeReasoningResponse,
    summary="6-step deterministic hedge reasoning chain",
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
    """Compute a 6-step hedge reasoning chain for the given instrument.

    Each step maps to an existing RITA core function. No LLM calls.
    Read-only — no database writes. All values are indicative.
    """
    inst = instrument.upper()

    # Edge case: load data, handle unknown instrument
    try:
        df = _get_df(inst)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"Unknown instrument: {inst}") from exc

    # Edge case: insufficient data
    if len(df) < 30:
        raise HTTPException(
            status_code=422,
            detail=f"Insufficient data for {inst}: need at least 30 rows, got {len(df)}.",
        )

    # Edge case: missing OHLCV columns
    required_cols = {"Open", "High", "Low", "Close", "Volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing OHLCV columns for {inst}: {', '.join(sorted(missing))}.",
        )

    spot = float(df["Close"].dropna().iloc[-1])

    # Step 1 — Regime
    step1 = _build_step_regime(df)
    regime = step1["data"]["regime"]

    # Step 2 — Technicals
    step2 = _build_step_technicals(df)

    # Step 3 — Sentiment (needs market summary)
    from rita.core.technical_analyzer import get_market_summary, get_sentiment_score

    summary = get_market_summary(df)
    step3 = _build_step_sentiment(summary)
    scored = get_sentiment_score(summary)

    # Step 4 — Allocation
    step4 = _build_step_allocation(summary, scored)
    allocation = step4["data"]["recommendation"]

    # Step 5 — Volatility
    step5 = _build_step_volatility(df, ann_vol_override)
    vol_data = step5["data"]

    # Step 6 — Hedge recommendation
    step6 = _build_step_hedge(regime, allocation, vol_data, spot, n_shares)
    recommendation = step6["data"]["primary_recommendation"]

    # Confidence derivation from total sentiment score
    total_score = scored["total_score"]
    if abs(total_score) >= 4:
        confidence = "high"
    elif abs(total_score) >= 2:
        confidence = "moderate"
    else:
        confidence = "low"

    # Payoff curves
    ann_vol = vol_data["ann_vol_253d"]
    sigma_pct = min(ann_vol / math.sqrt(12), 15.0)
    strike_pct = round(sigma_pct, 2)

    if allocation == "HOLD":
        # No position — flat payoff curves
        price_range = np.linspace(spot * 0.75, spot * 1.25, 33)
        zeros = [0.0] * 33
        payoff = PayoffCurves(
            price_range=[round(float(p), 2) for p in price_range],
            unhedged=zeros,
            call_sell=zeros,
            put_buy=zeros,
        )
    else:
        payoff = _build_payoff_curves(spot, n_shares, ann_vol, strike_pct)

    steps = [
        ReasoningStep(**step1),
        ReasoningStep(**step2),
        ReasoningStep(**step3),
        ReasoningStep(**step4),
        ReasoningStep(**step5),
        ReasoningStep(**step6),
    ]

    return HedgeReasoningResponse(
        instrument=inst,
        timestamp=datetime.now(timezone.utc),
        steps=steps,
        recommendation=recommendation,
        confidence=confidence,
        payoff_curves=payoff,
        spot_price=round(spot, 2),
        data_source="black_scholes",
    )
