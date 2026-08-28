# RITA — Agent Commentary Feature Specification

Fully local — no external LLM. Deterministic rule-based reasoning today; `_build_narrative()` is the single swap point for a future LLM upgrade.

---

## What It Does

Auto-generates plain-English narrative commentary for two RITA dashboard pages:

| Page | Trigger | Display |
|---|---|---|
| Overview (Market Signals) | Auto-fires on section load via `loadMarketSignals()` | Typewriter animation in narrator box above the Overview title |
| Strategy | Fires in parallel with `POST /api/v1/strategy` on "Design Strategy" click | Typewriter animation in narrator box above the result grid |

---

## Architecture

### 1. API Endpoint (`src/rita/api/v1/workflow/commentary.py`)

- **Method/Path:** `POST /api/v1/commentary` — Workflow tier, no auth (matches chat_router pattern)
- **Dispatch table:** module-level `_DISPATCH: dict[tuple[str,str], Callable]` — `("rita","overview")` → `_handle_overview`, `("rita","strategy")` → `_handle_strategy`
- **HTTP 400** for unknown `app`+`page` combination or strategy called without `instrument`
- **HTTP 200 always** on data errors — fallback sentence in `commentary`; never HTTP 500

### 2. Reasoning Layer

**Overview handler** (`_handle_overview`):
- Instruments: `_OVERVIEW_INSTRUMENTS = ["NVIDIA", "ASML", "NIFTY", "BANKNIFTY"]` (module-level constant)
- Geographic buckets: US=NVIDIA, EU=ASML, India=NIFTY+BANKNIFTY
- Per-instrument try/except — partial data produces partial commentary, not an error
- Computes per-instrument × per-timeframe (weekly W, monthly ME): SMA-20, RSI-14, EMA-20 slope, volume avg-20
- Classifies each as: **STRONG / NEUTRAL / CONSOLIDATING / WEAK / RECOVERING** using RSI + price-vs-SMA + volume confirmation
- Rankings: composite z-score (`weekly × 2 + monthly`) across all 4 instruments

**Strategy handler** (`_handle_strategy`):
- Requires `instrument` in request — HTTP 400 if missing
- Calls `get_market_summary()` + `get_sentiment_score()` + `get_allocation_recommendation()` from core modules
- Builds rationale from `recommendation`, `allocation_pct`, `rationale`, `primary_constraint`

**`_build_narrative(data: dict) -> str`** — single LLM swap point. Replace body with LLM call when upgrading; `data` dict is the context passed in.

### 3. Data Cache

Imports `_get_df(instrument)` from `rita.api.v1.workflow.chat` — reuses the existing mtime-based OHLCV cache. Do not duplicate this helper.

NaN guard: any uncomputable metric (insufficient bars after resample, <30 daily rows, <20 resampled rows) defaults to NEUTRAL classification.

### 4. DB Audit (`commentary_logs` table)

One row written per request via `CommentaryLogRepository(db).create(...)`.

| Column | Type | Notes |
|---|---|---|
| `id` | str (UUID) | Primary key |
| `app` | str | e.g. `rita` |
| `page` | str | e.g. `overview`, `strategy` |
| `instrument` | str (nullable) | Set for strategy, null for overview |
| `latency_ms` | float | End-to-end handler latency |
| `status` | str | `ok` or `error` |
| `commentary_preview` | str | First 200 chars of generated text |
| `timestamp` | datetime (UTC) | Request time |

ORM model: `src/rita/models/commentary_log.py` → `CommentaryLogModel`
Repository: `src/rita/repositories/commentary_log.py` → `CommentaryLogRepository`
Migration: `alembic/versions/c7e2a4f81d39_add_commentary_log.py`

### 5. Monitor KPIs

Three fields added to `GET /api/v1/chat/monitor` response (read from `commentary_logs` via `CommentaryLogRepository.get_summary()`):

| Field | Description |
|---|---|
| `commentary_count` | Total rows in `commentary_logs` |
| `commentary_avg_latency_ms` | Average `latency_ms` across all rows |
| `commentary_error_count` | Count of rows where `status = 'error'` |

---

## API Contract

### Request

```json
{ "app": "rita", "page": "overview" }
{ "app": "rita", "page": "strategy", "instrument": "NIFTY" }
```

### Response

```json
{
  "app": "rita",
  "page": "overview",
  "commentary": "Cross-instrument overview: ...",
  "instruments_analyzed": ["NVIDIA", "ASML", "NIFTY", "BANKNIFTY"],
  "latency_ms": 142.3
}
```

### Error responses

| Case | HTTP | Detail |
|---|---|---|
| Unknown app+page | 400 | `No handler registered for app='X' page='Y'` |
| Strategy without instrument | 400 | `instrument is required for page='strategy'` |

---

## Frontend

### JS Module (`dashboard/js/rita/commentary.js`)

| Export | Description |
|---|---|
| `loadOverviewCommentary()` | async — calls `POST /api/v1/commentary`, shows result or `—` on failure |
| `showOverviewCommentary(text)` | Shows and animates overview narrator box |
| `showStrategyCommentary(text)` | Shows and animates strategy narrator box |

Internal: `_showCommentaryNarrator(titleId, textId, title, text, speed=10)` with module-level `_twToken` cancel counter — incremented on each call to abort any in-flight typewriter animation.

### Integration points

| File | Change |
|---|---|
| `market-signals.js` | `loadMarketSignals()` calls `await loadOverviewCommentary()` after `loadGeoPanels()` |
| `export.js` | `runStrategy()` uses `Promise.allSettled([commentary, strategy])` — strategy grid always renders even if commentary fails |
| `main.js` | `window.loadOverviewCommentary = loadOverviewCommentary` |

### DOM elements (both in `rita.html`)

| ID | Role |
|---|---|
| `commentary-overview-box` | Container card (hidden until first commentary loads) |
| `commentary-overview-title` | Heading — set to "Agent Commentary" |
| `commentary-overview-text` | Body — typed character by character |
| `commentary-strategy-box` | Container card (hidden until strategy fires) |
| `commentary-strategy-title` | Heading — set to "Agent Commentary" |
| `commentary-strategy-text` | Body — typed character by character |

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| One of 4 overview instruments missing/corrupt CSV | Per-instrument try/except; fallback classification NEUTRAL; HTTP 200 with partial commentary; structlog warning |
| Strategy data unavailable | HTTP 200 with fallback sentence; structlog warning |
| JS `loadOverviewCommentary` throws | Catch shows `—`; never propagates to section loader |
| `Promise.allSettled` — commentary fails | Strategy grid renders regardless |
| Consecutive errors ≥ 3 | `log.warning("commentary.repeated_errors")` |
| DB audit write fails | Swallowed with `log.warning`; response still returned |

---

## Schemas (`src/rita/schemas/commentary.py`)

```python
class CommentaryRequest(BaseModel):
    app: str
    page: str
    instrument: str | None = None

class CommentaryResponse(BaseModel):
    app: str
    page: str
    commentary: str
    instruments_analyzed: list[str]
    latency_ms: float

class CommentaryLogCreate(BaseModel):
    id: str
    app: str
    page: str
    instrument: str | None
    latency_ms: float
    status: str
    commentary_preview: str
    timestamp: datetime
```

---

## Valid `app` Values

`rita` only (current). The dispatch table pattern supports extension: add `("ds","overview")` etc. when other apps need commentary.

---

## Future LLM Upgrade Path

Replace the body of `_build_narrative(data: dict) -> str` in `commentary.py`. The `data` dict is the structured context (classifications, rankings, recommendation fields). The function signature and call sites do not change.
