# RITA — Chat Feature Specification

Fully local — no Claude/Anthropic API calls at runtime.

---

## Architecture (3-layer pipeline)

### 1. Intent Classification (`src/rita/core/classifier.py`)
- Uses `sentence-transformers/all-MiniLM-L6-v2` — a local embedding model
- 20 fixed investment intents, each with seed phrases
- Cosine similarity between user query and seed embeddings → best-matching intent
- Confidence threshold: **0.42** (below = low-confidence fallback response)
- Model is lazy-loaded once, then cached in memory (`_model` global)
- **Embed model path resolution (2026-07-05):** `chat.embed_model_path` default in
  `base.yaml` is the Windows HF-cache path. Per-machine override via the
  `RITA_CHAT_EMBED_MODEL_PATH` env var (handled in `config.py` alongside
  `RITA_MODEL_PATH`); on the Mac it's exported in `activate-env-mac.sh` pointing
  at the local HF cache snapshot. Production uses `production.yaml`
  (`/app/models/embed_model`, baked into the Docker image).
- **Intel Mac constraint:** torch is capped at 2.2.2 (last x86_64 macOS wheel), so
  the local venv must keep transformers ≤4.x / sentence-transformers ≤3.x —
  transformers 5.x requires torch ≥2.4 and crashes chat warmup on import.
  Production pins the modern stack via `constraints-prod.txt`.

### 2. Data Calculations (`dispatch()` in `classifier.py`)
- Once classified, a deterministic handler runs against live OHLCV data
- Handlers: `market_sentiment`, `strategy_recommendation`, `return_estimates`, `stress_scenarios`, `performance_feedback`, `portfolio_comparison`
- All responses computed from indicator calculations — no LLM generation

### 3. Response Caching (`src/rita/api/v1/workflow/chat.py`)
- `_market_signals_cache: dict[str, dict]` — keyed by instrument id
- Recomputes only when any source file's **mtime** changes (primary CSV + manual supplement)
- Per-instrument cache: supports NIFTY, BANKNIFTY, ASML, NVIDIA

---

## Router (`src/rita/api/v1/workflow/chat.py`)

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/chat/warmup` | POST | Pre-warms SentenceTransformer (called when chat UI opens) |
| `/api/v1/chat` | POST | Classify query + dispatch handler + log to `alerts` table |
| `/api/v1/chat/monitor` | GET | Chat KPIs and recent query log |

---

## 20 Intent Groups

| Intent group | Example intents | Handler |
|---|---|---|
| Return estimates | `return_1m`, `return_3m`, `return_6m`, `return_1y`, `return_3y`, `return_5y` | `get_period_return_estimates(df, period_days)` — rolling percentile windows over 25-year history |
| Sentiment & trend | `market_sentiment`, `trend_direction` | `get_sentiment_score()`, `get_market_summary()` |
| Technical signals | `rsi_reading`, `volatility_check` | `get_market_summary()` — RSI-14, ATR-14, EMAs |
| Strategy | `invest_now`, `allocation_level`, `conservative_strategy`, `aggressive_strategy` | `get_allocation_recommendation()` in `strategy_engine.py` |
| Stress scenarios | `stress_crash_10`, `stress_crash_20`, `stress_rally_10`, `stress_flat` | `simulate_stress_scenarios()` in `performance.py` |
| Outcomes | `backtest_performance`, `portfolio_compare`, `explain_decision` | `_load_perf_summary()`, `build_portfolio_comparison()` |

---

## Data Cache Helper (`_get_df(instrument)`)

```python
def _get_df(instrument: str) -> pd.DataFrame:
    """Loads and caches the indicators DataFrame for the given instrument.
    Primary CSV: find_instrument_csv(inst) via data_understanding.py
    Supplement: data/input/DAILY-DATA/{inst}_manual.csv (if exists)
    Cache key: (mtime_primary, mtime_manual) — recomputes when either changes.
    """
```

Cache key per instrument: `(mtime_primary_csv, mtime_manual_csv)` — two-file mtime tuple.

---

## Agent Coverage Map

See `Specs/Spec-Agent-Workflow.md` for full gap analysis. Summary:

| Agent | Chat Coverage | Status |
|---|---|---|
| Financial Goal | return_1m/3m/6m/1y/3y/5y | Covered |
| Sentiment Analyst | market_sentiment, trend_direction | Proxy only (no news/FII data) |
| Technical Analyst | rsi_reading, volatility_check | Well covered |
| Strategy Analyst | invest_now, allocation_level, conservative/aggressive | Single allocator, no strategy-type split |
| Scenario Analyst | stress_crash_10/20, stress_rally_10, stress_flat | Covered |
| Execution Analyst | (none) | Not covered — no chat intents |
| Outcome Analyst | backtest_performance, portfolio_compare, explain_decision | Read-only, no closed loop |

**Key structural gap:** When `breach_note=YES` (MDD > 10%), chat flags it but has no path to suggest or record a hedging trade (Scenario → Execution bridge is missing).

---

## Known Issue (fixed 2026-04-xx)

**`settings` vs `get_settings()`** — in chat.py and observability endpoints, always call `get_settings()` (function call). Never use a bare `settings` name at module level — it raises `NameError` caught silently, causing endpoints to return `[]` and all KPIs to show `—`.
