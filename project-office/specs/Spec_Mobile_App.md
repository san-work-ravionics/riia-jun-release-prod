# RITA Mobile App — Specification

High-density reference for AI agents working on the RITA mobile PWA.

**File:** `riia-jun-release/mobileapp/index.html`
**Type:** Single-file Progressive Web App (PWA) — 1,311+ lines
**Platform target:** Android Chrome (installable via manifest.json)

---

## 1. Architecture

| Decision | Detail |
|---|---|
| Single file | All HTML, CSS, and JS in `index.html` — no bundler, no external JS files |
| PWA | `manifest.json` + `sw.js` (service worker) — installable on Android |
| Live data | Toggle-gated — `LIVE_MODE = localStorage.getItem('ritaLiveMode') === 'true'` |
| Fallback | Every API call silently falls back to hardcoded DOM values on failure — app never breaks |
| Backend URL | `API_BASE = 'http://localhost:8000'` (hardcoded constant) — change for production |
| Chat | Hardcoded overlay — no backend API connection |
| Home screen | Hardcoded — user will redesign later |
| i18n | Language capsule (EN/NL/FR pill buttons) on home screen (s0) — reads/writes `localStorage('ritaLanguage')`. Applies `data-i18n` attribute translations. Part of Feature 14. |

---

## 2. 10 App Screens

| ID | Screen name | Description |
|---|---|---|
| s0 | Home | Avatar, greeting, RITA SAYS banner, Live toggle |
| s1 | Goal | YTD return radial ring, Sharpe, Win Rate |
| s2 | Market | Timeframe tabs (Daily/Weekly/Monthly) + 8-KPI grid (RSI-14, MACD, BB %B, ATR-14, EMA5, EMA13, EMA26, Trend) + Signal highlights + Price & Volume SVG chart |
| s3 | Signal Hero | Active signal types, regime, confidence |
| s4 | Strategy | P&L, Win Rate, Sharpe, trade decisions list |
| s5 | Today | Date hero, regime card, NIFTY price, signal type rows |
| s6 | Overview | Market hero price, goal progress bar, signal previews |
| s7 | Market Feed | Regime pill, factor bars, narrative paragraph |
| s8 | Portfolio | Total value, daily gain, holdings list + sparklines |
| overlay | Portfolio overlay | Detailed holdings with sparklines |

Navigation: `goTo(screenIndex)` — slides left/right between screens.

---

## 3. API Client Functions (6 total)

All functions return `null` on failure (never throw). Callers check `if (!data) return`.

```js
// ── Config ───────────────────────────────────────────────────────────────────
const API_BASE  = 'http://localhost:8000';
let   LIVE_MODE = localStorage.getItem('ritaLiveMode') === 'true';

// ── API client ───────────────────────────────────────────────────────────────
async function fetchTimeline()        // GET /api/v1/risk-timeline
async function fetchSignals()         // GET /api/v1/market-signals?instrument=NIFTY&periods=5
async function fetchPerformance()     // GET /api/v1/performance-summary
async function fetchPortfolioSummary()// GET /api/v1/portfolio/summary
async function fetchPositions()       // GET /api/v1/portfolio/positions?mode=paper
async function fetchPriceHistory()    // GET /api/v1/portfolio/price-history?periods=30
async function fetchTradeEvents()     // GET /api/v1/trade-events
```

---

## 4. Live Data Coordinator (`initLiveData()`)

Called when app starts (if LIVE_MODE) and when Live toggle is turned on.

```js
async function initLiveData() {
  if (!LIVE_MODE) return;
  const [timeline, signals, perf, portSummary] = await Promise.all([
    fetchTimeline(), fetchSignals(), fetchPerformance(), fetchPortfolioSummary()
  ]);
  applyRegime(timeline);           // body background color
  bindGoalScreen(perf);            // s1
  bindMarketScreen(signals, portSummary);   // s2
  bindSignalHero(signals, portSummary);     // s3
  bindStrategyScreen(perf, events);         // s4 (events fetched separately)
  bindTodayScreen(timeline, signals, portSummary, perf);   // s5
  bindOverviewScreen(timeline, signals, portSummary, perf); // s6
  bindMarketFeedScreen(timeline, signals);  // s7
  const [positions, priceHistory] = await Promise.all([fetchPositions(), fetchPriceHistory()]);
  bindPortfolioScreen(positions, portSummary, priceHistory); // s8
}
```

---

## 5. Regime Background Colors

```js
function applyRegime(timeline) {
  const regime = timeline[timeline.length - 1].regime || '';
  const colors  = { Bull: '#EDFAF3', Bear: '#FFF7ED' };
  const color   = colors[regime] || '#FEFCE8';  // Neutral / unknown → light yellow
  document.body.style.backgroundColor = color;
}
```

| Regime | Color | CSS Variable |
|---|---|---|
| Bull | `#EDFAF3` | `--regime-bull` |
| Neutral (default) | `#FEFCE8` | `--regime-neutral` |
| Bear | `#FFF7ED` | `--regime-bear` |

Body has `transition: background-color 0.6s ease` for smooth regime transitions.

---

## 6. Signal Threshold Logic (Client-side)

Derived from the latest row of `GET /api/v1/market-signals?instrument=NIFTY&periods=5`:

```
Momentum   → rsi_14 > 60
Trend      → trend_score > 0.6
Volatility → atr_14 > average of last 5 rows' atr_14
Reversal   → bb_pct_b > 0.85 or bb_pct_b < 0.15
```

Display format: `"Momentum · Trend · 2 active"` — signal type labels only, no timestamps.

---

## 7. Gateway Hub Page (`mobileapp/gateway.html`)

**Added:** Feature 17 Phase 0 (2026-05-26)

A standalone HTML-only entry page served at `GET /mobile`. Acts as a universal hub linking users to the correct RITA app for their device context. No JavaScript, no UA detection — pure static HTML + inline CSS.

### Route

| Attribute | Value |
|---|---|
| Method | GET |
| Path | `/mobile` |
| Handler | `def mobile()` in `src/rita/main.py` |
| Response type | `FileResponse` |
| File served | `mobileapp/gateway.html` |
| Auth required | No |
| `include_in_schema` | `False` |
| Route placement | BEFORE `app.mount("/mobileapp", ...)` static mount |

### App Cards

| DOM ID | Destination | Type | Colour accent |
|---|---|---|---|
| `card-rita` | `/mobileapp` | Mobile Ready | Green |
| `card-onboarding` | `/onboarding` | Mobile Ready | Green |
| `card-ops` | `/mobileapp/ops.html` | Mobile Ready (Section 19) | — |
| `card-fno` | `/mobileapp/fno.html` | Mobile Ready (Section 18) | — |
| `card-ds` | `/mobileapp/ds.html` | Mobile Ready (Section 20) | — |
| `footer-desktop-link` | `/dashboard` | Footer escape-hatch | — |

> Updated 2026-06: the fno/ops/ds cards originally linked to the desktop dashboards with `?desktop=1` ("Desktop Only", amber). All three now have dedicated mobile PWAs and link to them directly. Do not revert to `?desktop=1` links.

### Design Rules

- CSS tokens: same `:root` block as `mobileapp/index.html` (`--bg`, `--surface`, `--build`, `--warn`, `--fd`, `--fm`, `--fs`)
- Layout: 2-column card grid ≥ 400 px; single column < 400 px (`@media (max-width: 399px)`)
- Page shell: `max-width: 600px` centred
- Mobile Ready cards: green accent bar + filled green CTA button "Open App →"
- Desktop Only cards: amber accent bar + text link "Open anyway ↗" + muted `surface2` background
- No `<script>` tags anywhere in `gateway.html`
- All CSS inline — no external stylesheet references

### Agent Directives (Phase 0)

1. Do not add `<script>` tags to `gateway.html` in any phase.
2. ~~Do not add UA detection or redirect logic to `main.py` in Phase 0.~~ **Lifted in Phase 1** — see Section 8 below.
3. `?desktop=1` query param on desktop links is a convention — no server-side handler is required in Phase 0.
4. The `/mobile` route must remain registered BEFORE the `/mobileapp` static mount in `main.py` to prevent route shadowing.

---

## 8. Mobile Detection — Phase 1 (`root()` UA Check + Dashboard JS Snippet)

**Added:** Feature 17 Phase 1 (2026-05-26)

Phase 1 adds automatic mobile redirection in two layers:
1. **Server-side UA check** in the `root()` handler (`GET /`) — mobile UAs are redirected to `/mobile` instead of `/dashboard`.
2. **Client-side inline IIFE snippet** inserted as the first `<script>` inside `<head>` on all 5 desktop dashboard HTML files — catches users who arrive directly at a dashboard URL via bookmark or link.

### Server-Side UA Detection (`main.py`)

```python
import re
from fastapi import Request

_MOBILE_UA_RE = re.compile(r"Android|iPhone|iPod|BlackBerry|IEMobile|Opera Mini", re.IGNORECASE)

@app.get("/", include_in_schema=False)
def root(request: Request):
    ua = request.headers.get("user-agent", "")
    if _MOBILE_UA_RE.search(ua):
        return RedirectResponse(url="/mobile", status_code=302)
    return RedirectResponse(url="/dashboard", status_code=302)
```

- Regex uses `re.IGNORECASE` and `.search()` (not `.match()`) — matches anywhere in the UA string.
- Desktop UA → `302 /dashboard` (no regression from Phase 0).
- Mobile UA → `302 /mobile` (gateway hub).

### Client-Side JS Snippet (Dashboard HTML Files)

Inserted as the first `<script>` immediately after `<meta name="viewport">` in `<head>`.

**Template (replace `APPNAME` with file-specific token):**

```html
<script>
(function(){
  var p = new URLSearchParams(location.search);
  if (p.get('desktop') === '1') { sessionStorage.setItem('mobileBypass','1'); return; }
  if (sessionStorage.getItem('mobileBypass') === '1') return;
  var mobile = /Android|iPhone|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
  var narrow = window.innerWidth < 768 && window.matchMedia('(pointer:coarse)').matches;
  if (mobile || narrow) location.replace('/mobile?from=APPNAME');
})();
</script>
```

**APPNAME token table:**

| File | APPNAME token |
|---|---|
| `riia-jun-release/dashboard/rita.html` | `rita` |
| `riia-jun-release/dashboard/fno.html` | `fno` |
| `riia-jun-release/dashboard/ops.html` | `ops` |
| `riia-jun-release/dashboard/ds.html` | `ds` |
| `riia-jun-release/dashboard/investgame.html` | `investgame` |

Note: `investgame_v2.html` and `users.html` are explicitly excluded from Phase 1.

### `?desktop=1` / `sessionStorage.mobileBypass` Escape-Hatch Convention

- Appending `?desktop=1` to any dashboard URL sets `sessionStorage.mobileBypass = '1'` and skips the redirect for the session.
- The `sessionStorage` key persists across tab navigation within the same browser session but resets when the tab/session closes (not `localStorage`).
- No server-side handler is required for `?desktop=1` — it is consumed entirely by the client-side snippet.
- The `?from=APPNAME` query param on `/mobile` redirects is informational — the `GET /mobile` handler silently ignores it (Phase 0 behaviour unchanged).

### Agent Directives (Phase 1)

1. The `_MOBILE_UA_RE` constant must be defined at module level in `main.py`, not inside `root()`.
2. Always use `.search()` not `.match()` — `.match()` only checks the start of the string and will miss UA strings with a prefix.
3. The JS snippet must be the first `<script>` in `<head>` — place it immediately after the `<meta name="viewport">` line.
4. The snippet is a synchronous IIFE — it is NOT registered in `main.js` and NOT a JS module.
5. `investgame_v2.html` and `users.html` are excluded — do not add the snippet to those files.

---

## 10. Screen Binding Functions

| Function | Source data | DOM bindings |
|---|---|---|
| `bindGoalScreen(perf)` | `performance-summary` | YTD % text, radial ring dashoffset, Sharpe, Win Rate |
| `bindMarketScreen(signals, portSummary, timeline)` | `market-signals`, `portfolio/summary`, `risk-timeline` | Regime label (`s2-regime-label`), price hero (`s2-price-hero`, `s2-price-change`), Signal Hero (s3) — KPI grid populated separately by `loadMsSignals()` |
| `bindSignalHero(signals, portSummary)` | `market-signals`, `portfolio/summary` | Confidence, regime, instrument, signal headline |
| `bindStrategyScreen(perf, events)` | `performance-summary`, `trade-events` | P&L, Win Rate, Sharpe, last 4 trade decisions |
| `bindTodayScreen(timeline, signals, portSummary, perf)` | all 4 | Date string, regime card, NIFTY price, signal type rows |
| `bindOverviewScreen(...)` | all 4 | Market hero price, goal bar, signal previews |
| `bindMarketFeedScreen(timeline, signals)` | timeline, signals | Regime pill, factor bars, narrative paragraph |
| `bindPortfolioScreen(positions, portSummary, priceHistory)` | positions, summary, history | Total value, daily gain, holdings list, sparklines |

---

## 11. Factor Bar Mapping

Market screen (s2) and Market Feed (s7) use 4 factor bars derived from the latest `market-signals` row:

```
Momentum bar  = rsi_14 / 100
Value bar     = 1 - bb_pct_b          (low BB position = value)
Quality bar   = trend_score            (normalized to [0,1])
Volatility bar = atr_14 / close_price  (normalized, capped at 1)
```

---

## 12. Sparkline Generation

Portfolio holdings (s8) use SVG polylines derived from `price-history` data:

```js
function pricesToPolyline(prices, w=200, h=60) {
  const min = Math.min(...prices), max = Math.max(...prices);
  return prices.map((p, i) =>
    `${(i/(prices.length-1)*w).toFixed(1)},${(h - (p-min)/(max-min)*h).toFixed(1)}`
  ).join(' ');
}
```

---

## 13. Live Toggle

DOM: `#liveToggle` (42×24px rounded div) + `#liveToggleKnob` + `#liveStatusDot`

```js
function toggleLiveMode() {
  LIVE_MODE = !LIVE_MODE;
  localStorage.setItem('ritaLiveMode', LIVE_MODE);
  updateToggleUI();
  if (LIVE_MODE) initLiveData();
  else document.body.style.backgroundColor = '';  // reset to CSS --bg
}
function updateToggleUI() {
  // Green (#1A6B3C) when ON, grey (#D0CBBC) when OFF
  // Knob slides: translateX(18px) ON, translateX(0) OFF
  // Dot: #4ADE80 (green) ON, #B8B2A6 (grey) OFF
}
// On load: updateToggleUI() to reflect persisted state
```

---

## 14. Trade Decisions List (Strategy screen s4)

Source: `GET /api/v1/trade-events` — last 4 entries displayed as:
```
{date (no time)} · {event_type} · {instrument}
```
Example: `"24 Apr · entry · NIFTY"`

---

## 15. PWA Files

| File | Purpose |
|---|---|
| `index.html` | App — all HTML, CSS, JS |
| `manifest.json` | PWA metadata (name, icons, theme_color, display=standalone) |
| `sw.js` | Service worker — offline caching |
| `icons/icon.svg` | Source icon (vector) |
| `icons/generate-icons.html` | Helper to generate PNG icons from SVG |

---

## 16. Integration Status

All 10 integration steps are complete:

| Step | Description | Status |
|---|---|---|
| 1 | CSS regime color tokens + body transition | Done |
| 2 | Config block + API client module | Done |
| 3 | Regime fetch + body background color | Done |
| 4 | Live toggle switch on Home screen | Done |
| 5 | Goal screen (s1) data binding | Done |
| 6 | Market (s2) + Signal Hero (s3) data binding | Done |
| 7 | Today (s5) + Overview (s6) data binding | Done |
| 8 | Market Feed (s7) data binding | Done |
| 9 | Strategy screen (s4) data binding | Done |
| 10 | Portfolio (s8 + overlay) + sparklines | Done |

---

## 17. AI Agent Directives

1. **Single file** — all changes go into `index.html`. No new `.js` or `.css` files.
2. **Fallback required** — every API binding must check `if (!data) return` before accessing fields.
3. **No new APIs** — use only existing backend endpoints listed in Section 3.
4. **`API_BASE` constant** — never hardcode the URL in individual functions; always prefix with `API_BASE`.
5. **`LIVE_MODE` check** — never call API functions if `LIVE_MODE` is false; respect the toggle.
6. **SVG sparklines** — use `pricesToPolyline()` helper, not Chart.js (too heavy for mobile).
7. **Factor bars** — use the threshold mapping in Section 8 exactly; do not invent new signal logic.
8. **No timestamps on signals** — display signal type labels only (e.g. "Momentum · Trend").

---

## 18. FnO Mobile App (`mobileapp/fno.html`)

**Added:** 2026-06-09

Single-file mobile PWA for the FnO portfolio tracker. Follows the same carousel + tab-bar pattern as `ops.html`.

### Route

Served statically from `/mobileapp/fno.html` via the existing `app.mount("/mobileapp", ...)` static mount. No new route required.

### Accent Colour

`--fno: #6B2FA0` (purple) — same as `--mon` in gateway.html token set.

### 5 Screens

| ID | Tab | Content |
|---|---|---|
| s0 | Overview | Unrealized P&L hero, Realized P&L + Open Positions + Margin KPIs, market prices grid, Real/Mock mode toggle |
| s1 | Positions | Per-underlying P&L KPI strip, position cards (instrument, FUT/CE/PE badge, Long/Short badge, P&L, expiry, qty, LTP) |
| s2 | Risk | Net Greeks per underlying (Δ Delta, Γ Gamma, Θ Theta/day, V Vega) as stat rows; Margin SPAN + Exposure + Total + utilization progress bar |
| s3 | Scenarios | R/R scenario levels per instrument (Bull Target/SL, Bear Target/SL); Stress test table (−4% to +4%, computed client-side from Greeks × spot) |
| s4 | Hedge | Position hedge quality scores with progress bars; Realized P&L summary + last 5 closed positions |

### API

Single call at init and on Refresh / mode change:

```
GET /api/v1/experience/fno/portfolio-analytics?mode={real|mock}
```

Auth: `sessionStorage.getItem('auth_token')` → `Authorization: Bearer` header (falls back to `localStorage.getItem('rita_token')`).

On 401 → redirects to `/`. On any other error → shows inline error messages; app does not crash.

### Agent Directives

1. Single file — all changes go into `fno.html`. No external JS or CSS files.
2. All rendering functions receive the full API response object (`data`) — no global state variable.
3. Stress scenarios are computed client-side: `Σ(delta × spot × move)` across all Greeks rows.
4. Scenario levels arrive pre-normalised as `{bull: {target, sl}, bear: {target, sl}}` — do not re-normalise.
5. Margin `summary['ALL']` is the all-instruments aggregate; `ledger` defaults to `3500000` when absent.
6. `gateway.html` card `#card-fno` now points to `/mobileapp/fno.html` — do not revert to `?desktop=1` link.

---

## 19. Ops Mobile App (`mobileapp/ops.html`)

**Added:** 2026-06-03 (~684 lines)

Single-file mobile PWA for the Operations portal. Carousel + tab-bar pattern (5 screens `s0`–`s4`, `goTo(idx)` switcher) — this is the pattern the FnO and DS mobile apps follow. Accent: `--ops: #0E7490` (teal). Client-side errors are reported via `POST /api/v1/client-error`.

### Route

Served statically from `/mobileapp/ops.html` via the existing `app.mount("/mobileapp", ...)` static mount. Linked from `gateway.html` card `#card-ops`.

### 5 Screens

| ID | Tab | Content |
|---|---|---|
| s0 | Overview | System health summary — API metrics summary + recent MCP calls |
| s1 | Monitoring | API latency / error-rate metrics from `/api/experience/ops/metrics/summary` |
| s2 | Deploy | GitHub deploy runs from `/api/experience/ops/github-deploys` |
| s3 | Agents | Agent build runs from `/api/experience/ops/agent-builds` |
| s4 | Activity | Pipeline progress + step log (`/progress` + `/api/experience/ops/step-log`) |

### Agent Directives

1. Single file — all changes go into `ops.html`. No external JS or CSS files.
2. Reuse the existing `apiFetch()` helper for all API calls.

---

## 20. DS Lab Mobile App (`mobileapp/ds.html`)

**Added:** 2026-06-08 (`c84b3dd`, ~947 lines)

Single-file mobile PWA for the Data Scientist Lab. Same carousel + tab-bar pattern as `ops.html` (5 screens, `goTo(idx)`). Accent: `--ds: #0E7490` (teal). Client-side errors are reported via `POST /api/v1/client-error`.

### Route

Served statically from `/mobileapp/ds.html`. Linked from `gateway.html` card `#card-ds`.

### 5 Screens

| ID | Tab | Content |
|---|---|---|
| s0 | Overview | Last build KPIs from `/api/v1/performance-summary` + backtest daily + training history |
| s1 | Perf | Performance charts/tables from `/api/v1/experience/rita/backtest-daily` + training history |
| s2 | Trades | Trade journal from `/api/v1/trade-events` |
| s3 | Model | Round-by-round training history from `/api/v1/experience/rita/training-history` |
| s4 | Risk | Risk timeline + trade risk from `/api/v1/experience/rita/risk-timeline` + `/api/v1/trade-events` |

### Agent Directives

1. Single file — all changes go into `ds.html`. No external JS or CSS files.
2. Reuse the existing `apiFetch()` helper for all API calls.
