# Skill: Add FnO Dashboard Feature
**App:** FnO Options dashboard (`fno.html` + `dashboard/js/fno/`)
**Use for:** New UI sections, panels, or data views in the FnO portfolio/options dashboard
**Compiled from:** `Spec_RITA_App.md` + `Spec_JS_Code.md`
**Guardrail refs:** org · engineer-role · rita-project  
**Last validated against spec:** 2026-05-26

---

## App Identity

| Item | Value |
|---|---|
| HTML file | `riia-jun-release/dashboard/fno.html` — 3,500 lines. **Never read directly.** Use spec. |
| JS module dir | `riia-jun-release/dashboard/js/fno/` |
| Primary API | Portfolio tier: `riia-jun-release/src/rita/api/v1/portfolio.py` |
| Experience API | `riia-jun-release/src/rita/api/experience/fno.py` |
| Key tables | `positions`, `orders`, `snapshots`, `trades`, `manoeuvres`, `portfolio` |
| Spec file | `project-office/specs/Spec_RITA_App.md` |
| JS Spec file | `project-office/specs/Spec_JS_Code.md` |

---

## File Map — What to Touch for a Typical FnO UI Feature

| Layer | File | What to do |
|---|---|---|
| **Backend** | `src/rita/api/v1/portfolio.py` | Add endpoint for FnO data (no auth, heavy computation allowed) |
| **Backend** | `src/rita/api/experience/fno.py` | Add aggregated read-only payload if feature is UI-only read |
| **Backend** | `src/rita/schemas/{name}.py` | Add Pydantic response schema |
| **Backend** | `src/rita/services/portfolio_service.py` | Add business logic if computation is non-trivial |
| **Frontend** | `dashboard/js/fno/{name}.js` | Create new JS module with loader function |
| **Frontend** | `dashboard/js/fno/main.js` | Register section loader + bind window.* functions |
| **Frontend** | `dashboard/js/fno/state.js` | Add to shared state only if multiple modules need the value |
| **HTML** | `fno.html` | Add `<section id="sec-NAME">` with DOM elements |
| **Spec** | `project-office/specs/Spec_RITA_App.md` | Update Portfolio endpoint inventory + section description |

---

## FnO Module Reference (existing — do not duplicate)

| Existing module | What it already handles |
|---|---|
| `dashboard.js` | FnO overview KPI cards — `loadFnoDashboard()` → `GET /api/v1/portfolio/summary` |
| `positions.js` | Open positions table — `GET /api/v1/portfolio/positions?mode=paper\|live` |
| `greeks.js` | Greeks calculator — `loadGreeks()`, `calculateGreeks()` |
| `margin.js` | Margin tracker |
| `payoff.js` | Payoff diagram |
| `stress.js` | Stress test section |
| `rr.js` | Risk-Reward chart — `GET /api/v1/portfolio/price-history` |
| `hedge.js` | Hedge Radar section — `GET /api/v1/portfolio/hedge-history` |
| `manoeuvre.js` | Manoeuvre tracking — `GET /api/v1/portfolio/man-groups` + man-snapshot + man-pnl-history |

Before adding a new module, confirm the feature is not already covered by an existing one.

---

## Portfolio API Reference (existing endpoints — do not add duplicates)

| Endpoint | Method | Returns |
|---|---|---|
| `/api/v1/portfolio/overview` | GET | Cross-instrument normalised prices + correlation matrix |
| `/api/v1/portfolio/backtest` | POST | Multi-instrument DDQN portfolio backtest |
| `/api/v1/portfolio/positions?mode=` | GET | Paper or live positions |
| `/api/v1/portfolio/summary` | GET | KPI cards + market prices (nifty_spot, banknifty_spot, asml_close, nvidia_close) |
| `/api/v1/portfolio/price-history?periods=N` | GET | Recent NIFTY OHLCV |
| `/api/v1/portfolio/hedge-history` | GET | Historical hedge suggestions |
| `/api/v1/portfolio/man-groups` | GET | Manoeuvre group list |
| `/api/v1/portfolio/man-snapshot` | POST | Record snapshot when manoeuvre applied |
| `/api/v1/portfolio/man-pnl-history` | GET | Daily P&L history |
| `/api/v1/portfolio/man-daily-status` | GET | Today's manoeuvre count + last record |
| `/api/v1/portfolio/man-daily-snapshot` | POST | Record daily portfolio snapshot |

---

## Step-by-Step Task Rules

### Step 1 — Design the API Contract First
Define before writing code:
- Endpoint: method + path + query params
- Which FnO tables it reads (positions / orders / manoeuvres / portfolio)
- Response shape: field names + types as a Pydantic schema
- Frontend consumer: which JS module, which DOM element IDs

Write the contract in the task brief `[Architect] Design` section before proceeding.

### Step 2 — Choose the Right API Tier
- **Portfolio tier** (`portfolio.py`): FnO-specific computation, no auth required, may be heavy
- **Experience tier** (`fno.py`): Aggregated read-only UI payload, no auth, no commits
- **System tier**: Only for raw CRUD on FnO tables (positions, orders, manoeuvres)

### Step 3 — Add the Backend Endpoint

**Portfolio tier pattern:**
```python
@router.get("/api/v1/portfolio/my-feature", response_model=MyFeatureResponse)
def get_my_feature(db: Session = Depends(get_db)):
    service = PortfolioService(db)
    data = service.my_feature_calculation()
    return MyFeatureResponse(items=data)
```

**Key rules:**
- FnO tables: `positions`, `orders`, `snapshots`, `trades`, `manoeuvres`, `portfolio`
- Never read lot sizes from hardcoded values — read from `settings.instruments.*`
- `PortfolioService` and `ManoeuvreService` constructors require `db: Session`
- Background threads must open their own `SessionLocal()` — never pass request-scoped session

### Step 4 — Add the Pydantic Schema
File: `src/rita/schemas/{name}.py`
- Match field names exactly to what `fno/dashboard.js` will read
- Key existing field names to be aware of: `total_pnl`, `lot_count`, `nifty_spot`, `banknifty_spot`, `asml_close`, `nvidia_close`

### Step 5 — Write the JS Module
File: `dashboard/js/fno/{name}.js`

**Module template:**
```js
import { api } from './api.js';
import { setEl, badge, fmt, fmtPct } from './utils.js';
import { mkChart, C } from './charts.js';
import { state } from './state.js';    // only if you need shared FnO state

export async function loadMyFeature() {
  try {
    const data = await api('/api/v1/portfolio/my-feature');
    setEl('my-feature-value', fmt(data.value, 2));
  } catch (e) {
    setEl('my-feature-value', '—');
  }
}
```

**Rules (same as RITA):**
- Import `api` from `./api.js` — never raw `fetch()`
- Wrap API calls in `try/catch` — show `—` on error
- Use `setEl(id, html)` — never `document.getElementById(...).innerHTML`
- Use `mkChart(id, config)` — never `new Chart(...)`
- Use `C` color palette from `charts.js`
- No top-level `fetch()` or DOM queries
- Use `state` from `state.js` for active group/instrument if needed

### Step 5.5 — FC-IMP Check: Verify Named Imports (run before Step 6)

> **Run this immediately after writing the JS module — before registering in main.js.**

For every `import { name1, name2 } from './module.js'` line in the new JS file:
1. Open `module.js` and grep for `export` statements
2. Confirm each imported name appears as `export function name` or `export const name`
3. Report explicitly: "FC-IMP: [name1] ✓ in [module.js]" — one line per import

**A missing named export is a static binding error** — the browser throws a `SyntaxError` at parse time and the entire app module tree dies, not just the new section. Do NOT proceed to main.js registration until all imports are confirmed.

If any name is missing: find the correct exported name in the file, or add the export — report the resolution. Do not silently skip a check.

**Path depth verification for cross-directory imports:**
For any import with a `..` path (e.g., `import { foo } from '../shared/api-cache.js'`), state the resolved absolute path explicitly before marking the import valid:
- From `dashboard/js/fno/`: `'../shared/'` resolves to `dashboard/js/shared/` ✓
- From `dashboard/js/fno/`: `'../../shared/'` resolves to `dashboard/shared/` — this directory does not exist
Report: "api-cache.js is at dashboard/js/shared/ → import `'../shared/api-cache.js'` ✓" — one line per cross-directory import.

### Step 6 — Register Section Loader in main.js
In `dashboard/js/fno/main.js`:
```js
import { loadMyFeature } from './my-feature.js';

_sectionLoaders['my-feature'] = loadMyFeature;
window.loadMyFeature = loadMyFeature;
```

### Step 7 — Update the Spec

> **STOP — do not run `git add` until this step is complete. This is a blocking gate — spec not updated = orchestrator will re-invoke you to fix it before QA runs.**

File: `project-office/specs/Spec_RITA_App.md`
- Add the new endpoint to the Portfolio tier table in Section 3
- Add the new JS module to `Spec_JS_Code.md` Section 3 (FnO module structure)

Open each spec file. Read the relevant table. Add the new row. **Report the exact line you added to each file** (e.g. `| GET | /api/v1/portfolio/my-feature | MyFnoFeatureResponse |`).

Then run: `grep -n 'YOUR_ENDPOINT_PATH' project-office/specs/Spec_RITA_App.md` (substitute the actual endpoint path from your API contract) and include the grep output line in your report. If grep returns no match, you have not saved the edit — do not proceed to commit until grep confirms the row exists.

### Step 8 — TechWriter: Confluence + Human Score Prompt

> **STOP — before closing the run, confirm `Spec_RITA_App.md` and `Spec_JS_Code.md` reflect the new endpoint and module. If the Engineer skipped Step 7, do it now before emitting the human score prompt.**

After confirming spec files and updating Confluence, ask the user to run a smoke test before scoring:

> **Smoke-test gate:** "Please open the FnO dashboard in a browser and verify the new section renders without JavaScript console errors. Open browser DevTools → Console and confirm no `SyntaxError`, `Cannot resolve module`, or `is not exported` errors appear. Report: page loads OK / page broken."
>
> If the user reports a runtime error: do NOT emit the scoring prompt. Investigate and fix the error first — it is likely a missing named export (FC-IMP) or a conflict marker (FC-MERGE). Only emit the scoring prompt after the user confirms the page loads cleanly.

Once the user confirms the page loads, emit the following prompt:

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

Record responses as `human_score{}` in the run JSON: `accuracy`, `relevance`, `planning_ok` (y→true), `csat`, `time_saved_hours`. Skipped fields default to `null`.

---

## Guardrails

| Rule | Detail |
|---|---|
| Never read `fno.html` directly | File is 3,500 lines. Use spec and HTML spec for nav/DOM patterns. |
| Never hardcode lot sizes | Read from `settings.instruments.*` |
| Never call `db.commit()` in Experience tier | Experience routes are read-only |
| Never use bare `pd.read_csv()` | Use `load_nifty_csv()` or `load_instrument_data()` from `core/data_loader.py` |
| Never add `print()` statements | Use `structlog` |
| Never hardcode `http://localhost:8000` in JS | Use `window.RITA_API_BASE` |
| HTML changes are still required even though full reads are forbidden | "Never read fno.html" = no full-file Read (3,500 lines). For any HTML file in the Architect's files-to-touch list: use Grep to find a sibling element ID, read ±15 lines around it, then use targeted Edit to insert. Skipping an HTML change is a partial implementation (FC-PARTIAL-IMPL). |
| **Alembic migration must be applied, not just created** | After writing a migration file, run `python -m alembic upgrade head` from `riia-jun-release/` and confirm the `Running upgrade` line before committing. Committing the file alone does NOT apply the schema change — the app will crash with `OperationalError: no such column` at runtime. This is a hard DoD gate: migration applied = confirmed upgrade output seen. |
| Never call `new Chart(...)` directly | Use `mkChart(id, config)` from `charts.js` |
| Never expose ES module functions without `window.*` | `onclick=""` handlers silently fail |
| Never duplicate existing portfolio endpoints | Check the Portfolio API Reference table above first |
| Always update spec when contract changes | Spec drift breaks future agents |

---

## Definition of Done

Before marking this task complete, verify each item:

**FC-004 gate — verify before committing:**
Open the JS module you just wrote or changed. List every `data.field` or `r.field`
access in the file. For each, confirm the exact field name exists in your Pydantic
schema or response dict. A single character difference (underscore vs camelCase,
_pct suffix missing) causes a silent JS render failure. Only after verifying every
field may you proceed to git add.

**FC-IMP gate — JS named-import resolution (verify before committing):**
For every `import { name1, name2 } from './module.js'` line in the new or modified
JS file, open `module.js` and confirm each name appears in an `export` statement.
A missing named export is a **static binding error** — the browser throws a
`SyntaxError` at parse time, which cascades up the import chain and kills the entire
app, not just the new section. This check must be done explicitly; it is not caught
by the FC-004 contract check or by ruff.

Also verify path depth for cross-directory imports: from `dashboard/js/fno/`, shared
modules are at `'../shared/api-cache.js'` (one `..` up to `js/`). Using `'../../'`
resolves to `dashboard/` which contains no `shared/` subdirectory.

**FC-TIER gate — system-tier API compliance (run before `git add`):**
Run: `grep -rn "api/v1/training-history\|api/v1/backtest-daily\|api/v1/risk-timeline" dashboard/js/fno/`
Output must be empty. Any match = banned system-tier call still in JS. Replace with the correct experience-tier path (`/api/v1/experience/rita/...`) before committing.

**FC-API-SIG gate — api() POST signature (run before `git add`):**
Run: `grep -rn "api(.*{" dashboard/js/fno/`
Output must show zero instances of `api(path, {` patterns. All POST calls must use the positional form: `api(path, 'POST', body)`. The object-options form silently breaks all POST operations.

**FC-MERGE gate — no leftover conflict markers (run before `git add`):**
Run: `grep -rn "^<<<<<<\|^=======\|^>>>>>>>" dashboard/js/`
Output must be empty. Any `<<<<<<<` / `=======` / `>>>>>>>` left in a JS file is a
`SyntaxError` that kills the entire app module tree — the browser cannot parse these
tokens. This is especially critical after merge conflict resolution sessions.

- [ ] **API contract matches** — Pydantic schema field names match JS `data.field` reads exactly
- [ ] **Correct tier used** — Portfolio for FnO computation, Experience for read-only aggregation
- [ ] **Section loader registered** — `_sectionLoaders['name'] = loadName` in `fno/main.js`
- [ ] **Window bindings set** — all `onclick` handlers on `window.*` in `fno/main.js`
- [ ] **Error handled** — `try/catch` in JS loader; shows `—` on failure
- [ ] **Spec updated** — endpoint added to `Spec_RITA_App.md` Portfolio tier; JS module added to `Spec_JS_Code.md` Section 3. **"n/a" is ONLY valid if the Architect's files-to-touch table lists zero spec rows** — any other "n/a" is FC-001 and triggers orchestrator re-invocation.
- [ ] **HTML changes complete** — every HTML file in the Architect's files-to-touch table is edited via Grep → read ±15 lines → targeted Edit. If Architect listed zero HTML files, write "n/a". Skipping = FC-PARTIAL-IMPL.
- [ ] **Ruff passes** — `ruff check src/` returns no errors
- [ ] **No hardcoded values** — no localhost URLs, no hardcoded lot sizes
