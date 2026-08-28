# RITA - HTML Frontend Specifications

This document outlines the architecture, design constraints, and purposes of the HTML files within the `dashboard/` directory. These files form the Experience Layer of the RITA platform.

## Design & Technical Constraints

1. **Pure Vanilla Web Stack**: 
   - Strict adherence to Vanilla HTML, Vanilla JavaScript (ES Modules), and pure CSS.
   - **DO NOT USE** React, Vue, Svelte, or any other JavaScript framework.
   - **DO NOT USE** Tailwind CSS, Bootstrap, or any other CSS framework.
2. **Styling and Theming**:
   - All styling is centralized via CSS variables documented in the `<style>` tags or `css/responsive.css`. Follow existing palettes (`--surface`, `--border`, `--text`, `--build`, `--run`, `--warn`).
   - Use dynamic interactions (hover states, transitions) heavily. Keep the UI feeling modern and responsive.
3. **Data Fetching**:
   - The UI communicates strictly with the Experience Layer API (`/api/experience/...`), fetching pre-composed payloads.
4. **Charting**:
   - `Chart.js` is utilized for all graphics, graphs, and performance charts. Avoid introducing D3 or Recharts.

---

## File Specifications

### 1. `index.html` (Welcome Portal)
- **Purpose**: The entry point of the frontend application. It acts as a router/landing page that directs the user to different personas or apps within RITA.
- **Key Sections**:
  - Hero banner with system readiness status.
  - **Demo / Live auth toggle** (`#auth-toggle-switch`, default: Live / checked): controls how tile navigation is authenticated. On **localhost** tiles navigate directly regardless of toggle. In **Live** mode, tiles check `auth_token` and redirect to `/auth/google/login` if absent. In **Demo** mode, tiles call `POST /auth/token {username:'webmaster@ravionics.nl', password:'rita-dev'}` to mint a JWT for the shared demo account, store it, then navigate — no Google OAuth needed. Demo mode exercises every function including Ops (all access flags are True on the demo user).
  - **Open Access zone** (no auth):
    1. **Invest Game** -> routes to `investgame-app.html`
  - Four primary navigation tiles (`.protected-route`):
    1. **Research (Data Scientist Lab)** -> routes to `ds.html`
    2. **Portfolio Builder (RITA core)** -> routes to `rita.html`
    3. **Portfolio Review (FnO Tracker)** -> routes to `fno.html`
    4. **Operations (Ops Portal)** -> routes to `ops.html`

### 2. `rita.html` (Portfolio Builder / RITA Core)
- **Purpose**: The core user interface for retail investors or quantitative traders to build, backtest, and evaluate their portfolios using the Double DQN model.
- **Sections (Phases)**:
  - **Phase 01 (Plan)**: Financial Goal setting, Market Analysis (fetching latest MACD/RSI indicators), and Strategy formulation.
  - **Phase 02 (Backtest)**: Scenarios to configure backtesting date boundaries.
  - **Phase 03 (Analyse)**: Performance (comparing returns against benchmarks), Trade Journal, and Model Explainability (SHAP values).
  - **Phase 04 (Monitor)**: Live Risk Views, Training Progress, and Observability.
  - **Phase 05 (Agentic AI)**: Agent Panel + AI Compliance — multi-agent ASML simulation demo.
- **Interacts with**: `/api/experience/dashboard`, `/api/v1/agent-panel`, and underlying `workflow` triggers.

#### Overview section (`#sec-market-signals`) layout (updated 2026-05-21)

DOM order inside `<section id="sec-market-signals">`:
1. `.page-hdr` — "Overview" title + last-updated label + Refresh button
2. `#geo-panels` (`.card-row`) — geography instrument tiles; each tile is `.geo-kpi` with `onclick="selectGeoInstrument(id)"`. Clicking selects the instrument and refreshes signal data. Active tile gets `.geo-kpi-active`.
3. `#commentary-overview-box` — AI commentary narrator (hidden until populated)
4. Timeframe tabs (Daily / Weekly / Monthly)
5. Signal KPI strip (`#ms-signals`)
6. Alert strip (`#ms-alerts`)
7. Price & Volume chart

**Removed:** `#inst-tabs-container` and the `.inst-tab` button row — geography tiles are the instrument selector.

- **Trade Journal section (`#sec-trades`) layout:**
  - Phase legend row (`display:flex; justify-content:space-between`) contains the colour-coded phase labels on the left and `#trades-model-info` (Rounds · Algorithm · Timesteps · Model ver, injected by `trades.js`) on the right.
  - `#trades-kpi-strip` uses `grid-template-columns: 1fr 1fr 2fr` — Train (25%) | Test (25%) | Backtest (50% with 8 metrics in a 4-column inner grid).

#### Agent Panel section (`#sec-agent-panel`)

6-agent LangGraph simulation running on ASML April 2026 data (16 days). Driven by `agent-panel.js`.

**Key DOM elements:**
| Element | Purpose |
|---|---|
| `#ap-chart` | Dual-axis Chart.js — ASML price (right y) + capital (left y) |
| `#ap-regime` | Current regime label |
| `#ap-policy` | Dynamic stop/target policy |
| `#ap-probability` | Historical success % |
| `#ap-proposal` | Action (BUY/WAIT) + size |
| `#ap-compliance` | Compliance status — green or red |
| `#ap-audit-body` | tbody — one row per day run, newest first (6 columns: Date, Context, Strategy, Probability, Portfolio Mgr, Compliance) |
| `#ap-narrator-title` | Narrator box title (typewriter animated) |
| `#ap-narrator-text` | Narrator insight text (typewriter animated) |
| `#ap-hitl-panel` | Human-in-the-Loop decision panel (hidden until BUY proposal) |
| `#ap-hitl-summary` | Proposal summary shown in HITL panel |
| `#ap-run-btn` | `onclick="agentPanelStep()"` — Run Day / Processing / Complete |
| `#agent-panel-status` | Status badge |
| Reset button | `onclick="resetAgentPanel()"` |
| Approve button | `onclick="approveAgentProposal()"` (inside HITL panel) |
| Reject button | `onclick="rejectAgentProposal()"` (inside HITL panel) |

#### AI Compliance section (`#sec-ai-compliance`)

Reads `riia_agent_history` from localStorage. Three sub-tabs. Driven by `ai-compliance.js`.

**Tab structure:**
| Tab button id | View id | Content |
|---|---|---|
| `ac-tab-governance` | `ac-view-governance` | KPIs + visual timeline of days |
| `ac-tab-guardrails` | `ac-view-guardrails` | Static rules documentation |
| `ac-tab-trace` | `ac-view-trace` | Trace inspector (per-day agent logs) |

**Key DOM elements:**
| Element | Purpose |
|---|---|
| `#ac-pass-rate` | Compliance pass rate % |
| `#ac-veto-count` | Number of FLAGGED days |
| `#ac-days-run` | Total days run |
| `#ac-timeline` | Container for clickable `.ac-node` day circles |
| `#ac-day-label` | Selected day label in trace inspector |
| `#ac-violation-badge` | Compliance status badge (shown on veto days) |
| Tab buttons | `.ac-tab` class + `onclick="switchAcTab(tabId, viewId)"` |
| Tab views | `.ac-view` class, toggled visible/hidden by `switchAcTab()` |

### 3. `fno.html` (FnO Portfolio Manager)
- **Purpose**: A specialized tracker for Futures and Options positions. Focuses heavily on Greeks, margin utilization, and hedging tools.
- **Sections**:
  - **Positions**: Active and closed trades with Unrealized/Realized P&L.
  - **Margin Tracker**: Estimates SPAN and exposure margins for active baskets.
  - **Risk & Greeks**: Aggregates Delta, Theta, and Vega across the portfolio. Stress scenarios (P&L at different underlying levels).
  - **Risk-Reward & Hedge History**: Tools for scenario planning and tracking anchor positions and reactive hedges.
  - **My Portfolio** (inside `#page-overview`) — **F29 Phase 3** redesign. Components: (1) meta strip (`fno-mp-name`, `fno-mp-updated`); (2) placeholders `fno-mp-empty` (hidden by default) and `fno-mp-error` (hidden by default); (3) 5-card KPI strip — `fno-mp-kpi-value` (Portfolio Value), `fno-mp-kpi-holdings` (Holdings count), `fno-mp-kpi-return` (Wtd 1Y Return, subtitle "weighted avg (indicative)"), `fno-mp-kpi-risk` (Avg Risk, subtitle "weighted avg (indicative)"), `fno-mp-kpi-hedged` (Hedge Coverage, subtitle "from saved plan (indicative)"); (4) 2-column row — left: `canvas#fno-mp-alloc-chart` inside `.chart-wrap` (region allocation doughnut), right: `div#fno-mp-hedge-card` (hedge status card, includes "Values are indicative — not financial advice" note); (5) 6-column holdings table — thead columns: Instrument · Alloc% · Position € · "1Y Return (ind.)" · "Risk (ind.)" · Hedged? — tbody: `fno-mp-holdings-body` — tfoot: `fno-mp-total`; (6) CTA button calling `fnoMpGoHedge()`.
  - **Portfolio Hedge** (`#page-portfolio-hedge`): 4-tab wizard (Feature 28 Phase 3). Tab bar buttons: `ph-tab-btn-{discover|selection|allocation|hedge}`. Panels: `ph-panel-{discover|selection|allocation|hedge}`.
    - **Discover** tab: Duration pills (`ph-dur-1m/3m/1y`). Holdings table — `<tbody id="ph-discover-holdings">` inside `.tbl-wrap` (max-height 230px, sticky thead). Concept block below explains hedging + horizon choice.
    - **Selection** tab: `<tbody id="ph-selection-body">` inside `.tbl-wrap` (max-height 230px, sticky thead). Put Buy / Sell Call buttons per row; `Rec` badge auto-assigned (risk ≥ 3 → Put Buy). Concept block below explains the two strategies.
    - **Allocation** tab: `<tbody id="ph-alloc-body">` + `<tr id="ph-alloc-agg-row">` (tfoot aggregate) inside `.tbl-wrap` (max-height 240px, sticky thead). σ columns: −2σ / −1σ / Flat / +1σ. Summary strip: `ph-alloc-cost` + `ph-alloc-dd`. Concept block explains σ and table reading.
    - **Hedge** tab: confirmed strategy table (`ph-table-body`), coverage dial (`ph-coverage-slider`), payoff chart (`ph-payoff-chart`), scenario table (`ph-scenario-body`). Strategy tabs: `ph-tab-{pp|ps|collar}`.
    - State banners: `ph-loading`, `ph-error` / `ph-error-msg`, `ph-empty` / `ph-empty-msg`. Content wrapper: `ph-content` (hidden until loaded).
  - **Equity Scenarios** (`#page-equity-scenarios`, nav item `data-page="equity-scenarios"` — integrated as a native FnO section `538cd1b`, 2026-06): Equity SL/Target scenario tracker rendered by `js/scenarios/equity-scenarios.js` via `_sectionLoaders['equity-scenarios']`. Expandable table layout — one line per instrument, 9-dot SL→Target position indicator column, Position column at the end; clicking a row toggles a detail row (P&L metrics, trade chips, recommendation). Colour tokens aliased to the fno palette via CSS custom properties scoped to `#page-equity-scenarios`. Data: static JSONs at `dashboard/data/scenarios/{alerts,portfolio,tradebook}.json` (committed in repo — required in prod).
  - A standalone wrapper page `dashboard/equity-scenarios.html` also exists, importing the same `init` from `js/scenarios/equity-scenarios.js`.

### 4. `ops.html` (Operations Portal)
- **Purpose**: Used by the platform engineers and DevOps to ensure the health of the RIIA system.
- **Sections**:
  - **Monitoring**: Real-time stats on API latency, error rates, and endpoints.
  - **CI / CD Pipeline**: Tracks the state of linting, unit testing, and Playwright execution matrices.
  - **Test Results** (`#sec-test`): Three suite-type summary cards (e2e/integration/unit) + scrollable module grid + overall KPI strip + failures table.
    - Suite summary cards: `#ts-e2e`, `#ts-integration`, `#ts-unit` — rendered by `loadTestResults()`.
    - Module grid: `#test-module-grid` — one row per test file; scrollable after 6 rows (max-height 252px, sticky thead).
    - Overall KPIs: `#test-total`, `#test-passed`, `#test-failed`, `#test-rate`.
    - Failures: `#test-failures` — scrollable table of failing test cases, or "All tests passing" banner.
  - **Deployments**: Details on the FastAPI and Streamlit environments, environment variables, and ports.
  - **Observability & Chat Analytics**: Model drift monitoring and query volume logs for the chat-based RITA assistant.
  - **Risk** (`#sec-risk`, formerly "Daily Ops" — renamed `1ee6105`): Portfolio risk overview rendered above the Manoeuvre section (risk-first layout). Driven by `ops/risk.js`. Components: (1) KPI strip — net delta, theta, vega, unrealised P&L; (2) open positions table; (3) stress scenarios table; (4) hedge quality score chips. Below a divider: Manoeuvre section (snapshots, action log, history).

### 5. `investgame-app.html` (Invest Game App)
- **Purpose**: Standalone top-level app aggregating the Invest Game, learning content, and agent dashboards into a unified sidebar experience. Open access (no auth).
- **Tile**: First tile in the Open Access zone on `index.html`.
- **Shell**: Same grid layout as `rita.html` / `ops.html` — topbar + collapsible sidebar + content area.
- **Sidebar pages** (7 sections):
  - **Invest Game** (`sec-investgame`): Welcome intro with link to play.
  - **Journey** (`sec-journey`): Investor journey flow via lazy-loaded iframe.
  - **Concepts** (`sec-concepts`): 8-tab agent workflow with Chart.js charts (NIFTY data).
  - **CRISP-DM** (`sec-crisp-dm`): 6-phase CRISP-DM methodology (ASML data).
  - **Agent Performance** (`sec-agent-performance`): Per-agent RL scorecards + KPIs.
  - **Agent Builds** (`sec-agent-builds`): Build run history, grounding charts, token estimates.
  - **Agent Panel** (`sec-agent-panel`): 16-day ASML multi-agent simulation demo.
- **JS architecture**: ES modules at `dashboard/js/investgame-app/` — imports from `shared/api.js`, `shared/charts.js`, `shared/utils.js`, `shared/i18n.js`, `shared/dev-auth.js`.
- **Entry point**: `<script type="module" src="./js/investgame-app/main.js"></script>`
- **Full spec**: See `Spec_Invest_Game.md` §10 for detailed module structure and nav map.

### 6. `ds.html` (Data Scientist Lab)
- **Purpose**: The advanced view for model developers to tweak the reinforcement learning model, re-train hyperparameters, and iterate on features.
- **File size**: ~2,900 lines. **DO NOT re-read the file** — use this spec instead. Only open specific line ranges when actually editing code.

#### Sidebar navigation map

| Nav label | Section id | Loader fn | Color | Description |
|---|---|---|---|---|
| Understand | `s-understand` | `loadUnderstand()` | `c-ds` | Default landing. Instrument data viz. Portfolio pill included. |
| Dashboard | `s-dashboard` | `loadDashboard()` | `c-text` | Last build KPIs: `d-return`, `d-cagr`, `d-sharpe`, `d-mdd`, `d-winrate`. Constraint strip `#dash-constraints`. Last run summary `#dash-goal`. |
| Build | `s-pipeline` | _(no auto-load)_ | `c-ds` | Two panels: Build (`runBuild()`) + Re-use (`runReuse()`). 8-step progress bars `build-bar`/`reuse-bar`. Status `build-status`/`reuse-status`. Step accordion `build-accordion`/`reuse-accordion`. Instrument dropdowns `b-instrument`/`r-instrument`. |
| Performance | `s-performance` | `loadPerformance()` | `c-build` | KPIs: `p-return`, `p-cagr`, `p-sharpe`, `p-mdd`, `p-winrate`. Constraint strip `#perf-constraints` (hidden until data). Charts: `ch-returns`, `ch-drawdown`, `ch-sharpe-roll`, `ch-alloc`. **Round-by-Round Comparison card** at bottom — 3 tabs (Training/Validation/Backtest) toggled by `switchPerfTab(tab,el)`. All 3 panels read a single `/api/v1/training-history` fetch with identical structure: chart (Sharpe | MDD % | Return % | Trades) + table (Run | Sharpe | MDD% | Return% | Trades). X-axis labels: `R1, R2, …` (short run labels). Field prefixes: `train_` for Training tab, `val_` for Validation, `backtest_` for Backtest. Trades on right Y-axis (`y1`), metrics on left (`y`). Charts: `ch-pf-train`, `ch-pf-val`, `ch-pf-bt`. Tables: `pf-train-tbl`, `pf-val-tbl`, `pf-bt-tbl`. Layout: `.round-cmp-grid` (2-col CSS grid). Tab CSS: `.perf-phase-tab.active`, `.perf-phase-panel.hidden`. API: `/api/v1/performance-summary` + `/api/v1/backtest-daily` + `/api/v1/training-history`. |
| Risk View | `s-risk` | `loadRisk()` | `c-build` | KPIs: `r-avg-var`, `r-peak-var`, `r-max-budget`, `r-ri-trades`. Charts: `ch-var`, `ch-budget`, `ch-trade-risk`, `ch-regime`. Table `#risk-phase-tbl`. API: `/api/v1/risk-timeline` + `/api/v1/trade-events`. |
| Trade Journal | `s-trades` | `loadTrades()` | `c-build` | KPIs: `t-entries`, `t-profit`, `t-loss`, `t-winrate`, `t-total`, `t-sharpe-entry`, `t-sharpe-exit`, `t-sharpe-delta`. Charts: `ch-trade-combined`, `ch-trade-pv`, `ch-trade-dd`. Tables: `#trade-phase-tbl`, `#trade-log-tbl`. API: `/api/v1/trade-events` + `/api/v1/backtest-daily`. |
| Explainability | `s-explain` | `loadExplain()` | `c-build` | KPIs: `sh-top`, `sh-cash`, `sh-full`. Charts: `ch-shap-bar`, `ch-shap-radar`. Table `#shap-tbl`. API: `/api/v1/shap`. |
| Scenarios | `s-scenarios` | `loadScenariosPage()` | `c-ds` | Instrument sliders `sc-slider-{id}`, checkboxes `sc-inst-{id}`, % labels `sc-pct-{id}`, EUR labels `sc-eur-{id}`. Capital input `sc-capital`. Dates `sc-from`, `sc-to`. Button `btn-sc`, spinner `sc-spinner`, badge `sc-status`. Results `#sc-result` (injected HTML + `chart-sc-portfolio`). |
| Training Metrics | `s-training` | `loadTraining()` | `c-run` | **3-phase tabs** (see below). KPIs: `tr-rounds`, `tr-best-sharpe`, `tr-latest-ret`, `tr-latest-val`. |
| Model Changelog | `s-changelog` | `loadChangelog()` | `c-run` | **Build History card at top**: `#build-hist-tbl`, badge `#build-badge`. Changelog table `#cl-tbl`. Add-entry form: `cl-date`, `cl-version`, `cl-cat`, `cl-change`, `cl-notes`. Save `saveChangelog()`. |
| Observability | `s-observability` | `loadObservability()` | `c-mon` | KPIs: `ob-total`, `ob-failed`, `ob-drift`. Chart `ch-ob-dur`. Health strip `#obs-health`. Table `#obs-run-tbl`. API: `/api/v1/step-log` + `/api/v1/drift`. |
| MCP Calls | `s-mcp` | `loadMCP()` | `c-mon` | KPIs: `mc-total`, `mc-success`, `mc-tools`, `mc-latency`, `mc-errors`, `mc-last`. Charts: `ch-mc-usage`, `ch-mc-latency`. Table `#mcp-tbl`. API: `/api/v1/mcp-calls`. |
| Export & DevOps | `s-export` | `loadExport()` | `c-warn` | Download buttons (JSON exports). API health panel `#api-health`. Manifest `#deploy-manifest`. Env table `#env-tbl`. |

#### Training Metrics — 3-phase tab structure (added 2026-04-17)

Tab switcher: `switchTrainTab(tab, el)` — toggles `.train-tab.active` + `.train-panel.hidden`.

| Tab | Panel id | Charts | Tables | Data source |
|---|---|---|---|---|
| Training | `tt-training` | `ch-tr-loss` (TD Loss + Reward dual-axis) | `#train-progress-tbl` | `/api/v1/training-progress` → fields `timestep`, `td_loss`, `reward` |
| Validation | `tt-validation` | `ch-tr-val-sharpe`, `ch-tr-val-mdd` | `#train-val-tbl` | `/api/v1/training-history` → fields `val_sharpe`, `val_cagr_pct`, `val_mdd_pct` |
| Backtest | `tt-backtest` | `ch-tr-sharpe` (BT+Val Sharpe), `ch-tr-mdd`, `ch-tr-return` | `#train-constraint-tbl`, `#train-hist-tbl` | `/api/v1/training-history` → fields `backtest_sharpe`, `backtest_mdd_pct`, `backtest_return_pct`, `backtest_cagr_pct` |

**Critical field names for training-history API** (common bug source — wrong names produce blank charts):
- Date: `timestamp` (NOT `run_date`)
- Backtest Sharpe: `backtest_sharpe` (NOT `sharpe_ratio`)
- Backtest MDD: `backtest_mdd_pct` (NOT `max_drawdown_pct`)
- Backtest Return: `backtest_return_pct` (NOT `total_return_pct`)
- Backtest CAGR: `backtest_cagr_pct` (NOT `cagr_pct`)
- Validation Sharpe: `val_sharpe` ✓
- Validation CAGR: `val_cagr_pct` ✓
- Validation MDD: `val_mdd_pct` ✓

#### Understand section

- Instrument pills rendered from `GET /api/v1/instruments` into `#viz-instrument-list` by `loadUnderstand()`.
- Portfolio pill `__portfolio__` → `runPortfolioOverview()` → `GET /api/v1/portfolio/overview`.
- Per-instrument results in `#viz-results`: KPI ids `vk-rows`, `vk-features`, `vk-from`, `vk-to`, `vk-missing`, `vk-trends`. Grids: `#viz-dist-grid` (distributions), `#viz-ts-grid` (time series), `#viz-cluster-grid` (clustering). Correlation: `#viz-corr-table`.
- Portfolio results in `#viz-portfolio-results`: KPIs `vp-count`, `vp-days`, `vp-from`, `vp-to`. Grid `#vp-inst-grid`. Chart `chart-vp-returns`. Correlation `#vp-corr-table`.
- Viz modal: `#viz-modal` (full-screen), canvas `#vm-canvas`. Opened by `openVizModal(chartId, title, desc)`.

#### Scenarios section

- Sliders update `scUpdateTotal()` on `oninput`. `scToggleInst(id)` disables slider when checkbox unchecked.
- Run: `runPortfolioScenario()` → `POST /api/v1/portfolio/backtest` → `renderPortfolioScenarioResults(d, from, to)` injects HTML into `#sc-result` + creates `chart-sc-portfolio`.
- Capital input `sc-capital` (default €1000), remaining-cash label `sc-remaining-lbl`.

#### JS architecture

- All JS inline in `<script>` tag (no ES module subtree). ~1,700 lines of JS.
- Chart registry: `const CHARTS = {}`. Helper: `mkChart(id, type, data, extra)` — destroys previous instance, creates new, attaches zoom-on-click to parent `.chart-wrap`. Destruction: `destroyChart(id)`.
- Color palette: `const C = { build, buildBg, run, runBg, mon, monBg, warn, warnBg, danger, dangerBg, ds, dsBg, t2, t3, grid }`.
- Table helper: `mkTbl(rows, cols)` — cols have `{key, label, mono?, right?}`.
- API helper: `api(path, opts)` — throws on non-2xx.
- Number helpers: `fmt(v, dec)`, `fmtPctRaw(v, dec)`.
- Navigation: `show(sectionId, el)` — loaders map is inline inside the function.
- Tab switchers: `switchTrainTab(tab, el)` (Training Metrics), `switchPerfTab(tab, el)` (Performance round-comparison) — same pattern: toggle `.active` on tabs, toggle `.hidden` on panels.
- Topbar status: `checkStatus()` runs every 30s.
- Active instrument: `_activeInst` global, updated by `loadActiveInstrument()`.
- Pipeline polling: `pollProgress()` inside `runPipeline(forceRetrain)`. Steps polled from `/progress`. Step keys: `step1_goal_set` … `step8_goal_updated`.

#### CSS variables (`:root`)

```
--bg, --surface, --surface2, --border, --border2
--text, --t2, --t3, --t4
--build, --build-bg, --build-bd
--run, --run-bg, --run-bd
--mon, --mon-bg, --mon-bd
--warn, --warn-bg, --warn-bd
--danger, --danger-bg, --danger-bd
--ds, --ds-bg, --ds-bd          ← teal — Data Scientist accent colour
--fd (Epilogue), --fm (IBM Plex Mono), --fs (Instrument Serif)
--r (6px border-radius), --sh (box-shadow), --shm
```

#### Key CSS classes

- `.geo-kpi` / `.geo-kpi-active` — geography panel instrument tiles (selectable; hover = subtle border, active = `--run` border + `--run-bg` background)
- `.kpi` / `.kpi-row-{3|4|5|6}` — metric cards
- `.card` / `.card-hdr` / `.card-row` / `.card-row-3` — content panels
- `.chart-wrap` / `.chart-box` / `.h180` `.h220` `.h260` `.h300` `.h340` — chart containers
- `.tbl-wrap` — scrollable table container; **max-height: 228px (6 rows visible)**; `overflow:auto`; sticky `<th>`
- `.badge.{ok|warn|err|run|ds|neu|mon}` — status pills
- `.alert-strip` / `.alert-row.{ok|warn|err}` — constraint/health rows
- `.pipe-panel.{build|reuse}` — pipeline config panels
- `.inline-steps` / `.istep-bar` / `.istep.{done|running}` — 8-step progress bar inside panels
- `.viz-pill.selected` — instrument selector pills
- `.train-tab-bar` / `.train-tab.active` / `.train-panel.hidden` — Training Metrics phase tabs
- `.cfg-grid` / `.cfg-group` / `.cfg-input` / `.cfg-select` — config form inside panels

#### Navigation: adding a new section

1. Add `<div class="nav-item c-{color}" data-s="{key}" onclick="show('{key}',this)">` in sidebar.
2. Add `<div id="s-{key}" class="section">` in `<main>`.
3. Write `async function load{Key}()`.
4. Add `{key}: load{Key}` entry in the `loaders` map inside `show()`.

#### Topbar elements

- `#nav-toggle` — collapse/expand sidebar (persisted in `localStorage`).
- `#inst-pill` (flex, hidden until active instrument loads): `inst-pill-flag`, `inst-pill-name`, `inst-pill-exch`.
- `#status-dot` (`.ok` / `.err`) + `#status-text` — API health indicator.
- `#sb-data-info`, `#sb-model-info` — sidebar footer status lines.

#### Chart expand modal

- `#chart-modal` (fixed overlay): `#chart-modal-title`, `#chart-modal-img`. Opens via `openChartModal(id, title)`, closes via `closeChartModal()` or Escape key. Renders canvas as PNG image (not a live Chart.js instance).
