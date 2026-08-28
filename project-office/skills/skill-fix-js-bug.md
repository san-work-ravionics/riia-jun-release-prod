# Skill: Fix JS Frontend Bug

**Guardrail refs:** org · engineer-role · rita-project  
**Last validated against spec:** 2026-05-26  
**Spec source:** `Spec_JS_Code.md` + `Spec_HTML_Code.md`

## When to use this skill
Use when a defect is reported from manual testing of the RITA dashboard (`rita.html`, `fno.html`, `ops.html`). Covers diagnosing and fixing bugs in `dashboard/js/` ES modules.

**Do NOT start the server to reproduce bugs.** Trace from source code only — starting a server wastes tokens and time.

---

## Module Map — Find the Right File Fast

### `dashboard/js/rita/` — main dashboard

| File | Owns | Key functions |
|---|---|---|
| `health.js` | Home KPI strip, model status | `loadHealth()`, `loadMetrics()`, `loadPerfSummary()`, `loadDrift()` |
| `market-signals.js` | Market Signals section + tabs | `loadMarketSignals()`, `switchMsTab(tf)` |
| `trades.js` | Trade Journal | `loadTrades()`, `downloadTradeJournal()` |
| `observability.js` | Ops monitoring panel | `loadObservability()` |
| `scenarios.js` | Backtest scenario runner | `loadScenarios()`, `runScenarioBacktest()` |
| `export.js` | Pipeline step buttons | `runGoal()`, `runMarket()`, `runStrategy()` |
| `pipeline.js` | Pipeline result renderers | `renderGoalResult()`, `renderMarketResult()`, `renderStepResult()` |
| `performance.js` | Performance analytics | `loadPerformance()` |
| `risk.js` | Live risk view | `loadRisk()` |
| `training.js` | Training progress | `loadTrainProgress()` |
| `chat.js` | Chat assistant | `sendChatMsg()`, `useChip()` |
| `nav.js` | Section navigation | `show(section)`, `_sectionLoaders` map |
| `main.js` | Entry point, wires all | `_sectionLoaders` registrations, `window.*` bindings |
| `utils.js` | DOM helpers | `setEl(id, html)`, `badge(status)`, `fmt(v, dec)`, `fmtPct(v)` |
| `charts.js` | Chart registry | `mkChart(id, config)`, `destroyChart(id)`, `C` (color palette) |
| `api.js` | HTTP client | `api(path, method?, body?)` |

---

## Trace Protocol — 5 Steps

Work through these in order. Stop when you find the root cause.

### Step 1 — Identify the broken section and its loader
From the bug report, identify which `<section id="sec-X">` is broken.  
The loader for section `X` is registered in `main.js` as `_sectionLoaders['X'] = loadX`.  
Open that loader's JS file.

### Step 2 — Find the API call
In the loader function, locate the `await api('/api/v1/...')` call.  
Note the exact URL and the fields the code reads from the response:
```js
const data = await api('/api/v1/some-endpoint');
setEl('some-id', data.fieldName);   // ← note 'fieldName'
```

### Step 3 — Read the API handler (not the full file — search for the route)
Grep for the endpoint path in `src/rita/api/`:
```
grep -r "some-endpoint" src/rita/api/
```
Open the handler. Check what it `return`s. Confirm every field the JS reads is present.

### Step 4 — Trace to DOM element
Find every `setEl('id', ...)` call in the loader.  
Grep the HTML file for each `id`:
```
grep -n "id=\"some-id\"" dashboard/rita.html
```
A silent miss (no error, no content) almost always means the element id in JS doesn't match the one in HTML.

### Step 5 — Identify the root cause category
| Symptom | Likely cause |
|---|---|
| Section renders blank, no console error | Wrong element id in `setEl()` call |
| KPI shows `—` or `NaN` | Field missing from API response, or `parseFloat(null)` |
| Chart is empty | `mkChart` called before data loads, or canvas id mismatch |
| Button does nothing | Function not bound on `window.*` in `main.js` |
| Section never loads | Loader not registered in `_sectionLoaders` |
| All KPIs show `—` after nav | Section loader fires only once — stale state, call loader directly |
| API call succeeds but data wrong | Query param echoed as field value; or wrong endpoint for the section |

---

## Known Gotchas (do not repeat these)

| Gotcha | Detail |
|---|---|
| `phases` in `trades.js` | Must be `const phases = Object.keys(TJ_PHASE)` before the `.map()` call — undeclared `phases` throws `ReferenceError`, caught silently, both chart and table blank |
| `macd_signal` vs `macd_signal_line` | `GET /api/v1/market-signals` returns `macd_signal` (number). `POST /api/v1/market` returns `macd_signal_line` (number) + `macd_signal` (string label). Do not swap them. |
| `settings` vs `get_settings()` | In Python, always call `get_settings()` — never bare `settings` at module level. Bare name → `NameError` → endpoint returns `[]` → all KPIs show `—`. |
| Chart title hardcoded | `#ms-pv-subtitle` is updated dynamically in `loadMarketSignals()`. Never hardcode timeframe words in HTML. |
| `mkChart` always recreates | Never patch an existing Chart.js instance. Always call `mkChart(id, fullConfig)` — it destroys and recreates. |
| Section loaders fire once | `nav.js` fires the loader on first visit only. To force a reload, call the loader function directly. |

---

## JS-Specific Fix Rules

**`parseFloat(null)` trap:**
```js
// Wrong — parseFloat(null) → NaN; NaN.toFixed() renders "NaN" in UI
setEl('id', parseFloat(data.value).toFixed(2));

// Correct
setEl('id', data.value !== null ? parseFloat(data.value).toFixed(2) : '—');
```

**Silent catch trap:**
```js
// Wrong — swallows all errors, section stays blank with no signal
try { ... } catch (_) {}

// Correct
try { ... } catch (e) { console.warn('[module] load failed', e); }
```

**`window.*` binding (required for all HTML onclick handlers):**
```js
// In main.js — required for every function called from HTML onclick=""
window.myFunction = myFunction;
```

**Adding a new section — checklist:**
1. `<section id="sec-NAME">` in the HTML file
2. Loader function in the correct JS module file
3. `_sectionLoaders['NAME'] = loadName` in `main.js`
4. `window.loadName = loadName` in `main.js` (if refresh button exists)

---

## What NOT to Do

- Do not start `uvicorn` or `python start.py` to reproduce the bug
- Do not `curl` endpoints — read the handler's `return` dict from the source
- Do not refactor surrounding code while fixing a bug
- Do not add error handling for cases that cannot happen
- Do not read `rita.html` / `fno.html` / `ops.html` in full — they are 2,900–4,000 lines; use targeted `grep` for the element id you need

---

## Definition of Done

- [ ] Root cause identified by tracing code — not by running the server
- [ ] Fix is the minimum targeted change (one function, one condition, one guard)
- [ ] Every `setEl(id, ...)` call has a matching element `id` confirmed in the HTML
- [ ] Every field read from API response is confirmed present in the handler's `return` dict
- [ ] Any new `window.*` binding added to `main.js` if a new onclick handler was introduced
- [ ] `specs/Spec_JS_Code.md` "Known Gotchas" section updated if this was a new class of bug
- [ ] **After committing static JS/HTML changes**: tell the user to hard-refresh (`Cmd+Shift+R` on Mac, `Ctrl+Shift+R` on Windows) to clear the browser cache — the fix is on disk but browsers may serve the old cached file for minutes to hours
