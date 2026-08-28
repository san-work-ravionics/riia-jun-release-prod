# RITA — MCP Server Specification

Exposes RITA's deterministic OHLCV investment analysis to Claude Desktop via the Model Context Protocol (MCP).
Fully local — no Claude/Anthropic API call at runtime.

---

## Architecture

```
Claude Desktop
    │  stdio (spawn)
    ▼
rita_mcp_server.py          ← MCP stdio process (separate from FastAPI)
    │  direct Python import
    ├── rita.core.classifier  (classify + dispatch)
    ├── rita.api.v1.workflow.chat._get_df  (indicator DataFrame loader)
    ├── rita.core.technical_analyzer  (get_market_summary, get_sentiment_score)
    └── rita.core.chat_monitor  (get_summary, get_recent_queries, get_intent_distribution)
    │  appends CSV row after every tool call
    ▼
data/output/mcp_calls.csv   ← shared log file
    │  read by FastAPI
    ▼
GET /api/v1/mcp-calls       ← RITA FastAPI server (running separately)
    │
    ▼
mcp.js → loadMcp()          ← RITA dashboard "MCP Calls" section
```

**Key constraint:** The MCP server and the RITA FastAPI server are two independent processes.
They share state only via the `mcp_calls.csv` file. The MCP server does NOT make HTTP calls to FastAPI.

---

## Source Files

| File | Role |
|---|---|
| `src/rita/interfaces/rita_mcp_server.py` | MCP stdio server — entry point, tool definitions, handlers |
| `src/rita/interfaces/__init__.py` | Package init (empty) |
| `src/rita/core/mcp_logger.py` | CSV append log — written by server, read by API endpoint |
| `src/rita/api/v1/system/mcp_calls.py` | `GET /api/v1/mcp-calls` FastAPI router |
| `src/rita/main.py` | Registers `mcp_calls_router` in the system tier |
| `pyproject.toml` | `mcp>=1.0` added under `[project.optional-dependencies] interfaces` |
| `project-office/claude_desktop_config_snippet.json` | Config block to paste into Claude Desktop |

---

## MCP Tools

### `ask_rita`
Classify a free-text investment query and return a deterministic OHLCV-driven answer.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | — | Natural-language investment question |
| `instrument` | enum | no | `NIFTY` | `NIFTY`, `BANKNIFTY`, `ASML`, `NVIDIA` |
| `portfolio_inr` | number | no | `1000000` | Portfolio size in INR (used by stress + allocation handlers) |
| `target_return_pct` | number | no | — | Target annual return % — triggers feasibility commentary on return-estimate intents |
| `time_horizon_days` | integer | no | — | Investment horizon in days |

**Returns:** Intent name + confidence + deterministic handler response (Markdown string).
Mirrors `POST /api/v1/chat` but called by Claude Desktop instead of the dashboard.

**Intent coverage:** Same 20 intents as the chat classifier — see `Spec_Chat_Feature.md`.

---

### `rita_market_overview`
Current market state for an instrument: sentiment score, trend, RSI-14, ATR percentile, Bollinger position, EMA levels.

| Parameter | Type | Required | Default |
|---|---|---|---|
| `instrument` | enum | no | `NIFTY` |

**Returns:** Formatted Markdown summary + 5-signal breakdown. Equivalent to opening the RITA chat warmup.

---

### `rita_monitor`
RITA chat classifier KPIs and 10 most recent queries.

No parameters.

**Returns:** Total queries, avg latency, low-confidence %, queries today, top-5 intent distribution, recent query log.
Reads from `chat_monitor.csv` (not `mcp_calls.csv`).

---

## MCP Call Logger (`mcp_logger.py`)

**CSV path:** `<project-root>/logs/mcp_calls.csv` — absolute path derived from `__file__` in `mcp_logger.py`.
Always resolves to `riia-jun-release/logs/mcp_calls.csv` regardless of the calling process's working directory.
Do not use `get_settings().data.output_dir` for this path — the MCP server and FastAPI server must agree on the same absolute location.

**Columns:**

| Column | Type | Description |
|---|---|---|
| `id` | int | Auto-increment row number |
| `timestamp` | ISO-8601 string | UTC timestamp of the call |
| `tool_name` | string | `ask_rita`, `rita_market_overview`, `rita_monitor` |
| `status` | string | `ok` or `error` |
| `duration_ms` | float | Wall-clock time for the tool handler |
| `args_summary` | string | Truncated key args (max 300 chars) |
| `result_summary` | string | First 200 chars of the response |

**Functions:**
- `log_mcp_call(tool_name, args_summary, result_summary, duration_ms, status)` — appended by server
- `get_mcp_calls(limit=100)` — read by `GET /api/v1/mcp-calls`, returns newest-first list
- `get_mcp_summary()` — returns KPI dict: `total_calls`, `avg_duration_ms`, `error_rate_pct`, `calls_today`

---

## FastAPI Endpoint

```
GET /api/v1/mcp-calls?limit=100
```

- **Router:** `src/rita/api/v1/system/mcp_calls.py`
- **Tier:** System (no auth, no DB dependency)
- **Response:** Flat JSON array of call rows (newest first), shape consumed by `mcp.js → loadMcp()`
- **Query param:** `limit` — integer 1–500, default 100

---

## Dashboard Integration

`mcp.js` and `main.js` are already fully wired. When the user navigates to the **MCP Calls** section in `rita.html`:

1. `_sectionLoaders.mcp = loadMcp` fires on first visit
2. `loadMcp()` calls `GET /api/v1/mcp-calls?limit=100`
3. Renders two Chart.js bar charts (calls-per-tool, avg-duration-per-tool) + a detail table

No changes required to any JS or HTML files.

---

## Claude Desktop Configuration

### Config file location (Windows)
```
C:\Users\Sandeep\AppData\Roaming\Claude\claude_desktop_config.json
```

### Config block to paste
```json
{
  "mcpServers": {
    "rita": {
      "command": "python",
      "args": ["-m", "rita.interfaces.rita_mcp_server"],
      "cwd": "C:\\Users\\Sandeep\\Documents\\Work\\code\\riia-cowork-jun\\riia-jun-release",
      "env": {
        "PYTHONPATH": "C:\\Users\\Sandeep\\Documents\\Work\\code\\riia-cowork-jun\\riia-jun-release\\src"
      }
    }
  }
}
```

If the file already has other MCP servers, merge the `"rita"` key into the existing `"mcpServers"` object — do not replace the whole file.

### If using a specific Python / conda environment
Replace `"command": "python"` with the full path to the Python executable, e.g.:
```json
"command": "C:\\Users\\Sandeep\\anaconda3\\envs\\rita\\python.exe"
```

---

## Installation

```bash
# Run once from riia-jun-release/
pip install -e .[interfaces]
```

This installs the `mcp>=1.0` SDK. All other dependencies (`sentence-transformers`, `pandas`, etc.) are already in the base install.

After updating the Claude Desktop config, **restart Claude Desktop** for the server to appear.

---

## Running the Server Manually (for testing)

```bash
cd C:\Users\Sandeep\Documents\Work\code\riia-cowork-jun\riia-jun-release
python -m rita.interfaces.rita_mcp_server
```

The server speaks MCP over stdin/stdout. In normal use Claude Desktop spawns it automatically.
To test tool responses interactively, use the [MCP Inspector](https://github.com/modelcontextprotocol/inspector):
```bash
npx @modelcontextprotocol/inspector python -m rita.interfaces.rita_mcp_server
```

---

## Example Commands and Expected Responses

Each example shows the tool name, the arguments you pass in Claude Desktop, and the response text RITA returns.

---

### `ask_rita` — market sentiment

**Input**
```json
{
  "query": "What is the current market sentiment?",
  "instrument": "NIFTY"
}
```

**Expected response**
```
**Instrument:** NIFTY
**Intent:** market_sentiment (confidence 0.87)

Market sentiment: **CAUTIOUSLY_BULLISH** (score +2/6).
EMA trend bullish, RSI neutral, MACD marginally positive.
```

---

### `ask_rita` — return estimate with target

**Input**
```json
{
  "query": "What returns can I expect in 1 year?",
  "instrument": "NIFTY",
  "target_return_pct": 18.0
}
```

**Expected response**
```
**Instrument:** NIFTY
**Intent:** return_1y (confidence 0.91)

Historical 1 year CAGR — median **14.2%**
(best 25%: +22.1%, worst 25%: 3.8%, win rate: 72%).
Your target of **18.0%** is above median — achievable in roughly 25–50% of historical windows.
```

---

### `ask_rita` — stress scenario

**Input**
```json
{
  "query": "What if the market crashes 20 percent?",
  "instrument": "NIFTY",
  "portfolio_inr": 2000000
}
```

**Expected response**
```
**Instrument:** NIFTY
**Intent:** stress_crash_20 (confidence 0.93)

If the market falls 20%: RITA (60% invested) → **-12.0%**
vs Aggressive −20.0%, Moderate −12.0%, Conservative −6.0%.
Drawdown breach: YES.
```

---

### `ask_rita` — strategy recommendation

**Input**
```json
{
  "query": "Should I invest in Nifty now?",
  "instrument": "NIFTY"
}
```

**Expected response**
```
**Instrument:** NIFTY
**Intent:** invest_now (confidence 0.89)

Recommended action: **INVEST** (75% invested).
Sentiment is cautiously bullish with RSI in neutral zone and EMA trend confirmed upward.
```

---

### `ask_rita` — low confidence (query outside known intents)

**Input**
```json
{
  "query": "Tell me about the weather in Mumbai",
  "instrument": "NIFTY"
}
```

**Expected response**
```
**Instrument:** NIFTY
**Intent:** uncertain (confidence 0.21 — below 0.42 threshold)

RITA could not confidently match your question to a known intent.
Try rephrasing, or ask about: market sentiment, RSI, volatility,
return estimates (1m/3m/1y/3y), stress scenarios, or strategy allocation.
```

---

### `ask_rita` — explain RITA's decision

**Input**
```json
{
  "query": "Why did RITA recommend HOLD?",
  "instrument": "NIFTY"
}
```

**Expected response**
```
**Instrument:** NIFTY
**Intent:** explain_decision (confidence 0.88)

**RITA recommendation: HOLD (50% invested)**

**Why:** Mixed signals — RSI overbought while trend score is mildly positive.

**Signal breakdown:**
- Trend: uptrend               (score +1)
- MACD: bearish crossover      (score -1)
- RSI: overbought              (score -1)
- Bollinger: near upper band   (score -1)
- Volatility: normal range     (score +0)
- **Total: -2/6** → CAUTIOUSLY_BEARISH

**Next trigger:** RSI falling below 65 would remove overbought constraint.
```

---

### `rita_market_overview` — full instrument snapshot

**Input**
```json
{
  "instrument": "NIFTY"
}
```

**Expected response**
```
**NIFTY — Market Overview**

Sentiment:   **CAUTIOUSLY_BULLISH** (score +2/6)
Trend:       uptrend (score +0.412)
RSI-14:      58.3 — neutral
ATR-14:      142.50  (volatility at 44th percentile)
Bollinger:   middle_band  (bb%B 0.52)
EMA-50:      22,184.30   |   EMA-200: 21,890.75
Close:       22,519.40 as of 2026-05-02

**Signal breakdown:**
  Trend      uptrend                (+1)
  MACD       bullish                (+1)
  RSI        neutral                (+0)
  Bollinger  middle_band            (+0)
  Volatility normal range           (+0)
```

---

### `rita_market_overview` — ASML

**Input**
```json
{
  "instrument": "ASML"
}
```

**Expected response**
```
**ASML — Market Overview**

Sentiment:   **BEARISH** (score -3/6)
Trend:       downtrend (score -0.601)
RSI-14:      34.1 — oversold
ATR-14:      28.74  (volatility at 81st percentile)
Bollinger:   near_lower_band  (bb%B 0.09)
EMA-50:      698.40   |   EMA-200: 742.15
Close:       671.20 as of 2026-05-02

**Signal breakdown:**
  Trend      downtrend              (-1)
  MACD       bearish                (-1)
  RSI        oversold               (-1)
  Bollinger  near_lower_band        (+0)
  Volatility high volatility        (-1)
```

---

### `rita_monitor` — classifier health check

**Input**
```json
{}
```

**Expected response**
```
**RITA Chat Monitor**

Total queries:     47
Avg latency:       183.4 ms
Low confidence:    12.8%
Queries today:     9

**Intent distribution (top 5):**
  market_sentiment             11 calls
  invest_now                    8 calls
  return_1y                     7 calls
  stress_crash_20               5 calls
  explain_decision              4 calls

**Recent queries:**
  [2026-05-05T09:14] invest_now             conf=0.89  Should I invest in Nifty now?
  [2026-05-05T09:11] market_sentiment       conf=0.87  What is the current market sentiment?
  [2026-05-05T08:58] return_1y             conf=0.91  What returns can I expect in 1 year?
  [2026-05-04T17:32] stress_crash_20       conf=0.93  What if the market crashes 20 percent?
  [2026-05-04T17:28] explain_decision      conf=0.88  Why did RITA recommend HOLD?
```

---

## Known Constraints

- **Route shadowing — do not add `/mcp-calls` to `data_prep.py`:** FastAPI resolves routes in registration order. `data_prep_router` (prefix `/api/v1`) is registered in `main.py` *before* `mcp_calls_router`. If `data_prep.py` contains a `@router.get("/mcp-calls")` handler, it will shadow the real router and always return `[]` — the real handler never executes. This stub was present and removed in May 2026. Do not re-add any `/mcp-calls` route to `data_prep.py`.
- **Working directory:** Claude Desktop spawns MCP servers with `cwd=C:\WINDOWS\system32`, ignoring the `cwd` field in the config. The server works around this by calling `os.chdir()` to the project root at startup, derived from `__file__` (4 levels up from `rita_mcp_server.py`). Do not remove this chdir.
- **stdout is sacred:** MCP uses stdout exclusively for JSON-RPC framing. Any non-JSON bytes on stdout — structlog lines, Python `logging` output, `print()` calls — cause `"Unexpected non-whitespace character after JSON"` on the Claude Desktop side. The server configures both `logging` and `structlog` to write to stderr before any `rita.*` import. Do not add `print()` statements or unconfigured loggers to this module.
- The MCP server is stateless across sessions — the DataFrame cache (`_market_signals_cache` in `chat.py`) resets each time Claude Desktop restarts the server process.
- `rita_monitor` reads the **chat** query log (`chat_monitor.csv`), not the MCP call log. It reflects activity from both the dashboard chat and MCP tool calls that route through `ask_rita`.
- First call after server start loads the SentenceTransformer model (~1–3 s cold start). Subsequent calls are fast.
- The `PYTHONPATH` env var in the config is only needed if `pip install -e .` has not been run. Either approach works.
