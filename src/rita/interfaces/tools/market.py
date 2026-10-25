"""``market.*`` — market data and RITA analysis tools (owner: ``core/technical_analyzer.py``,
``core/classifier.py``, ``core/chat_monitor.py``, ``services/market_analysis_service.py``).

The functions here are also used by the legacy aliases (``tools/legacy.py``) so both render from
the same data.
"""
from __future__ import annotations

from pathlib import Path

from rita.interfaces.tools._base import ToolContext, ToolError, ToolSpec
from rita.schemas.mcp_tools import (
    InstrumentIn,
    MarketAskIn,
    MarketAskOut,
    MarketMonitorOut,
    MarketOverviewOut,
    NoArgsIn,
    SignalOut,
)

DEFAULT_PORTFOLIO_VALUE = 1_000_000

LOW_CONFIDENCE_TEXT = (
    "RITA could not confidently match your question to a known intent. "
    "Try rephrasing, or ask about: market sentiment, RSI, volatility, "
    "return estimates (1m/3m/1y/3y), stress scenarios, or strategy allocation."
)


def load_df(instrument: str):
    """Indicators DataFrame for ``instrument``; ``not_found`` if it has no price data."""
    from rita.services.market_analysis_service import get_indicator_df

    try:
        return get_indicator_df(instrument)
    except FileNotFoundError as exc:
        raise ToolError("not_found", f"no price data for instrument {instrument.upper()}") from exc


def market_snapshot(instrument: str) -> tuple[dict, dict]:
    """``(summary, scored)`` from ``technical_analyzer`` for the latest bar."""
    from rita.core.technical_analyzer import get_market_summary, get_sentiment_score

    summary = get_market_summary(load_df(instrument))
    return summary, get_sentiment_score(summary)


def ask(query: str, instrument: str, portfolio_value: float, target_return_pct: float | None,
        horizon_days: int | None):
    """Classify ``query`` and run the deterministic handler → ``(IntentResult, answer | None)``.

    ``answer`` is None when the classifier confidence is below the threshold.
    """
    from rita.config import get_settings
    from rita.core.classifier import classify, dispatch

    inst = instrument.upper()
    df = load_df(inst)
    result = classify(query)
    if result.low_confidence:
        return result, None
    output_dir = str(Path(get_settings().data.output_dir) / inst)
    answer = dispatch(
        result, df,
        portfolio_inr=portfolio_value,
        output_dir=output_dir,
        target_return_pct=target_return_pct,
        time_horizon_days=horizon_days,
    )
    return result, answer


def monitor_data(recent: int = 10) -> tuple[dict, list, list]:
    from rita.core.chat_monitor import get_intent_distribution, get_recent_queries, get_summary

    return get_summary(), get_intent_distribution() or [], get_recent_queries(recent) or []


# ── tools ──────────────────────────────────────────────────────────────────────

def overview(inp: InstrumentIn, _ctx: ToolContext) -> MarketOverviewOut:
    inst = inp.instrument.upper()
    summary, scored = market_snapshot(inst)
    return MarketOverviewOut(
        instrument=inst,
        as_of=summary["date"],
        sentiment=scored["overall_sentiment"],
        total_score=int(scored["total_score"]),
        trend=summary["trend"],
        rsi_14=summary["rsi_14"],
        atr_14=summary["atr_14"],
        atr_percentile=summary["atr_percentile"],
        bb_position=summary["bb_position"],
        ema_50=summary["ema_50"],
        ema_200=summary["ema_200"],
        close=summary["close"],
        signals={k: SignalOut(value=str(v["value"]), score=int(v["score"]))
                 for k, v in scored["signals"].items()},
    )


def ask_tool(inp: MarketAskIn, _ctx: ToolContext) -> MarketAskOut:
    inst = inp.instrument.upper()
    value = inp.portfolio_value if inp.portfolio_value is not None else DEFAULT_PORTFOLIO_VALUE
    target_pct = inp.target_return * 100 if inp.target_return is not None else None
    result, answer = ask(inp.query, inst, value, target_pct, inp.horizon_days)
    return MarketAskOut(
        instrument=inst,
        intent=result.intent.name,
        confidence=round(float(result.confidence), 4),
        low_confidence=bool(result.low_confidence),
        answer=answer if answer is not None else LOW_CONFIDENCE_TEXT,
    )


def monitor(_inp: NoArgsIn, _ctx: ToolContext) -> MarketMonitorOut:
    summary, intents, recent = monitor_data(10)
    return MarketMonitorOut(summary=summary, intents=intents, recent=recent)


TOOLS = [
    ToolSpec(
        name="market.overview",
        description=(
            "Current market state for an instrument from local OHLCV data: sentiment and score, "
            "trend, RSI-14, ATR-14 and its percentile, Bollinger position, EMA-50/200, close, "
            "signal breakdown, as_of date."
        ),
        input_model=InstrumentIn,
        output_model=MarketOverviewOut,
        handler=overview,
        auth=frozenset({"none"}),
        stdio=True,
        text=lambda o: (f"{o.instrument} {o.as_of}: {o.sentiment} ({o.total_score:+d}/6), "
                        f"{o.trend}, RSI {o.rsi_14:.1f}, close {o.close:,.2f}."),
        summary=lambda o: f"instrument={o.instrument} as_of={o.as_of} sentiment={o.sentiment}",
    ),
    ToolSpec(
        name="market.ask",
        description=(
            "Ask RITA an investment question about an instrument. A local MiniLM classifier routes "
            "it to one of 20 fixed intents and a deterministic OHLCV handler answers. Fully offline."
        ),
        input_model=MarketAskIn,
        output_model=MarketAskOut,
        handler=ask_tool,
        auth=frozenset({"none"}),
        stdio=True,
        text=lambda o: o.answer,
        summary=lambda o: f"intent={o.intent} confidence={o.confidence:.2f} low={o.low_confidence}",
    ),
    ToolSpec(
        name="market.monitor",
        description=(
            "RITA chat classifier KPIs (total queries, latency, low-confidence rate, queries today), "
            "intent distribution and the 10 most recent queries. Ops access required."
        ),
        input_model=NoArgsIn,
        output_model=MarketMonitorOut,
        handler=monitor,
        auth=frozenset({"user"}),
        requires_flag="can_access_ops",
        text=lambda o: f"Chat monitor: {o.summary.get('total_queries', 0)} queries.",
        summary=lambda o: f"total_queries={o.summary.get('total_queries', 0)} recent={len(o.recent)}",
    ),
]
