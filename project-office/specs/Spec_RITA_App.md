# RITA — Application Overview Specification

High-density reference for AI agents. Covers the full app architecture, request flows, and key design decisions.

---

## 1. What RITA Is

RITA (Risk Informed Trading Approach) is a Nifty 50 Double DQN reinforcement learning trading system and FnO portfolio manager. It consists of:

| Component | Description |
|---|---|
| **Backend API** | FastAPI + SQLite via SQLAlchemy 2.x. Stateless REST API. |
| **RITA Dashboard** | Vanilla JS ES modules — `rita.html`. Main trading & model view. |
| **FnO Dashboard** | `fno.html` — Options portfolio, Greeks, manoeuvres. |
| **Ops Dashboard** | `ops.html` — monitoring, test results, users, agent panel. **Feature 15 (2026-05-24):** Consolidated nav from 15 to 10 items. `sec-cicd`, `sec-alerts`, `sec-source-availability`, `sec-functional-kpis`, `sec-api-metrics` removed as standalone sections; KPI strip, alerts table, and API metrics absorbed into `sec-monitoring`; source availability absorbed into `sec-observability`. |
| **DS Dashboard** | `ds.html` (separate page) — Data science, training, portfolio backtest. |
| **Mobile PWA** | `riia-jun-release/mobileapp/index.html` — 10-screen single-file PWA. Served at `/mobileapp` via StaticFiles mount in `main.py`. |

---

## 2. Three-Tier API Architecture (ADR-001)

```
Tier 1: System         src/rita/api/v1/system/        Pure CRUD, one repo per router
Tier 2: Workflow       src/rita/api/v1/workflow/       Stateful ML jobs, JWT-protected
Tier 3: Experience     src/rita/api/experience/        UI-shaped read-only aggregation
```

**Special routers (outside the 3 tiers):**
- `api/v1/auth.py` — JWT token issue (`POST /auth/token`); Google OAuth login/callback. `GET /auth/google/login` accepts optional `state` query param (e.g. `state=fno`) which is appended to the Google OAuth URL. `GET /auth/google/callback` accepts optional `state`; maps `state=="fno"` → `/dashboard/fno.html?token=…`, otherwise → `/dashboard/index.html?token=…` (backward-compatible).
- `api/v1/users.py` — User management (`GET/POST /api/v1/users`)
- `api/v1/portfolio.py` — Cross-instrument portfolio + FnO endpoints
- `api/v1/workflow/chat.py` — Local intent classifier chat

**Application entrypoints in `main.py`:**
- `GET /` — UA-based conditional redirect: mobile UA (Android|iPhone|iPod|BlackBerry|IEMobile|Opera Mini) → `302 /mobile`; desktop → `302 /dashboard` (Feature 17 Phase 1; Phase 0 was desktop-only `302 /dashboard`)
- `/health` — liveness probe (model file check + data freshness + Sharpe trend)
- `/progress` — pipeline step statuses for dashboard progress bar
- `/reset` — stateless acknowledgement
- `/readyz` — readiness probe (SELECT 1 on DB)
- `/mobile` — serves `mobileapp/gateway.html` (Feature 17 Phase 0; registered before `/mobileapp` static mount)
- `/dashboard` — static file mount (catch-all)
- `/mobileapp` — static file mount for `riia-jun-release/mobileapp/` (added Feature 12B)

---

## 3. Full Endpoint Inventory

### System Tier — Pure CRUD

| Router file | Prefix | Tables |
|---|---|---|
| `system/positions.py` | `/api/v1/positions` | `positions` |
| `system/orders.py` | `/api/v1/orders` | `orders` |
| `system/snapshots.py` | `/api/v1/snapshots` | `snapshots` |
| `system/trades.py` | `/api/v1/trades` | `trades` |
| `system/alerts.py` | `/api/v1/alerts` | `alerts` |
| `system/audit.py` | `/api/v1/audit` | `audit_log` |
| `system/market_data.py` | `/api/v1/market-data` | `market_data_cache` |
| `system/config_overrides.py` | `/api/v1/config-overrides` | `config_overrides` |
| `system/instruments.py` | `/api/v1/instruments` | `instruments` |
| `system/market_signals.py` | `/api/v1/market-signals` | `market_data_cache` (computes indicators) |
| `system/training_runs.py` | `/api/v1/training-history`, `/api/v1/risk-timeline` (legacy), `/api/v1/split-dates`, `/api/v1/backtest-status/{id}`, `GET /api/v1/training-metrics?instrument=` | `training_runs`, `backtest_runs`, `backtest_results`. `/api/v1/training-metrics` returns per-episode TD loss + reward from `training_metrics` table — added `761e8ba` for DS Concepts page. |
| `system/drift.py` | `/api/v1/drift` | DB-backed DriftDetector |
| `system/data_prep.py` | `/api/v1/data-prep/*`, `/api/v1/test-results`, `/api/v1/shap-values`, `/api/v1/data-understanding` | File system |
| `system/client_error.py` | `POST /api/v1/client-error` | No auth; accepts JS error payload (type, message, stack, url, trace_id); returns 204; writes to `logs/client-errors.jsonl` |

### Workflow Tier — JWT-protected

| Router file | Endpoints |
|---|---|
| `workflow/train.py` | `POST /api/v1/train` |
| `workflow/backtest.py` | `POST /api/v1/backtest` |
| `workflow/evaluate.py` | `POST /api/v1/evaluate` |
| `workflow/pipeline.py` | `POST /api/v1/instrument/select`, `GET /api/v1/pipeline/progress`, `POST /api/v1/pipeline/quick-backtest` |
| `workflow/instrument_onboard.py` | `GET /api/v1/instrument/search?q=<str>` (no auth), `POST /api/v1/instrument/onboard` (no auth) |
| `workflow/chat.py` | `POST /api/v1/chat`, `POST /api/v1/chat/warmup` |
| `workflow/commentary.py` | `POST /api/v1/commentary` |
| `workflow/user_portfolio.py` | `POST /api/v1/user-portfolio` (201, JWT), `GET /api/v1/user-portfolio` (JWT) |

### Experience Tier — Read-only, no auth

| Router file | Prefix | Purpose |
|---|---|---|
| `experience/dashboard.py` | `/api/experience` | Legacy RITA/FnO/Ops aggregated payloads |
| `experience/fno.py` | `/api/experience/fno` | FnO aggregated payload |
| `experience/ops.py` | `/api/experience/ops` | Ops payload + metrics/summary + step-log + users + agent-builds |
| `experience/rita.py` | `/api/v1` | RITA performance, risk, trade, instrument-selection, geography overview |
| `experience/pipeline_wizard.py` | `/api/v1` | Goal/Market/Strategy wizard steps |
| `experience/ds.py` | `/api/experience/ds` | DS dashboard instruments + training history + split dates |
| `experience/agent_panel.py` | `/api/v1/agent-panel` | LangGraph 6-agent simulation for ASML |
| `experience/invest_game.py` | `/api/experience/invest-game` | User-vs-AI investing game — session management, agent chain per day, run log writer |
| `experience/users.py` | `/api/v1/experience/users` | User traffic KPIs and 30-day daily login breakdown — no PII |
| `experience/user_portfolio.py` | `/api/v1/experience` | Active user portfolio — read-only, JWT required per-route. `GET /api/v1/experience/user-portfolio` |
| `experience/optimal_allocation.py` | `/api/v1/experience/rita` | Feature 34 — Guided Basket Optimal Allocation via OR-Tools CP-SAT solver. `GET /api/v1/experience/rita/optimal-allocation` |

### RITA Experience Endpoints (`/api/v1/experience/rita`)

| Method | Path | Description | Auth |
|---|---|---|---|
| `GET` | `/api/v1/experience/rita/geography-overview` | Geography panels for Overview section and Portfolio Builder. Returns instruments grouped by region (India / US / EU / Other). Each `GeoInstrument` carries: `close`, `daily_return_pct`, `signal`, `return_1y_pct` (1Y simple return), `return_5y_pct` / `return_15y_pct` (CAGR via `investment_horizons.py`), `risk_score` (1–5 vol bucket), `sector` (static map), `horizons[]` (list of qualifying horizon keys from `investment_horizons.py`). Used by Market Signals geo panel tiles and `portfolio-builder.js` (Feature 28). | No |
| `GET` | `/api/v1/experience/rita/backtest-daily` | Daily backtest results for charting — date, portfolio_value, benchmark_value, allocation, close_price. Query: `instrument` (optional, F34 P2.5 — default None = active instrument, unchanged behaviour for existing consumers) | No |
| `GET` | `/api/v1/experience/rita/model-eval-summary` | F34 P2.5 — per-instrument model evaluation summary. Returns `ModelEvalSummaryResponse` (`val_window`, `backtest_window`, `gate_rule`, `rows[]` of `ModelEvalSummaryRow`: `instrument`, `last_trained`, `timesteps`, `val_sharpe`, `val_mdd_pct`, `val_cagr_pct`, `backtest_sharpe`, `backtest_mdd_pct`, `backtest_return_pct`, `trade_count`, `gate_pass` [bool\|null — null when `has_history` false], `source`, `round`, `has_history`). One row per `config/instruments/*.yaml` id (via `list_instrument_ids()`), latest round from `models/<INST>/training_history.csv` (via `training_tracker.load_latest_round()`). Gate computed server-side (`backtest_sharpe >= 1.0 and \|backtest_mdd_pct\| <= 10`); rows sorted backtest_sharpe desc, nulls last. Read-only, no commit. | No |
| `GET` | `/api/v1/experience/rita/risk-timeline` | Risk timeline from latest backtest — drawdowns, VaR, vol, regime. Query: phase, instrument | No |
| `GET` | `/api/v1/experience/rita/training-history` | Training run history — all KPIs newest-first. Query: instrument | No |
| `GET` | `/api/v1/experience/rita/strategy-comparison` | 5-strategy OHLCV performance comparison (Buy&Hold, Value, Momentum, Swing, S/R). Query: `instrument` (default: active), `year` (2024/2025, default 2025). Returns `StrategyComparisonResponse` with equity curves, summary metrics, dates. LRU-cached per (instrument, year). | No |
| `GET` | `/api/v1/experience/rita/agent-performance` | Feature 32 — per-agent KPI summary for the 7 investment-workflow agents (Financial Goal, Sentiment Analyst, Technical Analyst, Strategy Analyst, Scenario Analyst, Execution Analyst, Outcome Analyst). Returns `AgentPerformanceSummaryResponse` (`agents[]` of `AgentKpi`: `agent_name`, `gap_status`, `invocation_count_30d`, `outcome_match_rate` [null until backfill], `trend_vs_prior_30d` [null when prior window empty]). Always exactly 7 agents (missing → count 0, rates null). Read-only, no commit. Powers the `sec-agent-performance` section. Distinct from the Ops Agent Builds page. | No |
| `GET` | `/api/v1/experience/rita/optimal-allocation` | Feature 34 Phase 1 — Guided Basket Optimal Allocation. Query param: `horizon` (required, Literal["short_term", "medium_term", "long_term"]). Returns `OptimalAllocationResponse` (`horizon`, `instrument_count`, `solver_status` ("OPTIMAL"/"FEASIBLE"/"INFEASIBLE"/"SINGLE_INSTRUMENT"/"NO_INSTRUMENTS"/"ERROR"), `estimated_sharpe`, `estimated_mdd_pct`, `allocations[]` of `AllocationItem` (`instrument_name`, `ticker`, `allocation_pct`, `sharpe`, `mdd_pct`, `metric_source` ("model"/"proxy"))). Uses OR-Tools CP-SAT solver with constraints: budget=100, min=5%, max=60%, Sharpe>=1.0, MDD<=10%. Read-only, no commit. Router file: `experience/optimal_allocation.py`. **Frontend consumer (Phase 2):** `portfolio-builder.js:_applyPreset()` calls this endpoint on horizon selection; renders optimized allocations in guided basket draft list with per-instrument Sharpe/MDD and mode badge. Falls back to equal-weight on error or non-OPTIMAL status. | No |

### Ops Experience Endpoints (`/api/experience/ops`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/experience/ops/` | Aggregated Ops payload (training runs + backtest runs + recent audit) |
| `GET` | `/api/experience/ops/metrics/summary` | API request counts, latency, error rate, pipeline stats |
| `GET` | `/api/experience/ops/step-log` | Pipeline step log entries |
| `GET` | `/api/experience/ops/users` | User list for Ops view |
| `GET` | `/api/experience/ops/agent-builds` | Returns agent build run history + aggregated metrics from DB. `AgentBuildRunOut` includes `human_score_csat: Optional[float]` (from run JSON `human_score.csat`). `AgentOut` includes `actual_tokens: Optional[dict]` (input/output/cache/total from Claude API). `SkillVersion.recent_commits` is `list[dict]` with `{hash, message}` objects. |
| `GET` | `/api/experience/ops/token-forecast` | Pre-run token budget estimate — query params: `feature_type`, `files_to_change`, `new_endpoint_or_model`, `frontend_scope`, `integration_type`. Returns `TokenForecastResponse` (complexity, per_role, total_forecast, confidence, basis_runs). Auth required. |
| `GET` | `/api/experience/ops/api-metrics` | Per-endpoint call count, p50/p95 latency, error rate from api_call_log. Query params: `limit` (default 200), `method`, `path_prefix`. Returns `ApiMetricsResponse(items: list[ApiMetricsRow])`. No auth. |
| `GET` | `/api/experience/ops/functional-kpis` | KPI time-series for training success rate, error rates, p95 latency (last 24h hourly buckets). Query param: `hours` (default 24, 1–168). Returns `FunctionalKPIsResponse`. No auth. |
| `GET` | `/api/experience/ops/drift` | Model health and drift checks — Experience-tier wrapper for DriftDetector. Returns `{ summary: { overall }, checks: { sharpe_drift, return_degradation, data_freshness, pipeline_health, constraint_breach } }`. Replaces direct JS call to system-tier `/api/v1/drift`. No auth. |

### Users Experience Endpoints (`/api/v1/experience/users`)

| Method | Path | Description | Auth |
|---|---|---|---|
| `GET` | `/api/v1/experience/users/traffic` | Returns aggregated login KPIs and 30-day daily breakdown — no PII. `UserTrafficResponse` with `summary` (total_users, active_today, active_this_week, active_this_month, total_logins_all_time) and `daily` list (date, unique_users, total_logins, new_registrations) | JWT |

### User Portfolio Endpoints (Feature 26)

| Method | Path | Description | Auth | Router file |
|---|---|---|---|---|
| `GET` | `/api/v1/experience/user-portfolio` | Read active portfolio for authenticated user — returns `UserPortfolioOut` with `portfolio_id`, `name`, `updated_at`, `holdings` (list of `{instrument_id, allocation_pct, shares?, cash_eur?}`), `total_value_eur`. 404 if none saved. | JWT | `experience/user_portfolio.py` |
| `GET` | `/api/v1/user-portfolio` | Read active portfolio (workflow tier alias). | JWT | `workflow/user_portfolio.py` |
| `POST` | `/api/v1/user-portfolio` | Save portfolio — body: `{name: str, holdings: [{instrument_id, allocation_pct, shares?, cash_eur?}], total_value_eur?}`. `shares` (int) = whole-number share count; `cash_eur` (float) = leftover cash after buying whole shares — both computed by `portfolio-builder.js` from `total_value_eur × allocation_pct / close`. Deactivates previous, inserts new. Returns `UserPortfolioOut` (201). | JWT | `workflow/user_portfolio.py` |
| `GET` | `/api/v1/experience/fno/portfolio-hedge` | Hedge wizard data — BS put + call pricing per holding at given coverage. Params: `coverage` 0–100 (default 50), `total_value_eur: float \| None` (optional). `duration` param removed (F29 Phase 0) — hardcoded to 1y (`t_months = 12.0`). Returns `PortfolioHedgeResponse`: holdings with `cost_pct` (put premium), `call_sell_cost_pct` (call income), `ann_vol_pct`, `risk_score`, `strike_pct`, `strike_label`, `protected_pct`, `duration` (always `"1y"`); plus `aggregate` and `coverage`. Used by 4-tab hedge wizard (Discover/Selection/Allocation/Hedge) in FnO. | JWT | `experience/portfolio_hedge.py` |
| `GET` | `/api/v1/experience/fno/hedge-plan` | Read the authenticated user's saved hedge plan. Returns `HedgePlanOut`: `key_id` (str), `hedged_ids` (list[str]), `coverage` (int 0–100), `scenario_tab` (str), `duration` (always `"1y"`), `updated_at` (datetime). 404 if no portfolio key or no saved plan exists — JS uses defaults silently. Added F29 Phase 1. | JWT | `experience/hedge_plan.py` |
| `PUT` | `/api/v1/experience/fno/hedge-plan` | Upsert the authenticated user's hedge plan. Body: `hedged_ids` (list[str]), `coverage` (int 0–100), `scenario_tab` (str). Returns `HedgePlanOut`. Called by `portfolio-hedge.js` with 400ms debounce on every user change. Added F29 Phase 1. | JWT | `experience/hedge_plan.py` |
| `GET` | `/api/v1/experience/fno/portfolio-analytics?mode=real\|mock` | Unified FnO dashboard analytics payload — positions, greeks, net_greeks, net_delta, scenario_levels, payoff (21-pt grid), stress (5 events), hedge_quality (HQS per instrument), market OHLCV, closed_positions, realized_pnl, margin. mode=mock: 200 no auth (demo data); mode=real: JWT required → 401 without token, 404 if no portfolio. Greeks derived from saved hedge plan; if no plan: delta=1.0, theta/vega/gamma=0. Added F30 Phase 1. **F30 Phase 2 JS consumer:** `app-init.js:initApp(mode)` — single fetch replaces prior multi-call chain; Real/Mock toggle in sidebar (`#analytics-mode-chk`) wired via `window.toggleAnalyticsMode`. **F30 Phase 3 JS consumers:** (a) `my-portfolio.js:renderOverviewFromState()` — instrument selector pills (ASML default) + positions grid filtered by selected instrument; (b) `hedge.js:renderPortfolioHedgeRadar()` — HQS counts + alert banner + instrument-level table; (c) `payoff.js:renderPayoffChart()` — portfolio-mode branch renders portfolio+hedged datasets on single canvas; (d) `stress.js:renderAnalyticsStress()` — historical event stress table below scenario cards; (e) `greeks.js:renderGreeksTable()` — uses `g.und`+`g.hedge_type` (was `g.full`), `g.ann_vol_pct` (was `g.iv`); (f) `manoeuvre.js:manLots()` — uses `p.full ?? p.instrument ?? p.und` for lotKey. `app-init.js:_normScenarioLevels()` normalises `{target,sl}` shape to `{bull:{target,sl},bear:{target:sl,sl:target}}` before storing in `state.scenarioLevels`. | JWT (mode=real only) | `experience/portfolio_analytics.py` |

**Frontend RITA (Phase 3 + UI update — 2026-05-30):** `dashboard/js/rita/my-portfolio.js` — `loadMyPortfolio()` + `savePortfolio()`. Section `sec-my-portfolio` in `rita.html` under Phase 05 — Portfolio nav (pink). Allocation builder uses `kpi kpi-sm` tiles. After save: chips + 2025 performance chart. See Phase 05 frontend note in full endpoint table below.

### Instrument Workflow Endpoints (`/api/v1/instrument` via `workflow/instrument_onboard.py`)

| Method | Path | Query params | Request body | Response | Description |
|---|---|---|---|---|---|
| `GET` | `/api/v1/instrument/search` | `q: string` | — | `list[InstrumentSearchResult]` | Instrument ticker search via yfinance |
| `POST` | `/api/v1/instrument/onboard` | — | `ticker, name, exchange, currency, country_code, lot_size` | `InstrumentOnboardResponse` | Full onboarding pipeline |
| `POST` | `/api/v1/instrument/refresh-all` | — | — | `RefreshAllResponse` | Refresh all instruments' price data from yfinance (Feature 16) |

### RITA Experience Endpoints (`/api/experience/rita` and `/api/v1` via `experience/rita.py`)

| Method | Path | Description | Router file |
|---|---|---|---|
| `GET` | `/api/experience/rita/technical-commentary` | Technical commentary + signal summary for active instrument | `rita.py` |
| `GET` | `/api/v1/experience/rita/portfolio-performance` | Custom portfolio 2025 daily performance index. Query params: `holdings` (e.g. `NIFTY:40,NVIDIA:30,ASML:30`) and `year` (default 2025). Loads each instrument's OHLCV CSV via `load_instrument_data`, normalises to base 100 on first trading day, computes daily weighted portfolio value across union of all trading dates (forward-filled). Returns `{dates, values, instruments}`. No auth required. | `rita.py` |

### Invest Game Endpoints (`/api/experience/invest-game`)

| Method | Path | Description | Response fields |
|---|---|---|---|
| `POST` | `/select-days` | Start a new game: pick instrument + date range; returns 12-day slice (2 warm-up + 10 active) | `game_id`, `instrument`, `currency`, `starting_capital`, `warmup_days[]`, `game_days[]` |
| `POST` | `/run-day` | Submit user action for one active day; runs 5-agent chain for AI action | `ai_action`, `compliance_status`, `compliance_rule`, `ai_insight` |
| `GET` | `/{game_id}/result` | Finalise game: writes run log JSON + regenerates metrics.json | `winner`, `day_log[]` |

**Request body — `/select-days`:** `{ instrument: "ASML"|"NVIDIA", start_date: "YYYY-MM-DD", end_date: "YYYY-MM-DD" }`
**Request body — `/run-day`:** `{ game_id: string, day_index: int (0–9), user_action: "BUY"|"SELL"|"HOLD" }`
**Session storage:** in-process `SESSION_DATA` dict keyed by `game_id` (UUID). Lost on server restart.
**AI agent chain:** Context → Strategy → Probability → Portfolio Manager → Compliance Gate → Narrator (5 pure-function agents, no async I/O).
**Run log output:** `riia-jun-release/data/agent-ops/runs/run-{YYYYMMDD-HHMM}.json` — auto-regenerates `metrics.json` via `aggregate_metrics.py` after game result is fetched.
**Data sources:** `data/raw/ASML/asml_2001-2026.csv` (col: `date`) and `data/raw/NVIDIA/nvda_daily_25yr_rounded.csv` (col: `Date`) — both normalised to lowercase at load time.

#### Invest Game — Frontend Files

Two UIs exist for the same backend. Both use `MOCK_MODE` flag to bypass the real API during development.

| File | Path | UX Paradigm | Status |
|---|---|---|---|
| `investgame.html` | `dashboard/investgame.html` | **Spreadsheet** — days as columns, all visible at once; inline Buy/Sell/Hold text buttons per column; P&L as a compact table; JS in external `dashboard/js/invest-game/main.js` | Production-ready; no mobile breakpoints |
| `investgame_v2.html` | `dashboard/investgame_v2.html` | **Arcade** — one day revealed at a time; large round 3D BUY/HOLD/SELL buttons; journey track node rail; You-vs-AI score cards; reveal bar after each action; game log builds as rows; fully self-contained HTML | Committed 2026-05-20; `MOCK_MODE=true` pending review; has ≤640px mobile breakpoints |

**To activate v2 live backend:** set `MOCK_MODE = false` in `investgame_v2.html` line ~373.
**Nav link:** no link to v2 from main dashboard yet — access directly at `/dashboard/investgame_v2.html`.

#### Invest Game App — Standalone Top-Level Page (Feature 33)

| File | Path | Description | Status |
|---|---|---|---|
| `investgame-app.html` | `dashboard/investgame-app.html` | **Standalone app** — 7-page sidebar: Play Game (intro + link to investgame.html), Journey (iframe of `/journey` — investor journey flow, formerly "Onboarding"), Concepts (8-tab agent workflow), CRISP-DM, Agent Performance, Agent Builds, Agent Panel. Same :root CSS as RITA. No auth required — open access. | Added 2026-07-04; Journey added 2026-07-05 |

**JS modules:** `dashboard/js/investgame-app/` — see Spec_JS_Code.md Section 5b.
**Index tile:** Listed as the first tile in the Open Access zone on `index.html`.
**Navigation removed from RITA:** The `data-s="investgame"` nav item was removed from `rita.html` sidebar — Invest Game is now accessed only via `investgame-app.html`.

### 6. `equity-scenarios.html` (Equity Scenarios — Standalone FnO-Adjacent Page)
- **Purpose**: Stop-loss and target tracker for equity holdings. Shows urgency-sorted instrument cards with price range bars, P&L metrics, trade analysis chips, and action recommendations. Navigated to from `fno.html` sidebar.
- **Data layer**: Static JSON files — `dashboard/data/scenarios/alerts.json`, `dashboard/data/scenarios/portfolio.json`, `dashboard/data/scenarios/tradebook.json`. No backend REST endpoint (future migration: Portfolio-tier endpoint merging the 3 JSON shapes).
- **JS module**: `dashboard/js/scenarios/equity-scenarios.js` — standalone self-contained module; no imports from fno/ or shared/.
- **Key DOM elements**: `kpi-invested`, `kpi-value`, `kpi-pnl`, `kpi-pnl-pct`, `kpi-status`, `kpi-status-sub`, `alert-strip`, `scenarios-grid`, `triggered-grid`, `last-updated`

### Portfolio Tier — No auth, heavy computation

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/portfolio/overview` | GET | Cross-instrument normalised prices + correlation matrix |
| `/api/v1/portfolio/backtest` | POST | Multi-instrument DDQN portfolio backtest with EUR allocations |
| `/api/v1/portfolio/positions?mode=paper\|live` | GET | Paper or live broker positions |
| `/api/v1/portfolio/summary` | GET | KPI cards + market prices for all 4 instruments |
| `/api/v1/portfolio/price-history?periods=N` | GET | Recent NIFTY OHLCV for Risk-Reward chart |
| `/api/v1/portfolio/hedge-history` | GET | Historical hedge suggestions from manoeuvres |
| `/api/v1/portfolio/man-groups` | GET | Manoeuvre group list aggregated from portfolio table |
| `/api/v1/portfolio/man-snapshot` | POST | Record snapshot when manoeuvre applied |
| `/api/v1/portfolio/adjust-position-action` | POST | Record manoeuvre action from FnO panel — body: date, month, action, lot_key, from_group, to_group, nifty_spot, banknifty_spot. Returns {status, manoeuvre_id} |
| `/api/v1/portfolio/man-pnl-history` | GET | Daily P&L history for Manoeuvre chart |
| `/api/v1/portfolio/man-daily-status` | GET | Today's manoeuvre count and last manoeuvre record |
| `/api/v1/portfolio/man-daily-snapshot` | POST | Record daily portfolio snapshot |
| `POST /api/v1/portfolio/equity-hedge-scenarios` | No | Portfolio tier | ASML equity portfolio performance + Black-Scholes covered call and protective put hedge scenarios with payoff curves. Body: instrument, n_shares, start_date, end_date. |

### User Portfolio Endpoints (Feature 26)

| Method | Path | Description | Auth | Router file |
|---|---|---|---|---|
| `POST` | `/api/v1/user-portfolio` | Save (create new version of) the authenticated user's allocation portfolio. Body: `{name, holdings: [{instrument_id, allocation_pct, shares?, cash_eur?}], total_value_eur?}`. `shares` (int) + `cash_eur` (float) are optional — populated by `portfolio-builder.js` when total EUR is set. Returns `UserPortfolioOut`. | JWT | `workflow/user_portfolio.py` |
| `GET` | `/api/v1/user-portfolio` | Return most recent active portfolio for authenticated user. 404 if none saved. | JWT | `workflow/user_portfolio.py` |
| `GET` | `/api/v1/experience/user-portfolio` | Read active portfolio for authenticated user — returns `UserPortfolioOut` with `portfolio_id`, `name`, `updated_at`, `holdings` (list of `{instrument_id, allocation_pct, shares?, cash_eur?}`), `total_value_eur`. 404 if none saved. | JWT | `experience/user_portfolio.py` |

**Frontend RITA (Phase 3 + UI update — 2026-05-30):** `dashboard/js/rita/my-portfolio.js` — `loadMyPortfolio()` + `savePortfolio()`. Section `sec-my-portfolio` in `rita.html` under **Phase 05 — Portfolio** nav. Auth: calls `ensureDevToken()` on localhost before save, Google OAuth on production.

**Frontend FnO (Phase 4 + UI update — 2026-05-30):** `dashboard/js/fno/my-portfolio.js` — `loadFnoMyPortfolio()`. Read-only portfolio overview with KPI strip, allocation doughnut, hedge status card, and 6-column holdings table. Empty state links to RITA builder. Token ingestion (`?token=` → sessionStorage) in `fno/main.js`.

**Shares + cash (post-F28):** `HoldingItem` schema carries optional `shares: int | None` and `cash_eur: float | None`. `portfolio-builder.js` computes `shares = floor(totalEur × allocPct/100 / closePrice)` and `cash_eur = allocEur − shares × closePrice` using the `close` field from the geography-overview response, then includes them in the POST body. FnO consumers (`app-init.js`, `equity_hedge.js`, `portfolio-hedge.js`) use `shares` directly for whole-number hedge calculations.

**Local dev auth bypass:** `shared/dev-auth.js:ensureDevToken()` auto-mints a JWT on localhost via `POST /auth/token {username:'rita-dev', password:'rita-dev'}` — no Google OAuth needed. Called at boot by RITA `main.js` and FnO `main.js`; also called by `portfolio-builder.js` and `my-portfolio.js` before any write. Production is unaffected (hostname check).

**Demo / Live auth toggle (dashboard home, `index.html`):** the home-page switch selects **Live** (default, `checked`) or **Demo**. The tile-click handler on `.protected-route` tiles routes as follows: on **localhost** it navigates directly (destination page mints its own dev token); in **Live** mode it requires an `auth_token` and otherwise redirects to `/auth/google/login`; in **Demo** mode it mints a JWT for the shared demo account via `POST /auth/token {username:'webmaster@ravionics.nl', password:'rita-dev'}`, stores it, then navigates. The demo user is seeded in the `users` table (migration `20260611_seed_demo_user`) with all access flags (`can_assist_research`, `can_create_portfolio`, `can_review_portfolio`, `can_access_ops`) = True, so Demo mode exercises every function — including the Ops console — and is a shared account (all demo visitors read/write the same portfolio). Its email is a frontend config constant only; no identity is hardcoded server-side.

---

## 4. Key Request Flows

### Flow 1: Instrument Tab Click → Metrics

Entry: `rita.html` instrument selector buttons (NIFTY/BANKNIFTY/ASML/NVIDIA) in `sec-market-signals` (the landing "Overview" page) call `onclick="selectInstrumentTab('NIFTY')`

Call chain (`main.js`):
```
selectInstrumentTab(id)
  1. POST /api/v1/instrument/select      → sets active_instrument_id in config_overrides table
  2. GET  /api/v1/instrument/active      → topbar pill (name, flag)
  3. GET  /api/v1/performance-summary    → KPI metrics cards (checks _run_instrument_id vs _active_instrument_id)
  4. GET  /health                        → model status card
  5. GET  /api/experience/ops/drift      → alert strip
  6. GET  /progress                      → pipeline step bar
```

**Stale check in `health.js:loadPerfSummary()`:**
```js
const stale = d._run_instrument_id !== d._active_instrument_id;
if (stale) { /* blank all KPIs, show "Run pipeline" */ return; }
```

### Flow 2: Agent Panel Step (HITL flow)

Entry: `rita.html` `#ap-run-btn` → `window.agentPanelStep()`

```
agentPanelStep()
  1. POST /api/v1/agent-panel/run-day { day_index, thread_id }
     → Backend: LangGraph graph.invoke(initial_state, config)
     → Nodes: context → strategy → probability → portfolio_manager → compliance → narrator
  2. Update chart (ASML price + cash), widgets (regime/policy/probability/proposal/compliance)
  3. Append audit row to #ap-audit-body
  4. Save to localStorage('riia_agent_history')
  5. If proposal.action == 'BUY' → show HITL panel (#ap-hitl-panel) and pause
     → approveAgentProposal() / rejectAgentProposal() → re-enable Run Day button
  6. If dayIndex >= 16 → show final summary narrative
```

### Flow 3: Pipeline Train

Entry: `export.js:runFullPipeline()` → `POST /api/v1/train` (JWT required)

```
WorkflowService.start_training(instrument)
  → Creates TrainingRun record (status=pending) in DB
  → Spawns daemon thread: ml_dispatch._run_training()
     → train_best_of_n(env, n_seeds=3) → best model by backtest Sharpe
     → Writes: models/{instrument}/pipeline-{id}.zip
     → Writes: models/{instrument}/training_history.csv (TrainingTracker)
     → Updates TrainingRun: status=complete, all phase metrics (train/val/backtest Sharpe, MDD, return)
```

### Flow 4: Portfolio Summary (Mobile + FnO)

Entry: Mobile `fetchPortfolioSummary()` or FnO `loadFnoDashboard()`

```
GET /api/v1/portfolio/summary
  → PortfolioService.list_all()     (portfolio table)
  → MarketDataCacheRepository.read_all()  (latest close per instrument)
  → Returns: total_pnl, lot_count, nifty_spot, banknifty_spot, asml_close, nvidia_close, market{NIFTY, BANKNIFTY, ASML, NVIDIA}
```

---

## 5. Middleware & Infrastructure

| Layer | Implementation | Note |
|---|---|---|
| CORS | `CORSMiddleware` from `settings.security.cors_origins` | Configured per env |
| Trace ID | `TraceIDMiddleware` — injects X-Request-ID ContextVar | All logs bind trace_id |
| Rate limiting | `slowapi` — 60/min default, 10/min on `/auth/token` | `limiter` in `limiter.py` |
| Logging | `structlog` JSON format, configured in `logging_config.py` | Binds trace_id per request |
| Metrics | `prometheus-fastapi-instrumentator` — auto-instruments all routes | `/metrics` endpoint |
| Exception handlers | 4 handlers: HTTPException, RequestValidationError, RepositoryValidationError, Exception→500 | Consistent `{detail, trace_id}` shape |

---

## 6. Database Tables (17 ORM models)

| Table | Model file | Category |
|---|---|---|
| `instruments` | `models/instrument.py` | Seeded (4 rows) |
| `market_data_cache` | `models/market_data.py` | Seeded (all 4 instruments, 2025-2026) |
| `paper_positions` | `models/paper_positions.py` | Seeded (2 ASML paper options) |
| `training_runs` | `models/training.py` | Pipeline history — NOT recoverable |
| `backtest_runs` | `models/backtest.py` | Pipeline history — NOT recoverable |
| `backtest_results` | `models/backtest.py` | Pipeline history — NOT recoverable |
| `risk_timeline` | `models/risk.py` | Pipeline history — NOT recoverable |
| `positions` | `models/positions.py` | FnO trading records |
| `orders` | `models/orders.py` | FnO trading records |
| `snapshots` | `models/snapshots.py` | FnO trading records |
| `trades` | `models/trades.py` | FnO trading records |
| `manoeuvres` | `models/manoeuvres.py` | FnO trading records |
| `portfolio` | `models/portfolio.py` | FnO portfolio snapshots |
| `model_registry` | `models/model_registry.py` | Model version tracking |
| `config_overrides` | `models/config_overrides.py` | Runtime config (incl. active_instrument_id) |
| `audit_log` | `models/audit.py` | API audit trail |
| `alerts` | `models/alerts.py` | Chat/query confidence log |
| `users` | `models/user.py` | User accounts |

---

## 7. Core Business Logic (`src/rita/core/`)

| File | Key classes/functions | Purpose |
|---|---|---|
| `data_loader.py` | `load_nifty_csv(path)`, `load_instrument_data(id)`, `find_instrument_csv(id)` | Canonical OHLCV loader — handles all date formats |
| `trading_env.py` | `RITAEnv`, `train_best_of_n(env, n_seeds)` | DoubleDQN gym environment + multi-seed trainer |
| `ml_dispatch.py` | `_run_training(run_id, instrument, n_seeds)` | Daemon thread — full train→validate→backtest cycle |
| `backtest_dispatch.py` | `run_episode(model, df)` | Real backtest engine (replaced stub in Sprint 6) |
| `training_tracker.py` | `TrainingTracker` | Records per-step metrics to training_history.csv |
| `performance.py` | `build_performance_feedback()`, `build_portfolio_comparison()`, `simulate_stress_scenarios()`, `compute_all_metrics()` | Performance analytics and stress testing |
| `portfolio_engine.py` | `portfolio_overview()`, `portfolio_backtest()` | Cross-instrument portfolio backtesting |
| `drift_detector.py` | `DriftDetector` — 5 checks | DB-backed model drift detection |
| `classifier.py` | `classify_intent(query)`, `dispatch(intent, db)` | Local SentenceTransformer intent classifier (20 intents) |
| `technical_analyzer.py` | `calculate_indicators(df)`, `get_market_summary()`, `get_sentiment_score()` | RSI, MACD, BB, EMA, ATR computation |
| `strategy_engine.py` | `get_allocation_recommendation(market_summary, risk_tolerance)` | Signal-based allocation recommender |
| `data_understanding.py` | `find_instrument_csv(id)` | Resolves correct CSV path per instrument |

---

## 8. Services (`src/rita/services/`)

| Class | Constructor | Key methods |
|---|---|---|
| `WorkflowService` | `__init__(db: Session)` | `start_training(instrument)`, `list_runs()` |
| `BacktestService` | `__init__(db: Session)` | `start_backtest(params)`, `list_runs()` |
| `ManoeuvreService` | `__init__(db: Session)` | `record(manoeuvre)`, `list_all()`, `list_recent(n)`, `list_by_date(date)` |
| `PortfolioService` | `__init__(db: Session)` | `record(portfolio)`, `list_all()`, `get_by_date(date)`, `get_latest()` |
| `UserPortfolioService` | `__init__(db: Session)` | `save(user_id, holdings, name) -> UserPortfolioOut`, `get(user_id) -> UserPortfolioOut \| None` |

---

## 9. Agent Panel — LangGraph Multi-Agent System

**File:** `src/rita/api/experience/agent_panel.py`

### AgentState (TypedDict)

```python
class AgentState(TypedDict):
    date: str                     # ISO date for the current trading day
    price_data: dict              # {open, high, low, close, volume}
    regime: str                   # "Bull Trending"|"Bear Trending"|"High Volatility"|"Quiet Mean-Reverting"
    policy: str                   # Dynamic stop/target policy string
    probability: float            # Historical success rate for regime [0,1]
    proposal: dict                # {action: "BUY"|"WAIT", size: "20%"|"0%"}
    compliance_status: str        # "PASSED" | "FLAGGED: ..."
    logs: List[str]               # Agent log strings (one per node)
    hitl_status: str              # "pending" | "approved" | "rejected"
    cash: float                   # Available cash in EUR
    holdings: float               # Shares held
    portfolio_value: float        # cash + holdings * price
    portfolio_history: List[float]
    cash_history: List[float]
    collaboration_insight: str    # Narrator's 2-sentence synthesis
```

### Agent Nodes

| Node | Function | Logic |
|---|---|---|
| `context` | `context_agent(state)` | Computes % change from prev day → regime classification (±1%/±3% thresholds) |
| `strategy` | `strategy_agent(state)` | Maps regime → stop/target policy string |
| `probability` | `probability_agent(state)` | Maps regime → historical success probability (0.35/0.65/0.82) |
| `portfolio_manager` | `portfolio_manager_agent(state)` | If prob > 0.70 and cash > 100 → BUY 20%; else WAIT. Updates portfolio_value. |
| `compliance` | `compliance_gate(state)` | If (high-low)/open > 0.05 → FLAGGED (extreme intraday volatility) |
| `narrator` | `narrator_agent(state)` | Generates 2-sentence collaboration insight via `_build_narrator_insight()` |

### Graph Flow
```
context → strategy → probability → portfolio_manager → compliance → narrator → END
```

### Endpoints
- `POST /api/v1/agent-panel/run-day` — `StepRequest{day_index, thread_id}` → runs one day through LangGraph
- `GET /api/v1/agent-panel/plot/{day_index}` — returns base64-encoded matplotlib PNG of ASML price up to day_index

### Session State
- `SESSION_DATA: dict[thread_id, {cash, holdings, portfolio_value}]` — persists portfolio across day steps within a thread
- `MemorySaver` checkpointer for LangGraph conversation memory

---

## 10. Chat Feature (Local, No LLM)

**File:** `src/rita/core/classifier.py`

3-layer pipeline:
1. **Intent classification** — SentenceTransformer `all-MiniLM-L6-v2`, cosine similarity against 20 fixed intents (threshold 0.42)
2. **Handler dispatch** — deterministic calculation against OHLCV data: `market_sentiment`, `strategy_recommendation`, `return_estimates`, `stress_scenarios`, `performance_feedback`, `portfolio_comparison`
3. **Logging** — POST `/api/v1/chat` logs to `alerts` table via `chat_monitor.py`

Endpoints:
- `POST /api/v1/chat/warmup` — pre-warms SentenceTransformer (called when chat panel opens)
- `POST /api/v1/chat` — classify + dispatch + log
- `GET /api/v1/chat/monitor` — KPIs + recent queries + intent distribution. Response `summary` dict also includes `commentary_count`, `commentary_avg_latency_ms`, `commentary_error_count` merged from `commentary_logs` table.
- `POST /api/v1/commentary` — deterministic rule-based narrative commentary for RITA dashboard pages. Request: `{app, page, instrument?}`. Response: `{app, page, commentary, instruments_analyzed, latency_ms}`. HTTP 400 for unknown app+page or missing instrument on strategy page.

---

## 11. Security

| Feature | Implementation |
|---|---|
| JWT | `python-jose` — issued by `POST /auth/token`, verified by `get_current_user` |
| Protected routes | `train`, `backtest`, `evaluate` — `Depends(get_current_user)` |
| Rate limiting | `slowapi` — 60/min global, 10/min on `/auth/token` |
| CORS | From `settings.security.cors_origins` (env-configured) |
| Input validation | Field constraints (max_length, ge=0, pattern) on 9 schemas |

---

## 12. Dashboard UI Panel Notes

### Nav Order (sidebar)

| Position | Section ID | Nav Label | Phase |
|---|---|---|---|
| 1 (landing) | `sec-market-signals` | Overview | Phase 01 — Plan (first item) |
| — | `sec-goal` | Financial Goal | Phase 01 — Plan |
| — | `sec-market` | Market Analysis | Phase 01 — Plan |
| — | `sec-technical-analysis` | Technical Analysis | Phase 01 — Plan |
| — | `sec-strategy` | Strategy | Phase 01 — Plan |
| — | `sec-scenarios` | Scenarios | Phase 02 — Backtest |
| — | `sec-agent-panel` | Agent Panel | Phase 02 — Backtest |
| — | `sec-performance` | Performance | Phase 03 — Analyse |
| — | `sec-trades` | Trade Journal | Phase 03 — Analyse |
| — | `sec-diagnostics` | Trade Diagnostics | Phase 03 — Analyse |
| — | `sec-explain` | Explainability | Phase 03 — Analyse |
| — | `sec-home` | Model Overview | Phase 03 — Analyse |

**Note:** `sec-market-signals` is the landing section (has `active` class on load). `_currentSection` default in `nav.js` is `'market-signals'`. `loadMarketSignals()` fires on `window.load`. Instrument selector tabs (`.inst-tab`) live inside `sec-market-signals`.

**Agent Performance section (`sec-agent-performance`, `data-s="agent-performance"`, loader `loadAgentPerformance`):** Feature 32 — under the Study nav group (next to Strategy Compare). Shows per-agent KPIs for the 7 investment-workflow agents (the trading-decision pipeline, distinct from the Ops Agent Builds /enhance dev pipeline). Renders KPI cards into `#agent-perf-cards` and a 7-row table into `#agent-perf-table` (columns: Agent, Gap Status, Invocations 30d, Outcome Match Rate, Trend vs Prior 30d), plus a refresh time in `#agent-perf-updated`. Reads `GET /api/v1/experience/rita/agent-performance`. `outcome_match_rate` and `trend_vs_prior_30d` render `—` (not 0%) when null. Module: `dashboard/js/rita/agent-performance.js`.

**Model Evaluation section (`sec-model-eval`, `data-s="model-eval"`, loader `loadModelEval`):** per-instrument RL diagnostic scorecard viewer (instrument tile bar `#me-instrument-bar` + 10-parameter scorecard detail `#me-content`, charts `chart-me-regime-sharpe`/`chart-me-action-regime`, reads `GET /api/v1/experience/rita/agent-performance/scorecards`). **F34 Phase 2.5 (2026-07-12):** prepended a per-instrument summary table (`#me-summary-table`, one row per instrument from `GET /api/v1/experience/rita/model-eval-summary`; columns Instrument | Last Trained | Timesteps | Val Sharpe | Val MDD% | Val CAGR% | Backtest Sharpe | Backtest MDD% | Backtest Return% | Trades | Gate; gate badge green PASS / amber BELOW GATE / neutral NO DATA — sub-gate models are never labelled "failed") and an evaluation plots block (`#me-eval-plots` with `#me-eval-plots-title`, empty-state `#me-eval-plots-msg`, canvases `chart-me-equity`/`chart-me-drawdown`/`chart-me-actions`). Rows with history are clickable → `meSelectRow(instrument)` (highlight class `me-row-active`) loads plots from `GET /api/v1/experience/rita/backtest-daily?instrument=<ID>` (drawdown computed client-side from portfolio_value running max; actions = stepped allocation line) and delegates to `meSelectInstrument()` when a scorecard exists. Default selection on load: ASML, falling back to the first row with data. Module: `dashboard/js/rita/model-eval.js`.

**Learnings / Concepts section (`sec-learnings`, `data-s="learnings"`, loader `loadLearnings`):** accordion concept cards + a live Market Trends card (Card 6, charts `chart-learn-price`/`chart-learn-rsi`). **Feature 31 (2026-06-17) — Investment Workflow & Agents:** appended after Card 6, a tabbed block explaining how professional investment firms invest — a narrative intro ("How Professional Investment Firms Invest"), an 8-step workflow table (Step / Purpose-Role / Scope), the retail-trader-gap paragraph, the RIIA two-pillar (Data Science + Agentic AI) explanation with the four ML-capability bullets, then a `concept-tab-bar` of 8 agent tabs (`switchAgentTab('a1'…'a8', this)`) and 8 `concept-panel` divs (`aw-a1`…`aw-a8`) each with `concept-desc` copy and a `concept-chart-grid` (canvases `aw-a1-c1`…`aw-a8-c1`, plus `aw-a4-c2` MACD; status span `aw-status`). Follows the DS Lab CRISP-DM tab pattern (`ds/concepts.js`). **No new endpoint** — charts reuse existing endpoints: `performance-summary`, `market-signals`, `experience/rita/backtest-daily`, `shap`, `experience/rita/training-history`. Concept CSS (`.concept-tab-bar`/`.concept-tab`/`.concept-panel`/`.concept-desc`/`.concept-chart-grid`) ported into `rita.html` `<style>` (active-tab accent uses `--run`).

### Element ID Formats

| Panel | Element ID | Format | Notes |
|---|---|---|---|
| Market Signals (Overview) | `ms-last-updated` | `Last updated: D MMM YYYY HH:MM` | Shows date **and** time (en-GB locale). Null/invalid date → `—`. Set to `—` on empty rows or API error. |
| Market Signals (Overview) | `ms-data-range` | `Timeframe · firstDate → lastDate \| N bars` | Date-only; unchanged. |

---

## 13. Key Design Constraints (DO NOT VIOLATE)

1. Never call a repository directly from a router — service layer only (Workflow tier), or repo-per-router (System tier).
2. Experience tier is **read-only** — no `db.commit()`, no `repo.upsert()` calls.
3. All repositories require `db: Session` — no default constructor.
4. Background threads must open their own `SessionLocal()` — never pass a request-scoped session.
5. `SqlRepository.upsert()` calls `db.commit()` internally — do not commit again.
6. `active_instrument_id` lives in `config_overrides` table (key = `"active_instrument_id"`), not in memory.
7. All OHLCV reads go through `load_nifty_csv()` or `load_instrument_data()` — no bare `pd.read_csv()`.
