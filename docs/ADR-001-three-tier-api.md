# ADR-001: Three-Tier API Design (Experience Layer / Business Process / System)

| Field | Value |
|---|---|
| **Status** | Accepted (updated Aug 2026) |
| **Date** | 2026-03-30 |
| **Last updated** | 2026-08-08 (full router inventory — 11 instruments, F34 features) |
| **Sprint** | 0 |

---

## Context

The POC had a single monolithic `rest_api.py` (1,533 lines) that mixed three distinct concerns:

- **CRUD operations** on individual CSV tables (positions, orders, snapshots)
- **Business process logic** for long-running jobs (train, backtest, evaluate)
- **Aggregation** of multiple data sources into UI-ready payloads (dashboard, FnO view, ops view)

This violates the Single Responsibility Principle, makes unit testing impossible without loading the entire app, and creates merge conflicts whenever more than one engineer touches the API layer.

---

## Decision

Split all API routes into three tiers with strict rules about what each tier is allowed to do.

### Tier 1 — System (`api/v1/system/`)

Pure CRUD for individual ORM-backed table resources. No business logic. Direct repository calls only.

| Router file | Prefix | Tables accessed |
|---|---|---|
| `system/positions.py` | `/api/v1/positions` | `positions` |
| `system/orders.py` | `/api/v1/orders` | `orders` |
| `system/snapshots.py` | `/api/v1/snapshots` | `snapshots` |
| `system/trades.py` | `/api/v1/trades` | `trades` |
| `system/alerts.py` | `/api/v1/alerts` | `alerts` |
| `system/audit.py` | `/api/v1/audit` | `audit_log` |
| `system/market_data.py` | `/api/v1/market-data` | `market_data_cache` |
| `system/market_signals.py` | `/api/v1/market-signals` | `market_data_cache` (computes indicators) |
| `system/config_overrides.py` | `/api/v1/config-overrides` | `config_overrides` |
| `system/instruments.py` | `/api/v1/instruments` | `instruments` |
| `system/training_runs.py` | `/api/v1/training-history`, `/api/v1/risk-timeline`, `/api/v1/split-dates`, `/api/v1/backtest-status/{id}` | `training_runs`, `backtest_runs`, `backtest_results` |
| `system/drift.py` | `/api/v1/drift` | DB-backed DriftDetector |
| `system/data_prep.py` | `/api/v1/data-prep/*`, `/api/v1/test-results`, `/api/v1/shap-values`, `/api/v1/data-understanding` | file system |
| `system/mcp_calls.py` | `/api/v1/mcp-calls` | MCP call log |
| `system/client_errors.py` | `/api/v1` (client error reporting) | Client-side error capture |

**Rule:** A System router may call **one repository** only. It must never call a service or another router.

### Tier 2 — Business Process (`api/v1/workflow/`)

Stateful workflows that orchestrate multiple services. Returns job status and results. Long-running operations triggered by the user. JWT-protected.

| Router file | Endpoints | Responsibility |
|---|---|---|
| `workflow/train.py` | `POST /api/v1/train` | Start DQN training run, multi-seed via `train_best_of_n()` |
| `workflow/backtest.py` | `POST /api/v1/backtest` | Start backtest, store results in `backtest_runs` + `backtest_results` |
| `workflow/evaluate.py` | `POST /api/v1/evaluate` | Run model evaluation against live or historical data |
| `workflow/pipeline.py` | `POST /api/v1/instrument/select`, `GET /api/v1/pipeline/progress`, `POST /api/v1/pipeline/quick-backtest` | Instrument switch + pipeline state |
| `workflow/chat.py` | `POST /api/v1/chat`, `POST /api/v1/chat/warmup`, `GET /api/v1/chat/monitor` | Local intent classifier chat; logs to `alerts` table |
| `workflow/instrument_onboard.py` | `/api/v1` (instrument onboard endpoints) | Instrument onboarding workflow |
| `workflow/user_portfolio.py` | `/api/v1/user-portfolio` | User portfolio management workflow |
| `workflow/commentary.py` | `/api/v1/commentary` | Commentary generation workflow |

**Rule:** A Workflow router calls **services only** — never repositories directly, never Experience Layer routers.

### Tier 3 — Experience Layer (`api/experience/`)

Composes data from the System and Workflow tiers into single, UI-optimised payloads per view. Shaped around what a specific screen needs. No writes, no side effects — read-only composition only.

| Router file | Prefix | Purpose |
|---|---|---|
| `experience/dashboard.py` | `/api/experience` | Legacy RITA / FnO / Ops aggregated payloads |
| `experience/fno.py` | `/api/experience/fno` | FnO aggregated payload (Greeks, P&L, manoeuvres) |
| `experience/ops.py` | `/api/experience/ops` | Ops payload + metrics/summary + step-log + users |
| `experience/rita.py` | `/api/v1` | RITA performance, risk, trade events, instrument selection endpoints |
| `experience/pipeline_wizard.py` | `/api/v1` | Goal / Market / Strategy wizard steps for the onboarding flow |
| `experience/ds.py` | `/api/experience/ds` | DS dashboard — instruments + training history + split dates |
| `experience/agent_panel.py` | `/api/v1/agent-panel` | LangGraph 6-agent simulation; HITL run-day + plot endpoints |
| `experience/invest_game.py` | `/api/experience/invest-game` | Investment game simulation UI payloads |
| `experience/portfolio_analytics.py` | `/api/v1/experience/fno` | Portfolio analytics aggregated view (`/portfolio-analytics`) |
| `experience/portfolio_hedge.py` | `/api/v1/experience/fno` | Portfolio hedge scenario composition (`/portfolio-hedge`) |
| `experience/hedge_reasoning.py` | `/api/v1/experience/fno` | Hedge reasoning and advisory payloads |
| `experience/user_portfolio.py` | `/api/v1/experience` | User portfolio read-only endpoint (`/user-portfolio`) |
| `experience/users.py` | `/api/v1/experience/users` | User traffic analytics (`/traffic`) |
| `experience/optimal_allocation.py` | `/api/v1/experience/rita` | F34 optimal allocation view (`/optimal-allocation`) |
| `experience/fno_hedge_plan.py` | `/api/v1/experience/fno` | FnO hedge plan read/write (`/hedge-plan`) |

**Special routers (outside the 3-tier hierarchy):**

| Router file | Prefix | Notes |
|---|---|---|
| `api/v1/auth.py` | `/auth/token` | JWT token issue — not CRUD, not ML, not a UI view |
| `api/v1/portfolio.py` | `/api/v1/portfolio/*` | Cross-instrument portfolio + FnO positions; 11 endpoints |

**Rule:** An Experience Layer router calls **System routers or services** to compose responses. It must never write data or trigger side effects.

---

## Consequences

**Positive:**
- Each tier has a single responsibility — engineers can work independently without conflicts.
- Unit testing is clean: repositories and services are testable in isolation.
- The Experience Layer absorbs all N+1 query risk — the UI makes one call per view, not many.
- The workflow tier can be replaced with a task queue (Celery, ARQ) in v2 without touching the Experience Layer or System tiers.
- "Experience Layer" communicates intent clearly — these routes exist to serve a specific user experience, not to expose raw data.

**Negative:**
- More files and boilerplate than the POC monolith.
- Small features require touching multiple files (route + service + repository).

---

## Alternatives Considered

| Option | Reason Rejected |
|---|---|
| Keep single `rest_api.py` | Same monolith problem — untestable, merge-conflict prone |
| GraphQL | Team unfamiliar; resolver pattern adds complexity not justified for v1 |
| Microservices split | Premature — single deployable is correct for v1 CSV-backed system |
| Name tier 3 "BFF" (Backend For Frontend) | Jargon — unclear to anyone not familiar with the pattern; "Experience Layer" communicates purpose directly |
