"""
Shared MCP Server instance — tool definitions and handlers.

Imported by both transports:
  - rita_mcp_server.py  (stdio, spawned by Claude Desktop locally)
  - mcp_sse_app.py      (SSE, mounted in the FastAPI app on EC2)

No transport-specific setup (no chdir, no logging redirect, no sys.path hacks)
belongs here — keep this module side-effect-free at import time.
"""
from __future__ import annotations

import time

from mcp.server import Server
from mcp.types import TextContent, Tool

try:
    from rita.core.mcp_logger import log_mcp_call as _log_call
except ImportError:
    def _log_call(**_kw) -> None:  # noqa: E704
        pass

server = Server("rita")


# ── Tool catalogue ─────────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="ask_rita",
            description=(
                "Ask RITA an investment question about Nifty 50, Bank Nifty, ASML, or Nvidia. "
                "Uses a local all-MiniLM-L6-v2 embedding classifier to route to one of 20 "
                "fixed intents, then runs a deterministic OHLCV-data handler. "
                "Fully offline — no LLM generation at runtime."
            ),
            inputSchema={
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
                        "enum": ["NIFTY", "BANKNIFTY", "ASML", "NVIDIA"],
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
            },
        ),
        Tool(
            name="rita_market_overview",
            description=(
                "Get the current market state for an instrument: overall sentiment score, "
                "trend direction, RSI-14, ATR volatility percentile, Bollinger Band position, "
                "and EMA levels. Equivalent to opening the RITA Market Analysis panel."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "instrument": {
                        "type": "string",
                        "enum": ["NIFTY", "BANKNIFTY", "ASML", "NVIDIA"],
                        "description": "Instrument to summarise. Defaults to NIFTY.",
                        "default": "NIFTY",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="rita_monitor",
            description=(
                "Retrieve RITA chat KPIs and the 10 most recent queries: "
                "total calls, average latency, low-confidence rate, success rate, "
                "and intent distribution. Useful for checking classifier health."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
    ]


# ── Tool dispatch ──────────────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    t0 = time.perf_counter()
    status = "ok"
    result_text = ""

    try:
        if name == "ask_rita":
            result_text = _handle_ask_rita(arguments)
        elif name == "rita_market_overview":
            result_text = _handle_market_overview(arguments)
        elif name == "rita_monitor":
            result_text = _handle_monitor()
        else:
            raise ValueError(f"Unknown tool: {name}")
    except Exception as exc:  # noqa: BLE001
        status = "error"
        result_text = f"RITA error ({name}): {exc}"

    duration_ms = round((time.perf_counter() - t0) * 1_000, 1)
    try:
        _log_call(
            tool_name=name,
            args_summary=_summarise_args(arguments),
            result_summary=result_text[:200],
            duration_ms=duration_ms,
            status=status,
        )
    except Exception:  # noqa: BLE001
        pass

    return [TextContent(type="text", text=result_text)]


# ── Handler: ask_rita ──────────────────────────────────────────────────────────

def _handle_ask_rita(args: dict) -> str:
    from pathlib import Path
    from rita.core.classifier import classify, dispatch
    from rita.config import get_settings

    query      = args["query"]
    instrument = args.get("instrument", "NIFTY").upper()
    port_inr   = float(args.get("portfolio_inr", 1_000_000))
    target_ret = args.get("target_return_pct")
    horizon    = args.get("time_horizon_days")

    settings   = get_settings()
    output_dir = str(Path(settings.data.output_dir) / instrument)

    df     = _load_df(instrument)
    result = classify(query)

    header = f"**Instrument:** {instrument}"
    if result.low_confidence:
        header += (
            f"\n**Intent:** uncertain (confidence {result.confidence:.2f} — below 0.42 threshold)"
            "\n\nRITA could not confidently match your question to a known intent. "
            "Try rephrasing, or ask about: market sentiment, RSI, volatility, "
            "return estimates (1m/3m/1y/3y), stress scenarios, or strategy allocation."
        )
        return header

    header += f"\n**Intent:** {result.intent.name} (confidence {result.confidence:.2f})"
    response = dispatch(
        result, df,
        portfolio_inr=port_inr,
        output_dir=output_dir,
        target_return_pct=target_ret,
        time_horizon_days=horizon,
    )
    return f"{header}\n\n{response}"


# ── Handler: rita_market_overview ──────────────────────────────────────────────

def _handle_market_overview(args: dict) -> str:
    from rita.core.technical_analyzer import get_market_summary, get_sentiment_score

    instrument = args.get("instrument", "NIFTY").upper()
    df      = _load_df(instrument)
    summary = get_market_summary(df)
    scored  = get_sentiment_score(summary)
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


# ── Handler: rita_monitor ──────────────────────────────────────────────────────

def _handle_monitor() -> str:
    from rita.core.chat_monitor import get_intent_distribution, get_recent_queries, get_summary

    summary = get_summary()
    recent  = get_recent_queries(10)
    intents = get_intent_distribution()

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


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _load_df(instrument: str):
    from rita.api.v1.workflow.chat import _get_df
    return _get_df(instrument)


def _summarise_args(args: dict) -> str:
    if not args:
        return ""
    parts = []
    if "query" in args:
        parts.append(f"query={str(args['query'])[:60]!r}")
    if "instrument" in args:
        parts.append(f"instrument={args['instrument']}")
    for key in ("portfolio_inr", "target_return_pct", "time_horizon_days"):
        if args.get(key) is not None:
            parts.append(f"{key}={args[key]}")
    return ", ".join(parts) if parts else str(args)[:80]
