"""
RITA MCP Server — stdio transport for Claude Desktop

Exposes RITA's deterministic OHLCV investment analysis as three MCP tools:

    ask_rita              — classify a free-text query + dispatch a handler
    rita_market_overview  — current sentiment, trend, RSI, ATR, Bollinger
    rita_monitor          — chat KPIs and recent query log

Fully local — no Claude/Anthropic API call at runtime.

Installation
------------
Install the mcp SDK alongside RITA's dependencies:
    pip install mcp

Run (for testing in the terminal):
    cd riia-jun-release
    python -m rita.interfaces.rita_mcp_server

Claude Desktop config (claude_desktop_config.json):
    {
      "mcpServers": {
        "rita": {
          "command": "python",
          "args": ["-m", "rita.interfaces.rita_mcp_server"],
          "cwd": "C:/Users/Sandeep/Documents/Work/code/riia-cowork-jun/riia-jun-release"
        }
      }
    }
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

# ── Pin working directory to riia-jun-release/ ────────────────────────────────
#    Claude Desktop spawns MCP servers with cwd=C:\WINDOWS\system32, so any
#    relative path in get_settings() (e.g. "data/output") resolves wrongly.
#    __file__ is always absolute, so we derive the project root from it.
#    rita_mcp_server.py → interfaces/ → rita/ → src/ → riia-jun-release/
_project_root = Path(__file__).resolve().parent.parent.parent.parent
os.chdir(_project_root)

# ── Ensure src/ is on sys.path when invoked as __main__ ───────────────────────
_src = _project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

# ── Redirect ALL logging output to stderr ─────────────────────────────────────
#    MCP uses stdout exclusively for JSON-RPC framing. Any non-JSON bytes on
#    stdout (structlog lines, warnings, print() calls) cause:
#      "Unexpected non-whitespace character after JSON at position N"
#    on the Claude Desktop side. Force every logging sink to stderr BEFORE
#    any rita.* import, because those modules create module-level loggers.
import logging  # noqa: E402
import structlog  # noqa: E402

logging.basicConfig(level=logging.WARNING, stream=sys.stderr, force=True)
structlog.configure(
    processors=[structlog.dev.ConsoleRenderer()],
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
)

from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
from mcp.types import TextContent, Tool  # noqa: E402

# ── MCP call logger (created in Step 2 — graceful fallback until then) ────────
try:
    from rita.core.mcp_logger import log_mcp_call as _log_call
except ImportError:
    def _log_call(**_kw) -> None:  # noqa: E704
        pass

# ── Server instance ────────────────────────────────────────────────────────────
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
    except Exception as log_exc:  # noqa: BLE001
        print(f"[rita-mcp] mcp_logger failed: {log_exc}", file=sys.stderr)

    return [TextContent(type="text", text=result_text)]


# ── Handler: ask_rita ──────────────────────────────────────────────────────────

def _handle_ask_rita(args: dict) -> str:
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


# ── Shared: instrument DataFrame loader ────────────────────────────────────────

def _load_df(instrument: str):
    """Load and cache the indicator DataFrame from the RITA chat module."""
    from rita.api.v1.workflow.chat import _get_df
    return _get_df(instrument)


# ── Shared: args summariser for the call log ───────────────────────────────────

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


# ── Entry point ────────────────────────────────────────────────────────────────

async def _main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(_main())
