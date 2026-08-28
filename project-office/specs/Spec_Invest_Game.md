# RITA — Invest Game Specification

High-density reference for AI agents working on the Invest Game feature. Covers the standalone page, JS modules, backend agent chain, and mock data.

**IMPORTANT FOR AI AGENTS**: Read this before modifying any Invest Game code. Do not re-read the full HTML file (397 lines) — use this spec instead.

---

## 1. What the Invest Game Is

A standalone browser game where a human player competes against a RITA AI agent over real historical stock data. The game demonstrates AI-driven investment decision-making with a live compliance gate.

| Aspect | Detail |
|---|---|
| **Page** | `dashboard/investgame.html` (standalone, no sidebar/shell) |
| **JS modules** | `dashboard/js/invest-game/main.js`, `dashboard/js/invest-game/api.js` |
| **Backend router** | `src/rita/api/experience/invest_game.py` |
| **API prefix** | `/api/experience/invest-game` |
| **Mount** | `main.py:390` — `app.include_router(invest_game_router)` |
| **Auth** | None (Experience tier — no JWT required) |
| **Instruments** | ASML (EUR) · NVIDIA (USD) |
| **Data source** | `data/raw/ASML/asml_2001-2026.csv` · `data/raw/NVIDIA/nvda_daily_25yr_rounded.csv` |

---

## 2. Game Flow — 2 Practice Days + 7 Active Days

```
┌─────────────────────────────────────────────────────────────────────┐
│  SETUP        User picks instrument (ASML/NVIDIA) + date range     │
│               → POST /select-days → backend returns 9 days         │
├─────────────────────────────────────────────────────────────────────┤
│  WARMUP       Days 1–2: prices shown for orientation               │
│  (Practice)   No action buttons, no scoring, no budget consumed    │
├─────────────────────────────────────────────────────────────────────┤
│  ACTIVE       Days 3–9 (7 game days): sequential, one at a time   │
│  (Game)       User clicks BUY / HOLD / SELL                        │
│               → POST /run-day → backend agent chain → AI response  │
│               → P&L updated, compliance shown, next day revealed   │
├─────────────────────────────────────────────────────────────────────┤
│  DAY 9        Auto-close: if user is long → forced SELL;           │
│  (Final)      if flat → HOLD. Buttons disabled. 700ms delay.       │
├─────────────────────────────────────────────────────────────────────┤
│  GAME OVER    GET /{game_id}/result → run log written              │
│               Winner = higher net value (currently returns "draw") │
└─────────────────────────────────────────────────────────────────────┘
```

### Budget Rules

- Both players start with **€/$ 5,000** capital.
- Each player has exactly **3 buys** and **3 sells** across the 7 game days.
- Each trade invests/sells **1/3 of starting capital** (€/$1,667 tranche).
- Transaction cost: **0.1%** of trade value (`TRANSACTION_RATE = 0.001`).
- Capital gains tax: **30%** on gross profit per sell (`TAX_RATE = 0.30`).
- Net Value = cash + portfolio − cumulative costs − cumulative tax.

### Volatile Mode

A separate "Volatile Days" button loads pre-configured high-swing scenarios from hardcoded data (no server call). This mode uses `selectVolatileDays()` / `runDayVolatile()` from `api.js` and sets `gameState.volatileMode = true`. Available scenarios:

| Instrument | Scenario | Date range |
|---|---|---|
| ASML | July 2025 earnings shock | 2025-07-11 → 2025-07-23 |
| NVIDIA | Feb 2025 DeepSeek shock | 2025-02-06 → 2025-02-19 |

---

## 3. Files & Module Structure

### 3a. HTML — `dashboard/investgame.html` (397 lines)

Fully self-contained standalone page. No sidebar, no grid shell, no section-loader architecture. Inherits CSS variables, font stack (Epilogue / IBM Plex Mono / Instrument Serif), and topbar from other pages.

**Layout:** Single-column `<main class="game-main">` with `max-width: 1100px` centered.

| Section | HTML ID / class | Content |
|---|---|---|
| **Topbar** | `header.topbar` | RIIA logo, "Trial Invest Game" crumb, "Mock Mode" badge, nav links (Home, RITA, Ops) |
| **Winner Banner** | `#winner-banner` | Hidden until game ends; "Game Over" label + `#winner-badge` |
| **Row 1 — Controls** | `#row-controls` | Instrument pills (ASML/NVIDIA), date inputs, Select / Volatile / New Game buttons |
| **Selection Label** | `#selection-label` | Shows selected instrument, date range, day count after Select Days |
| **Day Action Bar** | `#day-action-bar` | Warmup day prices (Day 1, Day 2) + 3 arcade buttons (Buy / Hold / Sell) |
| **Row 2 — Performance** | `#row-performance` | P&L table: You vs AI (Cash, Portfolio, Costs, Tax, Net Value), Budget display, Progress bar |
| **Row 3 — Journal** | `#row-game-table` | 7-column game table (Days 3–9), rows: Price, Action, AI Action, Gate, Insight |

**Key DOM element IDs:**

| Pattern | Purpose |
|---|---|
| `pill-asml`, `pill-nvidia` | Instrument selector pills |
| `start-date`, `end-date` | Date range inputs |
| `btn-select-days`, `btn-volatile-days`, `btn-new-game` | Action buttons |
| `dbar-buy`, `dbar-hold`, `dbar-sell` | Arcade action buttons (`.arc-btn`) |
| `dbar-date-{1,2}`, `dbar-price-{1,2}` | Warmup day display |
| `user-cash`, `user-portfolio`, `user-costs`, `user-tax`, `user-net` | User P&L cells |
| `ai-cash`, `ai-portfolio`, `ai-costs`, `ai-tax`, `ai-net` | AI P&L cells |
| `budget-display`, `ai-budget-display` | Remaining buys/sells counters |
| `progress-fill`, `progress-label-text` | Progress bar + "Day X of 7" |
| `game-row-{3..9}` | Column headers (`.day-col`, `.active-col` on current) |
| `row{3..9}-price` | Price cells with % change arrow |
| `action-label-{3..9}` | User action badge (BUY/SELL/HOLD) |
| `ai-cell-{3..9}` | AI action cell (`.ai-buy`/`.ai-sell`/`.ai-hold`) |
| `comp-status-{3..9}`, `comp-rule-{3..9}` | Compliance gate badge + rule name |
| `comp-insight-{3..9}` | AI narrator insight text |
| `winner-banner`, `winner-badge` | End-game result display |

### 3b. JavaScript — `dashboard/js/invest-game/`

| File | Responsibility | Key exports / functions |
|---|---|---|
| **`api.js`** | All data I/O; mock data; volatile mock data | `MOCK_MODE` (const boolean), `selectDays(instrument, start, end)`, `runDay(game_id, day_index, action)`, `getResult(game_id)`, `selectVolatileDays(instrument)`, `runDayVolatile(instrument, day_index)` |
| **`main.js`** | Game state, DOM wiring, game loop, P&L calculation, reset | `gameState` (module-level), `initControls()`, `handleUserAction(n, action)`, `calculateDay(actor, action, closePrice)`, `renderPnLCards()`, `renderBudgetDisplay()`, `renderComplianceRow(n, result)`, `revealDay(n)`, `unlockRow(n)`, `showDayBar(n)`, `endGame()`, `resetGame()` |

**No shared module imports.** These modules are standalone — they do not import from `shared/api.js`, `shared/utils.js`, or `shared/charts.js`. No Chart.js usage.

### 3c. Backend — `src/rita/api/experience/invest_game.py`

Experience-tier router. No auth. In-memory session storage (`SESSION_DATA` dict keyed by game_id).

---

## 4. API Endpoints

### `POST /api/experience/invest-game/select-days`

Selects a random 9-day block from CSV data within the given date range.

**Request:**
```json
{ "instrument": "ASML", "start_date": "2025-01-01", "end_date": "2025-03-01" }
```

**Response (`SelectDaysResponse`):**
```json
{
  "game_id": "uuid",
  "instrument": "ASML",
  "currency": "EUR",
  "starting_capital": 5000.0,
  "warmup_days": [ { "date": "2025-01-06", "close": 678.50 }, ... ],
  "game_days": [ { "date": "2025-01-08", "close": 675.30 }, ... ]
}
```

**Validation:** Raises 422 if fewer than 9 trading days in range.

**CSV column normalization:** Both CSVs have different casing (`date` vs `Date`); loader applies `df.columns = [c.lower() for c in df.columns]`.

### `POST /api/experience/invest-game/run-day`

Runs the 6-agent chain for one game day.

**Request:**
```json
{ "game_id": "uuid", "day_index": 0, "user_action": "BUY" }
```

**Response (`RunDayResponse`):**
```json
{
  "ai_action": "BUY",
  "compliance_status": "pass",
  "compliance_rule": "Position Limit Check",
  "ai_insight": "Bull momentum confirmed at 82% — entering long at day close."
}
```

**Validation:** 404 if game_id not found. 400 if day_index outside 0–6. 409 if out-of-sequence (day_index must equal current `len(day_log)`).

### `GET /api/experience/invest-game/{game_id}/result`

Fetches result and triggers run log write to `data/agent-ops/runs/run-{YYYYMMDD-HHMM}.json`.

**Response (`ResultResponse`):**
```json
{
  "winner": "draw",
  "day_log": [ { "date": "...", "user_action": "BUY", "ai_action": "SELL", "compliance_status": "pass" }, ... ]
}
```

**Note:** Currently always returns `"winner": "draw"` — winner logic is computed client-side via net value comparison.

---

## 5. Backend Agent Chain (6 Agents)

Sequential pipeline operating on a `GameAgentState` TypedDict:

```
Context → Strategy → Probability → Portfolio Manager → Compliance Gate → Narrator
```

| Agent | Function | Input → Output |
|---|---|---|
| **Context** | `_game_context_agent` | close + prev_close → `regime` (Bull / Bear / High Volatility / Sideways) |
| **Strategy** | `_game_strategy_agent` | regime → `policy` (Trend Following / Capital Preservation / Risk Management / Mean Reversion) |
| **Probability** | `_game_probability_agent` | regime → `probability` (0.82 / 0.35 / 0.35 / 0.65) |
| **Portfolio Manager** | `_game_portfolio_manager_agent` | probability → `proposal.action` (>0.70 BUY, <0.40 SELL, else HOLD) |
| **Compliance Gate** | `_game_compliance_gate` | regime + probability → `compliance_status` + `compliance_rule` |
| **Narrator** | `_game_narrator_agent` | All state → `ai_insight` (natural language sentence) |

### Regime Classification Thresholds

| % Change (close vs prev) | Regime |
|---|---|
| > +2% | Bull Market |
| < −2% | Bear Market |
| abs > 3% (after Bull/Bear check) | High Volatility |
| Everything else | Sideways |

### Compliance Gate Rules

| Condition | Status | Rule Name |
|---|---|---|
| High Volatility AND probability < 0.40 | `flagged` | Extreme Volatility Threshold |
| All other cases | `pass` | Position Limit Check |

---

## 6. Game State Object (`gameState` in main.js)

```javascript
{
  gameId: null,                    // UUID from backend (or volatile mock ID)
  instrument: 'ASML',             // 'ASML' | 'NVIDIA'
  currency: 'EUR',                // 'EUR' | 'USD'
  startingCapital: 5000,          // Fixed starting capital
  warmupDays: [],                 // 2 DayEntry objects [{date, close}]
  gameDays: [],                   // 7 DayEntry objects [{date, close}]
  currentDayIndex: 0,             // 0–6 progress tracker
  started: false,                 // Game started flag
  volatileMode: false,            // Using volatile mock data
  buysLeft: 3,                    // User remaining buy actions
  sellsLeft: 3,                   // User remaining sell actions
  aiBuysLeft: 3,                  // AI remaining buy actions
  aiSellsLeft: 3,                 // AI remaining sell actions
  user: { /* ActorState */ },     // User player state
  ai:   { /* ActorState */ }      // AI player state
}
```

### ActorState Shape

```javascript
{
  position: 'flat',     // 'flat' | 'long'
  cash: 5000,           // Available cash
  shares: 0,            // Current shares held (fractional)
  entryPrice: 0,        // Weighted average entry price
  portfolio: 0,         // shares × closePrice
  cumCosts: 0,          // Cumulative transaction costs
  cumTax: 0,            // Cumulative capital gains tax
  netValue: 5000,       // cash + portfolio − cumCosts − cumTax
  prevNetValue: 5000    // Previous day's net value (unused in current UI)
}
```

---

## 7. P&L Calculation Logic (`calculateDay`)

Pure function modifying the actor state in-place based on action and close price.

### BUY

1. Tranche = startingCapital / 3 (€1,667).
2. Invest = min(tranche, actor.cash).
3. Transaction cost = invest × 0.001.
4. New shares = (invest − txCost) / closePrice.
5. Entry price = weighted average of existing + new shares.
6. Cash decremented, position set to `long`.

### SELL

1. Shares to sell = min(tranche / closePrice, actor.shares).
2. Proceeds = sharesToSell × closePrice.
3. Transaction cost = proceeds × 0.001.
4. Gross profit = sharesToSell × (closePrice − entryPrice).
5. Tax = grossProfit × 0.30 (only if profit > 0).
6. Cash += proceeds − txCost − tax.
7. If shares ≈ 0 → position set to `flat`.

### SELL_ALL (Day 9 auto-close)

Same as SELL but liquidates all remaining shares regardless of tranche size.

### HOLD

No state changes. Portfolio value still recalculated: `actor.portfolio = shares × closePrice`.

---

## 8. Mock Data (in `api.js`)

`MOCK_MODE` (boolean const, line 1) controls whether API calls hit the server or return hardcoded data.

### Standard Mock Scenarios

| Instrument | Game ID | Currency | Date range | Warmup days | Game days | Flagged day |
|---|---|---|---|---|---|---|
| ASML | `mock-game-001` | EUR | Jan 2025 | 2 | 7 | day_index 5 |

NVIDIA standard mock: derived at runtime — same MOCK_DAYS structure with currency override.

### Volatile Mock Scenarios (`MOCK_VOLATILE`)

Always used when volatile mode is active (regardless of `MOCK_MODE` flag).

| Instrument | Game ID | Scenario | Flagged day |
|---|---|---|---|
| ASML | `volatile-asml-001` | Earnings shock Jul 2025 | day_index 1 (Extreme Volatility Threshold) |
| NVIDIA | `volatile-nvidia-001` | DeepSeek shock Feb 2025 | day_index 3 (Consecutive loss gate — mock override) |

---

## 9. Run Log Writer

On `GET /{game_id}/result`, `_write_run_log()` serializes the game session to `data/agent-ops/runs/run-{YYYYMMDD-HHMM}.json`. This feeds the Ops Agent Builds dashboard.

**Payload structure:**
```json
{
  "run_id": "20260520-1430",
  "app": "invest-game",
  "request": "Invest game: ASML over 7 days",
  "overall_status": "pass" | "pass_with_warnings",
  "total_tokens_estimated": 3000,
  "duration_minutes": 5.2,
  "agents": [ { "role": "pm", ... }, { "role": "architect", ... }, ... ],
  "day_log": [ { "date": "...", "user_action": "...", "ai_action": "...", ... } ]
}
```

After writing the run file, triggers `aggregate_metrics.py` (if it exists) as a subprocess.

---

## 10. Invest Game App — Standalone Top-Level Page (Feature 33)

The Invest Game is also accessible via a dedicated standalone app (`investgame-app.html`) with its own sidebar navigation. This app aggregates game, learning, and agent content into a single cohesive experience.

| Aspect | Detail |
|---|---|
| **Page** | `dashboard/investgame-app.html` |
| **JS modules** | `dashboard/js/investgame-app/` (ES modules, imports from `shared/`) |
| **Tile** | First tile in Open Access zone on `index.html` |
| **Auth** | None — open access |
| **Sidebar pages** | 7 (see below) |

### Sidebar Navigation

| Nav item | Section id | Loader | Content |
|---|---|---|---|
| Invest Game | `sec-investgame` | _(none — static intro)_ | Welcome intro + link to play |
| Journey | `sec-journey` | iframe lazy-load | Investor journey flow |
| Concepts | `sec-concepts` | `loadConcepts()` | 8-tab agent workflow charts (NIFTY) |
| CRISP-DM | `sec-crisp-dm` | `loadCrispDm()` | 6-phase CRISP-DM methodology (ASML) |
| Agent Performance | `sec-agent-performance` | `loadAgentPerformance()` | Per-agent scorecards + KPIs |
| Agent Builds | `sec-agent-builds` | `loadAgentBuilds()` | Build runs, grounding, token estimates |
| Agent Panel | `sec-agent-panel` | `loadAgentPanel()` | 16-day ASML multi-agent simulation |

### JS Module Structure — `dashboard/js/investgame-app/`

| File | Responsibility |
|---|---|
| `main.js` | Entry point — registers loaders, exposes to `window`, init |
| `nav.js` | `show()`, `toggleSidebar()`, `registerLoader()` |
| `concepts.js` | 8 agent tabs with Chart.js (NIFTY data) |
| `crisp-dm.js` | 6 CRISP-DM phases with charts (ASML data) |
| `agent-performance.js` | RL agent scorecards + invocation timeline |
| `agent-builds.js` | Build history, grounding, token forecast |
| `agent-panel.js` | Step-through ASML simulation (16 days) |
| `api.js` | API helper (shared with `shared/api.js`) |
| `charts.js` | Chart helpers (shared with `shared/charts.js`) |
| `utils.js` | DOM helpers |

### Relationship to `rita.html`

The invest game section was **removed from `rita.html`** (Feature 33 Phase 6). The standalone `investgame.html` game page remains unchanged — the app's "Invest Game" nav links to it directly.

---

## 11. Related Files

| File | Purpose |
|---|---|
| `dashboard/investgame.html` | Production game page (v1) — standalone, no sidebar |
| `dashboard/investgame-app.html` | Invest Game App — top-level sidebar app (Feature 33) |
| `dashboard/investgame_v2.html` | UI v2 redesign (work in progress) |
| `dashboard/js/invest-game/main.js` | Game logic & state management (for `investgame.html`) |
| `dashboard/js/invest-game/api.js` | API client & mock data (for `investgame.html`) |
| `dashboard/js/investgame-app/` | ES module suite for `investgame-app.html` |
| `src/rita/api/experience/invest_game.py` | Backend router + agent chain |
| `data/raw/ASML/asml_2001-2026.csv` | ASML price history |
| `data/raw/NVIDIA/nvda_daily_25yr_rounded.csv` | NVIDIA price history |
| `data/agent-ops/runs/` | Run log output directory |
| `project-office/features/Jul/33 invest-game-app-elevation/` | Feature 33 plan + requirements |
| `mobileapp/investor-flow/v2/invest-dashboard.html` | Mobile variant (separate feature) |

---

## 12. Design Decisions & Constraints

1. **Standalone page** — `investgame.html` has no sidebar, no section-loader, no shared nav. Single `<main>` layout.
2. **No shared module imports** — `invest-game/` modules are self-contained; they do not import from `shared/api.js` or any other dashboard module.
3. **Invest Game App uses shared modules** — `investgame-app/` imports from `shared/api.js`, `shared/charts.js`, `shared/utils.js`, `shared/i18n.js`, `shared/dev-auth.js`.
4. **No Chart.js in game page** — Pure HTML table + DOM manipulation only in `investgame.html`.
5. **In-memory sessions** — `SESSION_DATA` dict lives in Python process memory. Sessions are lost on server restart. No DB persistence for game state.
6. **Client-side winner** — Backend returns `"winner": "draw"`; actual winner determination happens via net value comparison in the browser.
7. **Sequential day unlock** — Days reveal one at a time; `day_index` must match `len(day_log)` (409 error if out-of-sequence).
8. **Day 9 auto-close** — Final day automatically sells if long, holds if flat, with a 700ms animation delay.
9. **Volatile mode bypass** — Volatile scenarios use fully client-side mock data; no server calls even when `MOCK_MODE = false`.
