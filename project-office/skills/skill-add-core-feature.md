# Skill: Add / Change RITA Core (Calculation · ML · RL) Logic
**Track:** Core/ML (`/enhance core|rl|ml "<description>"`)
**Use for:** Changes to `src/rita/core/` (RL envs, reward/metrics, ML dispatch, indicators), `src/rita/services/` (orchestration), or `src/rita/repositories/` (data access) — work that has **no dashboard endpoint/JS/HTML** by itself.
**Compiled from:** `Spec_Python_Code.md` + `Spec_Data.md` + `guardrails/roles/engineer.md` + `guardrails/project.md` + `context/domain-notes.md`
**Guardrail refs:** org · engineer-role · rita-project
**Last validated against code:** 2026-06-28 (Feature 32 RL work)

---

## Track Identity

| Item | Value |
|---|---|
| Core logic dir | `riia-jun-release/src/rita/core/` — calculation + ML/RL (e.g. `trading_env.py`, `trading_env_v2.py`, `ml_dispatch.py`, `performance.py`, `indicators*`) |
| Services dir | `riia-jun-release/src/rita/services/` — business orchestration |
| Repositories dir | `riia-jun-release/src/rita/repositories/` — one class per table; the ONLY place that touches the DB/files (ADR-002) |
| Schemas dir | `riia-jun-release/src/rita/schemas/` — Pydantic contracts (only if a surface is exposed) |
| Tests dir | `riia-jun-release/tests/{unit,integration,e2e}/` |
| Primary spec | `project-office/specs/Spec_Python_Code.md` |
| Data spec | `project-office/specs/Spec_Data.md` |
| Domain notes | `project-office/context/domain-notes.md` — lot sizes, Greeks, data paths, the Sharpe/MDD objective |
| Python interpreter | `/Users/sgawde/work/py-shared-env/dev/bin/python3` — but in the aug workspace **`source activate-aug.sh` first** so `import rita` resolves to THIS src, not jun's editable install |

---

## Non-negotiable rules (read before any edit)

1. **The golden env is FROZEN.** `src/rita/core/trading_env.py` (`RIIATradingEnv`) and the artifact `rita_ddqn_model.zip` are the June-release golden model. **Never edit them.** New RL/env behaviour goes in a **parallel module** (`trading_env_v2.py`, `RIIATradingEnvV2`) with its own `*_v2` train/eval functions and its own model lineage (`rita_ddqn_v2_*`). A change whose diff touches `trading_env.py` or a golden `.zip` is an automatic BLOCKING failure. There is a unit test that guards the golden action space — keep it green.

2. **Optimise the GRADED objective, not profit.** The project target is **Sharpe ratio > 1.0 AND max drawdown < 10%** — risk-adjusted return inside a hard drawdown cap. `performance.py::compute_all_metrics` encodes this (`sharpe_constraint_met = sr > 1.0`, `drawdown_constraint_met = mdd > -0.10`). A reward whose primary term is per-step *return* optimises terminal wealth (profit), NOT Sharpe — flag/avoid it. Prefer reward formulations that move Sharpe/MDD directly (e.g. Differential Sharpe Ratio, or a terminal `Sharpe − heavy·max(0, MDD−0.10)`).

3. **Train and eval must use the SAME data alignment.** An action chosen at bar `t` must earn bar `t+1`'s return in BOTH training and evaluation/inference. Do not let training earn the same bar whose return is in the observation while eval earns the next bar — that train/serve skew makes a policy that trains well and fails live.

4. **Repository pattern (ADR-002).** No direct DB or file I/O in routes or services — only in `repositories/`. Core calculation modules take already-loaded data (DataFrames/arrays) as inputs.

5. **No print(), no hardcoded secrets or lot sizes.** Use `structlog` / the existing `log_event`. Lot sizes come from the `NSE_LOT_SIZE` table, not literals.

---

## File Map — What to Touch for a Typical Core Change

| Layer | File | What to do |
|---|---|---|
| **Core** | `src/rita/core/{module}.py` (or a new `*_v2.py`) | The calculation/ML/RL change — additively, golden untouched |
| **Core** | `src/rita/core/performance.py` | Only if the metric/constraint definition itself changes (rare — it is the scorecard) |
| **Tests** | `tests/unit/test_{module}.py` | Assert the new BEHAVIOUR/numerics + a property test (see Step 3) |
| **Spec** | `project-office/specs/Spec_Python_Code.md` | Update the module/function inventory for the changed/added symbols |
| **Docs** | `docs/design-*.md` | Update the design record if the algorithm/reward changed |
| **(only if exposed)** | `src/rita/schemas/` + `src/rita/api/experience/` | Add a read-only surface ONLY if the requirement asks to expose results to a dashboard |

---

## Step-by-Step Task Rules

### Step 1 — State the algorithm/design first
Write the formulation in the brief `[Architect] Design` section before coding: reward terms (with formulas), observation/feature changes, training/eval changes, hyper-params, and **why each change moves Sharpe/MDD**. List the exact `path::symbol` targets.

### Step 2 — Implement additively in the correct layer
- RL/env/reward → `core/`, in a `*_v2` parallel module if it forks golden behaviour.
- Orchestration (train→validate→backtest wiring) → `core/ml_dispatch.py` via a thin additive branch; do not reach into golden trainers.
- Keep functions pure where possible (take data in, return metrics/arrays out) so they are unit-testable without I/O.

### Step 3 — Tests that pin behaviour, not just imports
Every core change needs a test under `tests/` that asserts the intended property on a small synthetic input (seed any RNG). For an RL reward change, examples:
- **Causal alignment:** action at bar `t` earns bar `t+1`'s return (construct a 3-bar frame, assert portfolio value).
- **Constraint engagement:** the MDD penalty/termination fires exactly at the −10% line, for all tolerance levels.
- **Objective sign:** under a constructed declining series, the variance-reducing action is rewarded ≥ the exposed action.
Run: `cd riia-jun-release && python -m pytest tests/unit/test_{module}.py -q` — all green.

### Step 4 — Lint + spec/doc
- `cd riia-jun-release && ruff check src/` → `All checks passed!` (expand inline `if ...: return` to two lines; remove unused vars).
- Update `Spec_Python_Code.md` for the changed symbols and the design doc under `docs/` if the algorithm changed.

### Step 5 — Golden-frozen proof + commit
- `git diff --name-only <base>...HEAD` — confirm `trading_env.py` and any golden `.zip` are NOT listed; paste into the Engineer log.
- Commit `feat(core): {1-line}`; never to master/main (worktree branch only).

---

## Definition of Done

Before marking complete, verify each item:

- [ ] **Golden-frozen guard:** `git diff` shows `core/trading_env.py` and golden `rita_ddqn_model.zip` are untouched; the golden action-space guard test is green.
- [ ] **Objective alignment:** the change moves the graded metric (Sharpe>1 / MDD<10%), not profit — stated in the design and reflected in code.
- [ ] **Train/eval consistency:** the same return alignment is used in training and evaluation/inference (no contemporaneous-vs-next-bar skew).
- [ ] **Layering:** change is in the correct layer (core/services/repositories); no direct DB/file I/O outside `repositories/` (ADR-002).
- [ ] **Tests:** ≥1 new/changed test under `tests/` asserts the new behaviour/property and passes; no test merely checks that the module imports.
- [ ] **Lint:** `ruff check src/` passes.
- [ ] **Spec/doc:** `Spec_Python_Code.md` (and the design doc, if the algorithm changed) updated for the changed symbols.
- [ ] **No print()/secrets/hardcoded lot sizes**; logging via `structlog`/`log_event`.
- [ ] **Acceptance criteria:** each testable criterion in the feature's `REQUIREMENTS.md` is met now, or explicitly marked "needs a training/backtest run" for the human sign-off gate.
