"""Feature 32 Phase 4 — realized-outcome evaluation for agent recommendations.

The closed loop needs to know whether an agent's recommendation *came true*. This
module defines, per chat intent:
  • EVAL_HORIZON_DAYS — how many trading days forward the call is judged over,
  • a compact, parseable recommendation encoding (instrument + implied direction),
  • evaluate_outcome() — compares the implied direction to the realised price move
    over the horizon and returns one of:
        "match"          — the call was borne out,
        "miss"           — the call was wrong,
        "neutral"        — move within the dead-band (neither right nor wrong),
        "not_evaluable"  — intent is a hypothetical / report with no price truth,
        None             — not enough forward data yet (still pending / immature).

Grounded in realised price only — no model internals — so it is a stable signal
for both the dashboard outcome_match_rate and a future retrain reward term.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

import pandas as pd

# Forward window (trading days) over which each intent's call is judged.
EVAL_HORIZON_DAYS: dict[str, int] = {
    # Financial Goal — return forecasts: judged over their own horizon.
    "return_1m": 21, "return_3m": 63, "return_6m": 126,
    "return_1y": 252, "return_3y": 756, "return_5y": 1260,
    # Technical Analyst — short-horizon directional reads.
    "trend_direction": 5,
    "rsi_reading": 5,
    "volatility_check": 5,
    # Execution Analyst — entry / hedge timing.
    "invest_now": 21,
    "explain_decision": 21,
    "hedge_advice": 21,
}

# Intents with no price-truth (hypotheticals, sentiment w/o feed, retrospective
# reports). Recorded honestly as "not_evaluable" rather than fabricating a result.
NOT_EVALUABLE_INTENTS: frozenset[str] = frozenset({
    "market_sentiment",
    "allocation_level", "conservative_strategy", "aggressive_strategy", "portfolio_compare",
    "stress_crash_10", "stress_crash_20", "stress_rally_10", "stress_flat",
    "backtest_performance", "backtest_1y_return",
})

# Realised-return dead-band: |move| below this is "neutral", not a hit or miss.
_DEAD_BAND = 0.01

# Fraction of a loss a protective hedge removes, used to compute the risk-adjusted
# "advised return" of a hedge recommendation (a simple protective-put proxy; carry
# ignored for the health metric). One documented assumption.
HEDGE_DOWNSIDE_PROTECTION = 0.6

# direction tokens whose "correct" outcome is a RISE / FALL / DRAWDOWN.
_BULLISH = {"up", "buy"}
_BEARISH = {"down"}
_HEDGE = {"hedge"}
_NO_HEDGE = {"nohedge"}


def build_recommendation(instrument: str, direction: str) -> str:
    """Encode the captured recommendation as a compact, parseable string.

    direction ∈ {up, down, buy, hedge, nohedge, none}. 'none' marks a
    not-evaluable call. Stored in agent_performance.recommendation (free String) —
    avoids a schema migration while still carrying the instrument + implied call.
    """
    return f"instrument={instrument};dir={direction}"


def derive_recommendation(intent: str, instrument: str, price_df: Optional[pd.DataFrame]) -> str:
    """Capture the implied directional call for an intent from current market data.

    Runs at instrumentation time (post-dispatch) so the recommendation that gets
    judged later is the one actually surfaced. Evaluable intents resolve to a
    direction (up/down/buy/hedge/nohedge); everything else → 'none' (not_evaluable).
    Defensive about missing indicator columns — never raises.
    """
    if intent in NOT_EVALUABLE_INTENTS or intent not in EVAL_HORIZON_DAYS:
        return build_recommendation(instrument, "none")

    direction = "none"
    try:
        last = price_df.iloc[-1] if price_df is not None and len(price_df) else None
        if intent.startswith("return_"):
            direction = "up"           # a return forecast implies upside over the horizon
        elif intent in ("invest_now", "explain_decision"):
            direction = "buy"          # recommending entry implies bullish
        elif intent == "trend_direction" and last is not None:
            direction = "up" if float(last.get("trend_score", 0.0)) >= 0 else "down"
        elif intent == "rsi_reading" and last is not None:
            rsi = float(last.get("rsi_14", 50.0))
            direction = "down" if rsi > 70 else "up" if rsi < 30 else "none"
        elif intent == "hedge_advice" and price_df is not None and "Close" in price_df.columns:
            recent = price_df["Close"].tail(60)
            dd = float(recent.iloc[-1]) / float(recent.max()) - 1.0 if len(recent) else 0.0
            direction = "hedge" if dd < -0.05 else "nohedge"
        # volatility_check and any other non-directional read stay "none".
    except Exception:
        direction = "none"

    return build_recommendation(instrument, direction)


def parse_recommendation(rec: Optional[str]) -> dict[str, str]:
    """Parse a build_recommendation() string back to a dict. Tolerant of junk."""
    out: dict[str, str] = {}
    if not rec:
        return out
    for part in rec.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _close_at_or_before(price_df: pd.DataFrame, when: datetime) -> Optional[int]:
    """Row position of the last bar at/before `when`, or None if all bars are after."""
    idx = price_df.index
    # idx is a DatetimeIndex; tz-normalise the comparison key.
    key = pd.Timestamp(when)
    if key.tzinfo is not None and idx.tz is None:
        key = key.tz_localize(None)
    elif key.tzinfo is None and idx.tz is not None:
        key = key.tz_localize(idx.tz)
    pos = idx.searchsorted(key, side="right") - 1
    return int(pos) if pos >= 0 else None


def forward_return(
    intent: str,
    created_at: datetime,
    price_df: Optional[pd.DataFrame],
) -> Optional[float]:
    """Realized return of the instrument over the intent's horizon from created_at.

    None if the intent has no horizon, price data is missing, the recommendation
    predates the data, or the horizon hasn't matured yet. Shared anchoring logic
    for both the verdict (evaluate_outcome) and the risk-adjusted advised_return.
    """
    if intent not in EVAL_HORIZON_DAYS:
        return None
    if price_df is None or len(price_df) == 0 or "Close" not in price_df.columns:
        return None
    ref_pos = _close_at_or_before(price_df, created_at)
    if ref_pos is None:
        return None
    target_pos = ref_pos + EVAL_HORIZON_DAYS[intent]
    if target_pos >= len(price_df):
        return None
    ref_close = float(price_df["Close"].iloc[ref_pos])
    if ref_close <= 0:
        return None
    return float(price_df["Close"].iloc[target_pos]) / ref_close - 1.0


def advised_return(
    intent: str,
    recommendation: Optional[str],
    created_at: datetime,
    price_df: Optional[pd.DataFrame],
) -> Optional[float]:
    """Realized return of *following the advice* over the horizon (risk-adjusted input).

    - hedge   → downside reduced by HEDGE_DOWNSIDE_PROTECTION (upside kept; carry ignored),
    - nohedge/up/buy → full exposure to the move,
    - down    → inverse exposure (gain when it falls).
    None when not evaluable / immature. Feeds the trigger's Sortino health metric.
    """
    fr = forward_return(intent, created_at, price_df)
    if fr is None:
        return None
    direction = parse_recommendation(recommendation).get("dir")
    if direction in _HEDGE:
        return fr if fr >= 0 else fr * (1.0 - HEDGE_DOWNSIDE_PROTECTION)
    if direction in _NO_HEDGE or direction in _BULLISH:
        return fr
    if direction in _BEARISH:
        return -fr
    return None


def evaluate_outcome(
    intent: str,
    recommendation: Optional[str],
    created_at: datetime,
    price_df: pd.DataFrame,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Return the realized outcome for one recommendation, or None if still pending.

    price_df: the instrument's OHLCV frame, DatetimeIndex ascending, with "Close".
    """
    if intent in NOT_EVALUABLE_INTENTS:
        return "not_evaluable"
    if intent not in EVAL_HORIZON_DAYS:
        return "not_evaluable"

    fields = parse_recommendation(recommendation)
    direction = fields.get("dir")
    if not direction or direction == "none":
        return "not_evaluable"

    realized_ret = forward_return(intent, created_at, price_df)
    if realized_ret is None:
        return None  # no anchor / not enough forward bars yet → still maturing

    return _classify_direction(direction, realized_ret)


def sortino(returns: list[float]) -> Optional[float]:
    """Mean return / downside deviation. None if < 2 points or no downside variance.

    Shared risk-adjusted score for the retrain trigger and the dashboard timeline.
    """
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    dd = math.sqrt(sum(min(0.0, r) ** 2 for r in returns) / len(returns))
    if dd == 0.0:
        return None
    return mean / dd


def outcome_match_sign(direction: str, realized_ret: float) -> int:
    """+1 if the call matched the realised move, −1 if it missed, 0 if neutral.

    Shared by the dashboard outcome evaluation and the Phase 4.2 RL reward term so
    the policy is trained on the *same* notion of "match" the dashboard reports.
    """
    verdict = _classify_direction(direction, realized_ret)
    return {"match": 1, "miss": -1}.get(verdict, 0)


def _classify_direction(direction: str, realized_ret: float) -> str:
    """Map (implied direction, realised return) → match / miss / neutral."""
    if direction in _BULLISH:
        if realized_ret > _DEAD_BAND:
            return "match"
        if realized_ret < -_DEAD_BAND:
            return "miss"
        return "neutral"
    if direction in _BEARISH:
        if realized_ret < -_DEAD_BAND:
            return "match"
        if realized_ret > _DEAD_BAND:
            return "miss"
        return "neutral"
    if direction in _HEDGE:
        # Hedging is "right" when a decline followed (the hedge protected capital).
        if realized_ret < -_DEAD_BAND:
            return "match"
        if realized_ret > _DEAD_BAND:
            return "miss"
        return "neutral"
    if direction in _NO_HEDGE:
        if realized_ret > _DEAD_BAND:
            return "match"
        if realized_ret < -_DEAD_BAND:
            return "miss"
        return "neutral"
    return "not_evaluable"
