"""Legacy tool names — aliases of ``market.ask`` / ``market.overview`` / ``market.monitor``
(ADR-007 §9). Kept for one release; removed with SSE in P4.

Output stays the Markdown text of the pre-F44 tools (byte-for-byte the same rendering) and the
input schemas are the original ones, so existing Claude Desktop configs keep working.
On stdio they keep today's behaviour (no user); over ``/mcp`` and SSE they need a JWT like every
tool, and ``rita_monitor`` needs the same ops access as ``market.monitor``.
"""
from __future__ import annotations

from rita.interfaces.tools._base import ToolContext, ToolSpec
from rita.interfaces.tools.market import ask, market_snapshot, monitor_data
from rita.schemas.mcp_tools import AskRitaIn, LegacyInstrumentIn, LegacyNoArgsIn

_INSTRUMENT_ENUM = ["NIFTY", "BANKNIFTY", "ASML", "NVIDIA"]


def ask_rita(inp: AskRitaIn, _ctx: ToolContext) -> str:
    instrument = inp.instrument.upper()
    result, answer = ask(inp.query, instrument, float(inp.portfolio_inr),
                         inp.target_return_pct, inp.time_horizon_days)

    header = f"**Instrument:** {instrument}"
    if answer is None:
        header += (
            f"\n**Intent:** uncertain (confidence {result.confidence:.2f} — below 0.42 threshold)"
            "\n\nRITA could not confidently match your question to a known intent. "
            "Try rephrasing, or ask about: market sentiment, RSI, volatility, "
            "return estimates (1m/3m/1y/3y), stress scenarios, or strategy allocation."
        )
        return header

    header += f"\n**Intent:** {result.intent.name} (confidence {result.confidence:.2f})"
    return f"{header}\n\n{answer}"


def market_overview(inp: LegacyInstrumentIn, _ctx: ToolContext) -> str:
    instrument = inp.instrument.upper()
    summary, scored = market_snapshot(instrument)
    signals = scored["signals"]

    lines = [
        f"**{instrument} — Market Overview**",
        "",
        f"Sentiment:   **{scored['overall_sentiment']}** (score {scored['total_score']:+d}/6)",
        f"Trend:       {summary['trend']} (score {summary['trend_score']:+.3f})",
        f"RSI-14:      {summary['rsi_14']:.1f} — {summary['rsi_signal']}",
        f"ATR-14:      {summary['atr_14']:,.2f}  "
        f"(volatility at {summary['atr_percentile'] * 100:.0f}th percentile)",
        f"Bollinger:   {summary['bb_position']}  (bb%B {summary['bb_pct_b']:.2f})",
        f"EMA-50:      {summary['ema_50']:,.2f}   |   EMA-200: {summary['ema_200']:,.2f}",
        f"Close:       {summary['close']:,.2f} as of {summary['date']}",
        "",
        "**Signal breakdown:**",
        f"  Trend      {signals['trend']['value']:22s} ({signals['trend']['score']:+d})",
        f"  MACD       {signals['macd']['value']:22s} ({signals['macd']['score']:+d})",
        f"  RSI        {signals['rsi']['value']:22s} ({signals['rsi']['score']:+d})",
        f"  Bollinger  {signals['bollinger']['value']:22s} ({signals['bollinger']['score']:+d})",
        f"  Volatility {signals['volatility']['value']:22s} ({signals['volatility']['score']:+d})",
    ]
    return "\n".join(lines)


def rita_monitor(_inp: LegacyNoArgsIn, _ctx: ToolContext) -> str:
    summary, intents, recent = monitor_data(10)

    lines = [
        "**RITA Chat Monitor**",
        "",
        f"Total queries:     {summary.get('total_queries', 0)}",
        f"Avg latency:       {float(summary.get('avg_latency_ms', 0)):.1f} ms",
        f"Low confidence:    {float(summary.get('low_conf_pct', 0)):.1f}%",
        f"Queries today:     {summary.get('queries_today', 0)}",
        "",
        "**Intent distribution (top 5):**",
    ]
    for entry in (intents or [])[:5]:
        lines.append(
            f"  {entry.get('intent_name', '?'):28s} {entry.get('count', 0)} calls"
        )

    lines += ["", "**Recent queries:**"]
    for r in (recent or []):
        ts    = str(r.get("timestamp", ""))[:16]
        conf  = float(r.get("confidence", 0))
        qtext = str(r.get("query_text", ""))[:60]
        lines.append(
            f"  [{ts}] {r.get('intent_name', '?'):22s} conf={conf:.2f}  {qtext}"
        )

    return "\n".join(lines)


_ASK_RITA_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Natural-language investment question, e.g. "
                "'Should I invest in Nifty now?' or 'What is the 3-year return estimate?'"
            ),
        },
        "instrument": {
            "type": "string",
            "enum": _INSTRUMENT_ENUM,
            "description": "Instrument to analyse. Defaults to NIFTY.",
            "default": "NIFTY",
        },
        "portfolio_inr": {
            "type": "number",
            "description": (
                "Portfolio size in INR used for stress and allocation calculations. "
                "Default 1,000,000."
            ),
            "default": 1_000_000,
        },
        "target_return_pct": {
            "type": "number",
            "description": (
                "Target annual return % — optional. When set on return-estimate "
                "intents, RITA assesses feasibility against historical percentiles."
            ),
        },
        "time_horizon_days": {
            "type": "integer",
            "description": "Investment horizon in days — optional.",
        },
    },
    "required": ["query"],
}

_OVERVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "instrument": {
            "type": "string",
            "enum": _INSTRUMENT_ENUM,
            "description": "Instrument to summarise. Defaults to NIFTY.",
            "default": "NIFTY",
        },
    },
    "required": [],
}

_MONITOR_SCHEMA = {"type": "object", "properties": {}, "required": []}


def _first_line(text: str) -> str:
    return text.splitlines()[0][:200] if text else ""


TOOLS = [
    ToolSpec(
        name="ask_rita",
        description=(
            "Ask RITA an investment question about Nifty 50, Bank Nifty, ASML, or Nvidia. "
            "Uses a local all-MiniLM-L6-v2 embedding classifier to route to one of 20 "
            "fixed intents, then runs a deterministic OHLCV-data handler. "
            "Fully offline — no LLM generation at runtime. (Legacy alias of market.ask.)"
        ),
        input_model=AskRitaIn,
        input_schema=_ASK_RITA_SCHEMA,
        handler=ask_rita,
        auth=frozenset({"none"}),
        stdio=True,
        summary=lambda text: text.splitlines()[1][:200] if text.count("\n") else _first_line(text),
    ),
    ToolSpec(
        name="rita_market_overview",
        description=(
            "Get the current market state for an instrument: overall sentiment score, "
            "trend direction, RSI-14, ATR volatility percentile, Bollinger Band position, "
            "and EMA levels. Equivalent to opening the RITA Market Analysis panel. "
            "(Legacy alias of market.overview.)"
        ),
        input_model=LegacyInstrumentIn,
        input_schema=_OVERVIEW_SCHEMA,
        handler=market_overview,
        auth=frozenset({"none"}),
        stdio=True,
        summary=lambda text: " ".join(text.splitlines()[:3])[:200],
    ),
    ToolSpec(
        name="rita_monitor",
        description=(
            "Retrieve RITA chat KPIs and the 10 most recent queries: "
            "total calls, average latency, low-confidence rate, success rate, "
            "and intent distribution. Useful for checking classifier health. "
            "(Legacy alias of market.monitor.)"
        ),
        input_model=LegacyNoArgsIn,
        input_schema=_MONITOR_SCHEMA,
        handler=rita_monitor,
        auth=frozenset({"user"}),
        requires_flag="can_access_ops",
        stdio=True,
        # KPIs only — the recent-query lines hold message text and are never logged.
        summary=lambda text: " ".join(ln.strip() for ln in text.splitlines()[2:6])[:200],
    ),
]
