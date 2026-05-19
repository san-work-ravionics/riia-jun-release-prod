python -m http.server 8080


# RITA Mobile App — Live Data Integration Plan

**File:** `android-mobile-app/index.html` (1,311 lines, single-file PWA)
**Backend base URL:** `http://localhost:8000` (hardcoded constant — change when deploying)
**Fallback rule:** Every API call silently falls back to existing hardcoded DOM values on failure. App never breaks.
**Confirm-per-step:** Wait for user go-ahead before starting each step.

---

## Design Decisions (locked)

| Decision | Detail |
|---|---|
| No new APIs | Use only existing backend endpoints |
| Regime source | `GET /api/v1/risk-timeline` → last array entry → `.regime` string |
| Signal source | `GET /api/v1/market-signals?instrument=NIFTY` → latest row → threshold-derived types |
| No timestamps | Signal recency ("14 min ago") is removed — informational only |
| Home screen | Hardcoded for now — user will redesign later |
| Chat overlay | Stays hardcoded — no backend chat API |
| Regime background colors | Bull = `#EDFAF3` (light green), Neutral = `#FEFCE8` (light yellow), Bear = `#FFF7ED` (light amber) |

---

## API Calls Used (5 total)

| Call | Endpoint | Used in screens |
|---|---|---|
| `fetchTimeline()` | `GET /api/v1/risk-timeline` | Regime color (all), s5, s7 |
| `fetchSignals()` | `GET /api/v1/market-signals?instrument=NIFTY&periods=5` | s2, s3, s5, s6, s7 |
| `fetchPerformance()` | `GET /api/v1/performance-summary` | s1, s4 |
| `fetchPortfolioSummary()` | `GET /api/v1/portfolio/summary` | s2, s5 |
| `fetchPositions()` | `GET /api/v1/portfolio/positions?mode=paper` | s8 |
| `fetchPriceHistory()` | `GET /api/v1/portfolio/price-history?periods=30` | sparklines s8 |

---

## Signal Threshold Logic (client-side, no new API)

From the latest row of `/api/v1/market-signals`:

```
Momentum  → rsi_14 > 60
Trend     → trend_score > 0.6
Volatility→ atr_14 > atr rolling average (computed from last 5 rows)
Reversal  → bb_pct_b > 0.85 or bb_pct_b < 0.15
```

Display: signal type labels only (e.g. "Momentum · Trend · 2 active"). No timestamps.

---

## Step Breakdown

### STEP 1 — CSS: Regime background color tokens + transition  ☐
**File:** `index.html` — `<style>` block, `:root` section (lines 22–53)
**What:** Add 3 new CSS variables and a transition rule on `body`.
```css
--regime-bull:    #EDFAF3;   /* light green  */
--regime-neutral: #FEFCE8;   /* light yellow */
--regime-bear:    #FFF7ED;   /* light amber  */
```
Add `transition: background-color 0.6s ease;` to `html, body` rule (line 56–62).
The `--bg` token stays unchanged; regime color is applied separately to `body` via JS.
**Test:** Manually set `document.body.style.backgroundColor = '#EDFAF3'` in console — verify smooth fade.
**No API call in this step.**

---

### STEP 2 — JS: Config block + API client module  ☐
**File:** `index.html` — `<script>` block, insert before `// ── Navigation ──` (before line 1229)
**What:** Add two sections at the top of the script block:
1. **Config constants** — `API_BASE`, `LIVE_MODE` (reads localStorage)
2. **API client** — 6 async functions, each wrapping `fetch()` with a try/catch that returns `null` on failure

```js
// ── Config ──────────────────────────────────────────────────────────
const API_BASE  = 'http://localhost:8000';
let   LIVE_MODE = localStorage.getItem('ritaLiveMode') === 'true';

// ── API client (all return null on failure — callers check before using) ──
async function fetchTimeline()        { try { const r = await fetch(`${API_BASE}/api/v1/risk-timeline`);        return r.ok ? r.json() : null; } catch { return null; } }
async function fetchSignals()         { try { const r = await fetch(`${API_BASE}/api/v1/market-signals?instrument=NIFTY&periods=5`); return r.ok ? r.json() : null; } catch { return null; } }
async function fetchPerformance()     { try { const r = await fetch(`${API_BASE}/api/v1/performance-summary`);  return r.ok ? r.json() : null; } catch { return null; } }
async function fetchPortfolioSummary(){ try { const r = await fetch(`${API_BASE}/api/v1/portfolio/summary`);   return r.ok ? r.json() : null; } catch { return null; } }
async function fetchPositions()       { try { const r = await fetch(`${API_BASE}/api/v1/portfolio/positions?mode=paper`); return r.ok ? r.json() : null; } catch { return null; } }
async function fetchPriceHistory()    { try { const r = await fetch(`${API_BASE}/api/v1/portfolio/price-history?periods=30`); return r.ok ? r.json() : null; } catch { return null; } }
```

**Test:** Open browser console, call `fetchTimeline()` — verify it returns data or null gracefully.

---

### STEP 3 — JS: Regime fetch + body background color  ☐
**File:** `index.html` — `<script>` block, new function after API client
**What:** Add `applyRegime(timeline)` function + call it in `initLiveData()`.

```js
function applyRegime(timeline) {
  if (!timeline || !timeline.length) return;
  const regime = timeline[timeline.length - 1].regime || '';
  const colors  = { Bull: '#EDFAF3', Bear: '#FFF7ED' };
  const color   = colors[regime] || '#FEFCE8';   // Neutral / unknown → yellow
  document.body.style.backgroundColor = color;
}
```

`initLiveData()` is the master coordinator function added in this step:
```js
async function initLiveData() {
  if (!LIVE_MODE) return;
  const [timeline, signals, perf, portSummary] = await Promise.all([
    fetchTimeline(), fetchSignals(), fetchPerformance(), fetchPortfolioSummary()
  ]);
  applyRegime(timeline);
  // subsequent steps add more calls here
}
```

Call `initLiveData()` just before `goTo(0)` at bottom of script.
**Test:** Toggle live mode in console (`LIVE_MODE=true; initLiveData()`), verify body color changes.

---

### STEP 4 — HTML + JS: Live toggle switch on Home screen (s0)  ☐
**File:** `index.html` — Home screen markup (around line 252, after the avatar row)
**What:** Insert a small toggle row between the greeting header and the RITA SAYS banner.

HTML to insert (after line 252):
```html
<!-- Live toggle -->
<div style="padding:10px 22px 0;display:flex;align-items:center;gap:10px;">
  <div id="liveToggle" onclick="toggleLiveMode()"
       style="width:42px;height:24px;border-radius:12px;background:#D0CBBC;cursor:pointer;position:relative;transition:background 0.2s;flex-shrink:0;">
    <div id="liveToggleKnob" style="position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:9px;background:#fff;transition:transform 0.2s;box-shadow:0 1px 3px rgba(0,0,0,0.2);"></div>
  </div>
  <span style="font-family:var(--fm);font-size:10px;font-weight:600;color:var(--t3);letter-spacing:0.06em;">
    LIVE DATA <span id="liveStatusDot" style="display:inline-block;width:6px;height:6px;border-radius:3px;background:#B8B2A6;margin-left:4px;vertical-align:middle;"></span>
  </span>
</div>
```

JS to add in script block:
```js
function toggleLiveMode() {
  LIVE_MODE = !LIVE_MODE;
  localStorage.setItem('ritaLiveMode', LIVE_MODE);
  updateToggleUI();
  if (LIVE_MODE) initLiveData();
  else document.body.style.backgroundColor = '';  // reset to CSS --bg
}
function updateToggleUI() {
  const tog  = document.getElementById('liveToggle');
  const knob = document.getElementById('liveToggleKnob');
  const dot  = document.getElementById('liveStatusDot');
  tog.style.background  = LIVE_MODE ? '#1A6B3C' : '#D0CBBC';
  knob.style.transform  = LIVE_MODE ? 'translateX(18px)' : 'translateX(0)';
  dot.style.background  = LIVE_MODE ? '#4ADE80' : '#B8B2A6';
}
// Run on load to reflect persisted state
updateToggleUI();
```

**Test:** Tap toggle — verify visual state changes, localStorage persists on reload.

---

### STEP 5 — HTML + JS: Goal screen (s1) data binding  ☐
**Source:** `GET /api/v1/performance-summary`
**Response fields used:** `portfolio_total_return_pct`, `win_rate_pct`, `sharpe_ratio`
**What:**
1. Add `id` attributes to the YTD % text, the radial ring `stroke-dashoffset`, and the KPI cells in s1
2. Add `bindGoalScreen(perf)` function called from `initLiveData()`

Key bindings:
- YTD % text → `perf.portfolio_total_return_pct.toFixed(1) + '%'`
- Radial ring dashoffset → computed from return vs 10% goal
- Sharpe display if element exists → `perf.sharpe_ratio.toFixed(2)`
- Win rate display → `perf.win_rate_pct.toFixed(0) + '%'`

---

### STEP 6 — HTML + JS: Market screen (s2) + Signal Hero (s3) data binding  ☐
**Source:** `GET /api/v1/market-signals?instrument=NIFTY&periods=5`, `GET /api/v1/portfolio/summary`
**What:**
1. Add IDs to factor bars (Momentum, Value, Quality, Volatility) and price display in s2
2. Add IDs to confidence/regime/instrument fields in s3
3. Add `bindMarketScreen(signals, portSummary)` function

Factor bar mapping (latest signals row):
- Momentum bar → `rsi_14 / 100`
- Value bar → `(1 - bb_pct_b)` (inverted: low BB position = value)
- Quality bar → `trend_score`
- Volatility bar → normalized `atr_14` (atr / close price, capped at 1)

Signal threshold detection (for s3 headline):
- Collect which thresholds fire → build headline text from active signals
- No timestamps shown

Price display in s2 → `portSummary.market.NIFTY.close` (or `nifty_spot`)

---

### STEP 7 — HTML + JS: Today (s5) + Overview (s6) data binding  ☐
**Source:** Already fetched (timeline, signals, portSummary, perf)
**What:**
1. Add IDs to date string, regime hero card, NIFTY price, signal type rows in s5
2. Add IDs to market hero price, goal bar, signal previews in s6
3. Add `bindTodayScreen(timeline, signals, portSummary, perf)` and `bindOverviewScreen(...)` functions

Date: use `new Date().toLocaleDateString('en-GB', {weekday:'short', day:'numeric', month:'short'}).toUpperCase()`
Regime label: `timeline[last].regime`
NIFTY close: `portSummary.market.NIFTY.close`
Signal type list: derived from thresholds (Step 6 logic reused)

---

### STEP 8 — HTML + JS: Market Feed (s7) data binding  ☐
**Source:** timeline, signals
**What:**
1. Add IDs to regime pill, factor bars, regime narrative paragraph in s7
2. Add `bindMarketFeedScreen(timeline, signals)` function

Regime pill → `timeline[last].regime`
Factor bars → same mapping as s2 (Step 6)
Narrative → client-side template:
```js
`${regime} market · Trend score ${(trend_score*100).toFixed(0)}. RSI at ${rsi_14.toFixed(0)}.`
```

---

### STEP 9 — HTML + JS: Strategy screen (s4) data binding  ☐
**Source:** `GET /api/v1/performance-summary`, `GET /api/v1/trade-events`
**What:**
1. Add IDs to P&L, Win Rate, Sharpe, and decisions list in s4
2. Add `fetchTradeEvents()` API call (added to API client in Step 2 but called here)
3. Add `bindStrategyScreen(perf, events)` function

Sharpe → `perf.sharpe_ratio.toFixed(2)`
Win rate → `perf.win_rate_pct.toFixed(0) + '%'`
P&L → derived from perf or portfolio summary
Decisions list → last 4 `trade-events` entries: date + event_type + instrument (no intraday time)

`fetchTradeEvents()` added to API client:
```js
async function fetchTradeEvents() { try { const r = await fetch(`${API_BASE}/api/v1/trade-events`); return r.ok ? r.json() : null; } catch { return null; } }
```

---

### STEP 10 — HTML + JS: Portfolio screen (s8 + overlay) + sparklines  ☐
**Source:** `GET /api/v1/portfolio/positions?mode=paper`, `GET /api/v1/portfolio/summary`, `GET /api/v1/portfolio/price-history?periods=30`
**What:**
1. Add IDs to total value, daily gain, and holdings list in s8 and portfolio-overlay
2. Replace hardcoded SVG sparklines with data-driven polylines
3. Add `bindPortfolioScreen(positions, portSummary, priceHistory)` function

Total value → sum of `positions[].qty * positions[].ltp` or from `portSummary.total_pnl`
Holdings list → render `positions` array: instrument, qty, ltp, pnl
Sparkline → scale `priceHistory[].close` values to SVG viewport (0–60 height, full width):
```js
function pricesToPolyline(prices, w=200, h=60) {
  const min = Math.min(...prices), max = Math.max(...prices);
  return prices.map((p, i) =>
    `${(i/(prices.length-1)*w).toFixed(1)},${(h - (p-min)/(max-min)*h).toFixed(1)}`
  ).join(' ');
}
```

---

## Status Tracking

| Step | Description | Status |
|---|---|---|
| 1 | CSS regime color tokens + body transition | ✅ Done |
| 2 | Config block + API client module | ✅ Done |
| 3 | Regime fetch + body background color logic | ✅ Done |
| 4 | Live toggle switch UI on Home screen | ✅ Done |
| 5 | Goal screen (s1) data binding | ✅ Done |
| 6 | Market (s2) + Signal Hero (s3) data binding | ✅ Done |
| 7 | Today (s5) + Overview (s6) data binding | ✅ Done |
| 8 | Market Feed (s7) data binding | ✅ Done |
| 9 | Strategy screen (s4) data binding | ✅ Done |
| 10 | Portfolio (s8 + overlay) + sparklines | ✅ Done |

---

## Session Resume Instructions

If tokens are exhausted, start next session with:
> "Resume mobile integration from MOBILE_INTEGRATION_PLAN.md — start at Step N"

The plan file is at:
`C:\Users\Sandeep\Documents\Work\code\riia-cowork-jun\rita-build-portfolio\android-mobile-app\MOBILE_INTEGRATION_PLAN.md`
