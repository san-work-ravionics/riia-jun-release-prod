"""
RITA Core — Strategy Engine

Rule-based allocation recommendation that mirrors the DDQN model's action space.
Used by the chat classifier dispatch() to answer strategy/allocation intents.
"""
from __future__ import annotations


def get_allocation_recommendation(summary: dict, scored: dict) -> dict:
    """
    Rule-based proxy for the DDQN model's allocation decision.

    Inputs are the outputs of get_market_summary() and get_sentiment_score()
    from technical_analyzer.py — the same 5 signals the RL model observes.

    Returns one of three actions matching the RL model's action space:
        action 0 → HOLD  (0%  invested)
        action 1 → HALF  (50% invested)
        action 2 → FULL  (100% invested)

    Decision is calibrated toward the two project constraints:
        Sharpe > 1.0       — don't enter unless risk/reward is favourable
        Max drawdown < 10% — exit / reduce if downside risk is elevated
    """
    total_score = scored["total_score"]
    trend       = summary["trend"]
    rsi_signal  = summary["rsi_signal"]
    bb_position = summary["bb_position"]
    volatility  = summary["sentiment_proxy"]   # fearful / neutral / complacent
    overall     = scored["overall_sentiment"]

    # ── Base action from sentiment score ──────────────────────────────────────
    if total_score >= 3:
        action = 2   # FULL — strong bullish consensus, maximise Sharpe
    elif total_score >= -1:
        action = 1   # HALF — mixed signals, balance return vs drawdown
    else:
        action = 0   # HOLD — bearish, protect against MDD breach

    # ── Override rules — max drawdown < 10% protection ───────────────────────
    override_reason = None

    if volatility == "fearful" and action == 2:
        action = 1
        override_reason = (
            "High volatility (fearful ATR) caps at 50% — "
            "large daily swings risk breaching 10% drawdown limit"
        )

    if trend == "downtrend" and action == 2:
        action = 1
        override_reason = (
            "Downtrend caps at 50% — "
            "sustained negative returns risk breaching 10% drawdown limit"
        )

    if trend == "downtrend" and volatility == "fearful":
        action = 0
        override_reason = (
            "Downtrend + fearful volatility: HOLD — "
            "combined risk too high, protecting against drawdown > 10%"
        )

    if rsi_signal == "overbought" and bb_position == "near_upper_band":
        action = max(0, action - 1)
        override_reason = (
            "Overbought RSI + price at upper Bollinger Band: "
            "reversal risk, stepping down one allocation level"
        )

    # ── Map action to output labels ───────────────────────────────────────────
    _ACTION_MAP = {0: ("HOLD", 0), 1: ("HALF", 50), 2: ("FULL", 100)}
    label, alloc_pct = _ACTION_MAP[action]

    if action == 0:
        primary_constraint = "max_drawdown < 10%"
    elif action == 2:
        primary_constraint = "Sharpe > 1.0"
    else:
        primary_constraint = "Sharpe > 1.0 & max_drawdown < 10%"

    # ── Plain-English rationale ───────────────────────────────────────────────
    score_desc = scored["signal_summary"]
    if override_reason:
        rationale = (
            f"Base signals ({overall}, score {total_score:+d}/6): {score_desc}. "
            f"Override: {override_reason}."
        )
    else:
        rationale = (
            f"Sentiment {overall} (score {total_score:+d}/6): {score_desc}. "
            f"Driving constraint: {primary_constraint}."
        )

    # ── Triggers for next review ──────────────────────────────────────────────
    if action == 2:
        upgrade_trigger   = "Already at maximum allocation."
        downgrade_trigger = (
            "Reduce to HALF if downtrend confirmed or volatility turns fearful "
            "(score drops below +3)"
        )
    elif action == 1:
        upgrade_trigger = (
            "Move to FULL if uptrend + MACD bullish + volatility not fearful "
            "(score >= 3)"
        )
        downgrade_trigger = "Move to HOLD if downtrend + fearful volatility or score <= -2"
    else:
        upgrade_trigger = (
            "Move to HALF if trend turns sideways or up and MACD turns bullish "
            "(score >= -1)"
        )
        downgrade_trigger = "Already at minimum allocation."

    return {
        "recommendation":    label,
        "allocation_pct":    alloc_pct,
        "action_code":       action,
        "primary_constraint": primary_constraint,
        "rationale":         rationale,
        "upgrade_trigger":   upgrade_trigger,
        "downgrade_trigger": downgrade_trigger,
        "override_applied":  override_reason is not None,
        "override_reason":   override_reason,
    }
