# Skill: Add DS Dashboard Feature
**App:** Data Science dashboard (`ds.html` + `dashboard/js/ds/`)
**Use for:** New UI sections, panels, module extraction, or data views in the DS data science dashboard
**Compiled from:** `Spec_RITA_App.md` + `Spec_JS_Code.md`
**Guardrail refs:** org · engineer-role · rita-project  
**Last validated against spec:** 2026-05-26

---

## App Identity

| Item | Value |
|---|---|
| HTML file | `riia-jun-release/dashboard/ds.html` — large file. **Never read directly.** Use spec. |
| JS module dir | `riia-jun-release/dashboard/js/ds/` — may not yet exist (created in Phase 4) |
| Primary API | Experience tier: `riia-jun-release/src/rita/api/experience/ds.py` |
| Secondary API | Workflow tier: `/api/v1/train`, `/api/v1/backtest`, `/api/v1/pipeline`, `/api/v1/shap` |
| Key tables | `training_history`, `backtest_results`, `risk_metrics`, `trades` |
| Spec file | `project-office/specs/Spec_RITA_App.md` |
| JS Spec file | `project-office/specs/Spec_JS_Code.md` |

---

## DS Architecture Note (Critical for Phase 4)

**Current state:** `ds.html` uses inline `<script>` blocks — NOT ES modules. All JS logic lives inside `<script>` tags at the bottom of `ds.html`. There is no `dashboard/js/ds/` directory.

**Phase 4 target state:** Extract all inline scripts into `dashboard/js/ds/` modules. Replace all inline `<script>` blocks with a single `<script type="module" src="js/ds/main.js">`. The nav pattern (inline `show(section, el)`) moves to `ds/nav.js`.

**Section switching:** ds.html uses a direct DOM show/hide pattern via `show(section, el)`. After extraction, `ds/nav.js` will implement `show()` and export it; `ds/main.js` will assign `window.show = show`.

---

## DS Section Inventory (13 sections to extract)

| Section key (`data-s`) | Page title | Target module |
|---|---|---|
| `understand` | Understand Data | `ds/understand.js` |
| `dashboard` | Dashboard | `ds/dashboard.js` |
| `pipeline` | Pipeline | `ds/pipeline.js` |
| `performance` | Performance | `ds/performance.js` |
| `risk` | Risk View | `ds/risk.js` |
| `trades` | Trade Journal | `ds/trades.js` |
| `explain` | Explainability | `ds/explain.js` |
| `scenarios` | Portfolio Scenarios | `ds/scenarios.js` |
| `training` | Training Metrics | `ds/training.js` |
| `changelog` | Model Changelog | `ds/changelog.js` |
| `observability` | Observability | `ds/observability.js` |
| `mcp` | MCP Calls | `ds/mcp.js` |
| `export` | Export & DevOps | `ds/export.js` |

---

## File Map — What to Touch for a Typical DS Feature or Module Extraction

| Layer | File | What to do |
|---|---|---|
| **Backend** | `src/rita/api/experience/ds.py` | Add aggregated read-only payload (primary API for DS) |
| **Backend** | `src/rita/schemas/{name}.py` | Add Pydantic response schema |
| **Frontend** | `dashboard/js/ds/api.js` | Re-export from `../shared/api.js` (thin wrapper) |
| **Frontend** | `dashboard/js/ds/nav.js` | Section switching: `show(section, el)` + nav highlight |
| **Frontend** | `dashboard/js/ds/main.js` | Entry point: import all section loaders, wire `_sectionLoaders`, assign `window.show` |
| **Frontend** | `dashboard/js/ds/{section}.js` | One file per section — extracted from inline script |
| **HTML** | `ds.html` | Remove inline `<script>` blocks; add `<script type="module" src="js/ds/main.js">` |
| **Spec** | `project-office/specs/Spec_JS_Code.md` | Update Section 5 (ds/ module table) — change from "inline scripts" to ES module description |

---

## DS Experience API Reference (existing endpoints — do not add duplicates)

| Endpoint | Method | Returns |
|---|---|---|
| `/api/experience/ds` | GET | DS dashboard instruments + training history + split dates |

---

## Step-by-Step Task Rules

### Step 1 — Design First
Define before writing code:
- Endpoint: method + path + query params (or "n/a — JS-only refactor")
- Response shape: field names + types as a Pydantic schema (or "n/a")
- Frontend consumer: which JS module(s), which DOM element IDs

Write the contract in the task brief `[Architect] Design` section before proceeding.

### Step 2 — Choose the Right API Tier
- **Experience tier** (`experience/ds.py`): aggregated read-only payload for DS UI — primary choice
- **Workflow tier** (`/api/v1/train`, `/api/v1/backtest`, `/api/v1/pipeline`): trigger training/backtest runs
- **System tier**: only for raw CRUD; call via experience wrapper, never directly from JS

### Step 3 — Add the Backend Endpoint (if needed)

**Experience tier pattern:**
```python
@router.get("/api/experience/ds/my-feature", response_model=MyDsFeatureResponse)
def get_ds_my_feature(db: Session = Depends(get_db)):
    repo = MyRepo(db)
    data = repo.get_my_data()
    return MyDsFeatureResponse(items=data)
```

**Key rules:**
- Experience routes are read-only — never call `db.commit()`
- Use `load_nifty_csv()` or `load_instrument_data()` from `core/data_loader.py` for data files
- Never use bare `pd.read_csv()`

### Step 4 — Add the Pydantic Schema (if needed)
File: `src/rita/schemas/{name}.py`
- Match field names exactly to what the DS JS module will read

### Step 5 — Write the JS Module
File: `dashboard/js/ds/{section}.js`

**DS Module template (for extracted inline section):**
```js
import { api } from './api.js';
import { setEl, badge, fmt, fmtPct } from '../shared/utils.js';
import { mkChart, C } from '../shared/charts.js';

export async function loadMySection() {
  try {
    const data = await api('/api/experience/ds/my-feature');
    setEl('my-section-value', fmt(data.value, 2));
  } catch (e) {
    setEl('my-section-value', '—');
  }
}
```

**DS nav.js template:**
```js
export function show(section, el) {
  document.querySelectorAll('[data-s]').forEach(s => s.classList.add('d-none'));
  const target = document.querySelector(`[data-s="${section}"]`);
  if (target) target.classList.remove('d-none');
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
  if (el) el.classList.add('active');
}
```

**DS api.js template (thin re-export):**
```js
export { apiBase, api, apiFetch } from '../shared/api.js';
export const DS_API_KEY = '';
```

**DS main.js template:**
```js
import { show } from './nav.js';
import { loadUnderstand } from './understand.js';
// ... all section imports

const _sectionLoaders = {};
_sectionLoaders['understand'] = loadUnderstand;
// ... register all 13 sections

window.show = show;

// Auto-load first section on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  loadUnderstand();
});
```

**Rules:**
- Import `api` from `./api.js` — never raw `fetch()`
- Wrap API calls in `try/catch` — show `—` on error
- Use `setEl(id, html)` — never `document.getElementById(...).innerHTML`
- Use `mkChart(id, config)` — never `new Chart(...)`
- Use `C` color palette from `../shared/charts.js`
- Never use `window.RITA_API_BASE` hardcoded — always relative paths via `api()`

### Step 5.5 — FC-IMP Check: Verify Named Imports (run before Step 6)

> **Run this immediately after writing each JS module — before registering in main.js.**

For every `import { name1, name2 } from './module.js'` or `from '../shared/module.js'` line:
1. Open the source file and grep for `export` statements
2. Confirm each imported name appears as `export function name` or `export const name`
3. Report explicitly: "FC-IMP: [name1] ✓ in [module.js]" — one line per import

**Path depth rules for ds/ modules:**
- From `dashboard/js/ds/`: `'../shared/'` resolves to `dashboard/js/shared/` ✓
- From `dashboard/js/ds/`: `'../../shared/'` resolves to `dashboard/shared/` — WRONG (does not exist)

### Step 6 — Register in main.js
In `dashboard/js/ds/main.js`:
```js
import { loadMySection } from './my-section.js';
_sectionLoaders['my-section'] = loadMySection;
```

### Step 7 — Update ds.html (Phase 4 only)
**For Phase 4 (full extraction):** Replace ALL inline `<script>` blocks with one tag:
```html
<script type="module" src="js/ds/main.js"></script>
```

**Rules for HTML edits (never read the full file):**
- Use Grep to find the `</body>` or `<script>` tag near your insertion point
- Read ±20 lines around the match
- Use targeted Edit to replace/insert
- Skipping this step = FC-PARTIAL-IMPL

### Step 8 — Update the Spec

> **STOP — do not run `git add` until this step is complete.**

File: `project-office/specs/Spec_JS_Code.md` — Section 5:
- If creating `dashboard/js/ds/` for the first time: replace the "inline scripts" description with the ES module table (one row per module file)
- If adding a new module: add a row to the ds/ module table

File: `project-office/specs/Spec_RITA_App.md`:
- If a new experience endpoint was added: add a row to the experience tier table

Run grep to confirm the edit saved: `grep -n 'ds/' project-office/specs/Spec_JS_Code.md`

### Step 9 — TechWriter: Confluence + Human Score Prompt

After confirming spec files and updating Confluence, ask the user to run a smoke test:

> **Smoke-test gate:** "Please open the DS dashboard (`/dashboard/ds.html`) in a browser and verify all 13 sections load without JavaScript console errors. Open DevTools → Console and confirm no `SyntaxError`, `Cannot resolve module`, or `is not exported` errors appear. Report: page loads OK / page broken."
>
> If the user reports a runtime error: do NOT emit the scoring prompt. Investigate and fix the error first. Only emit after the user confirms the page loads cleanly.

Once the user confirms, emit the scoring prompt:

```
=== Agent Run Complete — Please score this run ===
Output accuracy (1–5, where 5 = exactly what was needed): _
Relevance to stated intent (1–5): _
Did PM + Architect decompose the task correctly first time? (y/n): _
Overall satisfaction / CSAT (1–5): _
Estimated hours this would have taken manually: _
Press Enter to skip any field.
=========================================
```

Record responses as `human_score{}` in the run JSON.

---

## Guardrails

| Rule | Detail |
|---|---|
| Never read `ds.html` directly | File is large. Use Grep + targeted Edit only. |
| Never call `db.commit()` in Experience tier | Experience routes are read-only |
| Never use bare `pd.read_csv()` | Use `load_nifty_csv()` or `load_instrument_data()` |
| Never add `print()` statements | Use `structlog` |
| Never hardcode `http://localhost:8000` in JS | Use relative paths via `api()` |
| HTML changes are required when Architect lists ds.html | "Never read ds.html" = no full-file Read. Use Grep → read ±20 lines → targeted Edit. Skipping = FC-PARTIAL-IMPL. |
| **Alembic migration must be applied, not just created** | Run `python -m alembic upgrade head` from `riia-jun-release/` and confirm `Running upgrade` line before committing. Hard DoD gate. |
| Never call `new Chart(...)` directly | Use `mkChart(id, config)` from `../shared/charts.js` |
| Never expose ES module functions without `window.*` | `onclick=""` handlers silently fail |
| Always update spec when contract changes | Spec drift breaks future agents |
| DS section keys must not duplicate RITA section keys | Use `model-` prefix for planned new sections (model-observability, model-mcp, etc.) |
| **Never call banned system-tier endpoints from DS JS — FC-TIER gate** | These paths are banned in DS JS modules: `/api/v1/training-history` (use `/api/v1/experience/rita/training-history`), `/api/v1/backtest-daily` (use `/api/v1/experience/rita/backtest-daily`), `/api/v1/risk-timeline` (use `/api/v1/experience/rita/risk-timeline`). Run self-verify grep before `git add`: `grep -rn "api/v1/training-history\|api/v1/backtest-daily\|api/v1/risk-timeline" dashboard/js/ds/` — must return empty. |
| **`api()` POST signature is positional — FC-API-SIG gate** | Correct: `api(path, 'POST', bodyObject)`. Wrong: `api(path, { method: 'POST', body: ... })`. The second argument is the HTTP method string, not a fetch options object. Passing an object silently breaks all POST operations (instrument select, pipeline run, scenario backtest). |

---

## Definition of Done

**FC-004 gate — verify before committing:**
List every `data.field` or `r.field` access in new/changed JS modules. Confirm exact field name exists in Pydantic schema or response dict. Single character difference causes silent render failure.

**FC-IMP gate — JS named-import resolution:**
For every `import { name }` in new/modified JS files, confirm the name is actually exported from the source module. SyntaxError at parse time kills the entire ds module tree.

**FC-TIER gate — system-tier API compliance (run before `git add`):**
Run: `grep -rn "api/v1/training-history\|api/v1/backtest-daily\|api/v1/risk-timeline" dashboard/js/ds/`
Output must be empty. Any match = banned system-tier call. Replace with the correct experience-tier path before committing.

**FC-API-SIG gate — api() POST signature (run before `git add`):**
Run: `grep -rn "api(.*{" dashboard/js/ds/`
Output must show zero instances of `api(path, {` patterns. All POST calls must use positional form: `api(path, 'POST', body)`.

**FC-MERGE gate:**
Run: `grep -rn "^<<<<<<\|^=======\|^>>>>>>>" dashboard/js/ds/`
Output must be empty.

- [ ] **API contract matches** — schema field names match JS `data.field` reads (or "n/a — JS-only refactor")
- [ ] **Correct tier used** — Experience tier for read-only aggregation; Workflow tier for triggers
- [ ] **Section loader registered** — `_sectionLoaders['name'] = loadName` in `ds/main.js`
- [ ] **Window bindings set** — `window.show` assigned in `ds/main.js`; any `onclick` handlers on `window.*`
- [ ] **Error handled** — `try/catch` in each JS loader; shows `—` on failure
- [ ] **Spec updated** — `Spec_JS_Code.md` Section 5 updated with ds/ module table; `Spec_RITA_App.md` updated if new endpoint added
- [ ] **HTML changes complete** — `ds.html` inline scripts replaced with `<script type="module">` (or "n/a" if Architect listed zero HTML files)
- [ ] **Ruff passes** — `ruff check src/` returns no errors (trivially true for JS-only changes)
- [ ] **No hardcoded values** — no localhost URLs, no hardcoded paths
