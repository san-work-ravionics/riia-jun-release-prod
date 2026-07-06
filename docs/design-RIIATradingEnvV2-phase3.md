# Design — `RIIATradingEnvV2`: Scenario → Execution Bridge (Feature 32, Phase 3)

**Status:** Draft for design review
**Author:** Architect (RITA agent)
**Date:** 2026-06-27
**Feature:** 32 — RIIA Agent Performance + RL Improvement, Phase 3 (RL Plan Step 1)
**Requirements:** `project-office/features/Jun/32 riia-agent-performance-rl/REQUIREMENTS.md` §Phase 3
**Supersedes requirement wording:** REQUIREMENTS §Phase 3 lists "`core/trading_env.py` — extended action space" (edit in place). Per user decision (2026-06-27) this is **re-scoped to a new `RIIATradingEnvV2`** — see §1.

---

## 1. Non-negotiable constraint — the golden env is frozen

The deployed `RIIATradingEnv` (`core/trading_env.py`) and its model artifact `rita_ddqn_model.zip` are the **June-release golden version** (tag `june-release-golden`, prod `0178a44`). They MUST NOT change.

Therefore Phase 3 introduces a **new, parallel** environment and model lineage:

| Concern | Golden (frozen) | Phase 3 (new) |
|---|---|---|
| Env class | `RIIATradingEnv` | **`RIIATradingEnvV2`** (new class) |
| File | `core/trading_env.py` (unedited) | **`core/trading_env_v2.py`** (new file) |
| Action space | `Discrete(3)` | `Discrete(4)` (see §3) |
| Obs features | 8–9 | 10–11 (see §4) |
| Model artifact | `rita_ddqn_model.zip` | `rita_ddqn_v2_<run>.zip` (separate `model_version`) |
| Production swap | n/a | **None in Phase 3** — offline train + backtest only |

`trading_env_v2.py` may import shared helpers from `trading_env.py` (e.g. `TrainingProgressCallback`, `compute_all_metrics`) but defines its own `step`/`reset`/`_get_obs`. No symbol in the golden module is modified. All Phase 3 work lands on a **feature branch off `june-release-golden`**, never on prod `master` until the Phase 5 rollout gate.

---

## 2. Problem statement

Today the Scenario→Execution handoff is broken (REQUIREMENTS §gap analysis):
- **Scenario Analyst** flags an MDD breach (`breach_note: YES`) using a **static** `DRAWDOWN_THRESHOLD = −0.10` in `performance.py`.
- **Execution Analyst** has zero chat coverage and nothing downstream acts on the breach.

**Goal:** let the *trained policy itself* decide when an MDD breach should produce a **hedge recommendation**, conditioned on the user's stated risk tolerance — replacing the one-size-fits-all static threshold. The output is always a **recommendation surfaced to a human**, never an auto-executed order.

---

## 3. Extended action space

Golden `Discrete(3)` = allocation level {0%, 50%, 100%}. V2 adds an explicit **hedge** action so the policy can choose protection rather than only de-allocating:

```
Discrete(4):
  0 → Cash      (0% invested,  unhedged)
  1 → Half      (50% invested, unhedged)
  2 → Full      (100% invested, unhedged)
  3 → Hedged    (100% invested, hedge overlay applied)   ← NEW
```

Rationale for keeping 0–2 identical to golden: preserves transfer/initialisation comparability and lets the backtest isolate the *marginal* value of the hedge action. Action 3 models "stay invested but buy protection" — the realistic alternative to panic-selling into a drawdown, and the bridge to the FnO hedge machinery (protective put / covered call already in `equity_hedge_scenarios`).

**Hedge effect in the env (backtest semantics):** when action 3 is held, the step return is modelled as `daily_ret − hedge_cost_per_day`, with downside truncated below the hedge strike (a protective-put payoff approximation). `hedge_cost_per_day` is a calibratable constant (default ≈ the BSM put premium amortised over the option tenor, sourced from the existing hedge-pricing path). This is a **modelling approximation for offline backtest only** — see Open Questions Q1.

---

## 4. Observation space extension

Add two features so the policy can condition the hedge decision on *how bad the drawdown is relative to this user's tolerance*:

| # | New feature | Definition | Why |
|---|---|---|---|
| 9  | `dd_vs_tolerance` | `current_drawdown / mdd_tolerance`, clipped to [0, 3] | Lets the policy see proximity to the user's pain threshold, not an absolute −10% |
| 10 | `is_hedged` | 0 or 1 — whether a hedge overlay is currently active | Makes the hedge state observable (so the policy can hold/lift it) |

Obs dimension becomes 10 (or 11 when `ema_ratio` is present). `observation_space` Box widened accordingly. All existing features and their scaling are copied verbatim from golden `_get_obs`.

`mdd_tolerance` is **not** a free numeric in the data — Financial Goal stores `risk_tolerance: low|medium|high` (`pipeline_wizard.py:175`). V2 maps it:

```
RISK_TOLERANCE_MDD = { "low": -0.08, "medium": -0.15, "high": -0.25 }
```

(Initial calibration; tunable. Default `medium` when absent.) This is the single coupling point to Phase 1 Financial-Goal data.

---

## 5. Reward shaping

Golden reward: `portfolio_ret − 0.005  if current_dd < −0.10`.

V2 reward — penalise **unhedged** drawdown beyond the user's tolerance more heavily, and price the hedge so the policy only uses it when warranted:

```
reward = step_return
         − λ_breach · max(0, |current_dd| − |mdd_tolerance|)   if NOT hedged   (graded, not flat)
         − hedge_cost_per_day                                   if hedged
```

Key differences from golden:
1. **Graded** breach penalty (proportional to how far past tolerance) instead of a flat −0.005 — gives the policy gradient signal to act *earlier* as it approaches tolerance.
2. **Tolerance-relative**, pulled from `risk_tolerance`, not a hardcoded −10%.
3. The hedge action carries an explicit cost, so hedging is not free — the policy must learn it pays off only near/after a breach.

`λ_breach` and `hedge_cost_per_day` are hyper-parameters tuned during training; defaults chosen so a `medium` user hedging exactly at tolerance is reward-neutral vs. riding the drawdown.

---

## 6. `execution_analyst` chat intent (recommendation-only)

A **new** intent surfaced through the existing classifier/dispatch path (via `/add-chat-intent`: name, seed phrases, handler, dispatch wiring). NOTE — there is currently **no** `execution_analyst` intent; the only intents mapping to **Execution Analyst** today are `invest_now` and `explain_decision` (`classifier.py:579-580`). Phase 3 must create the new intent **and** add its name to the Feature 32 `INTENT_TO_AGENT` map (→ "Execution Analyst"). It does not alter the existing two.

- **Input:** current instrument + portfolio drawdown state + user `risk_tolerance`.
- **Action:** load the V2 policy, build the V2 observation for the current state, `model.predict(deterministic=True)`.
- **Output:** a recommendation string — e.g. *"Drawdown −12% vs your medium tolerance (−15%); RIIA V2 policy suggests **applying a protective hedge** (action: Hedged). This is advisory — no order placed."* Plus the action label and the dd-vs-tolerance number.
- **Guardrails:** NEVER calls any order/trade-execution path. Read-only. If no V2 model artifact exists, returns a graceful "RL hedge advisor not yet trained" message (so this is safe to ship behind the golden model).

This intent is **additive** — it does not alter the existing Scenario Analyst static `breach_note` path, which keeps working unchanged.

---

## 7. Model versioning & artifact isolation

Reuse `TrainingConfig.model_version` (`ml_dispatch.py:73`) — V2 runs set `model_version="rita_ddqn_v2"`, producing `rita_ddqn_v2_<run_id8>.zip`. Golden `rita_ddqn_model.zip` is never overwritten (different stem). Training logged via the existing `training_tracker` — **no new tracking system** (REQUIREMENTS acceptance criterion).

**Important (design-review correction):** the golden `train_agent` / `train_best_of_n` / `run_episode` **hardcode** `RIIATradingEnv` and the 3-action `alloc_map` (`trading_env.py:221,283`) and take no env-class parameter. Adding one would edit the frozen file. Therefore `trading_env_v2.py` ships its **own** `train_agent_v2` / `train_best_of_n_v2` / `run_episode_v2` (handling action 3). `ml_dispatch` gets a thin additive branch that calls the V2 trainers when `model_version` is a `rita_ddqn_v2` stem — it does **not** reach into golden training code. This keeps `trading_env.py` at 0 changes (some ~150 lines are duplicated into V2 by design — the cost of freezing golden).

**Training must randomise tolerance per episode:** `mdd_tolerance` is sampled across {low,med,high} on each `reset()` so the single policy generalises across risk levels and the `dd_vs_tolerance` observation carries real signal (rather than a constant).

---

## 8. Backtest & acceptance gate

Offline only — no production swap in Phase 3.

1. Train V2 (best-of-N seeds, same infra as golden) on the shared training window.
2. `run_episode`-equivalent for V2 over historical **MDD-breach events** (the periods where golden/static threshold fired).
3. Compare: static-threshold hedge timing vs V2-suggested hedge timing on Sharpe and realised post-breach drawdown.

**Acceptance gate (REQUIREMENTS §Phase 3):** V2 hedge timing is **no worse** than the static threshold on historical MDD events; the new intent returns a recommendation and never places an order; run logged via `training_tracker`. **Human review sign-off required before Phase 4.**

---

## 9. File change list (all new/additive, on a Phase-3 branch)

| File | Change |
|---|---|
| `core/trading_env_v2.py` | **NEW** — `RIIATradingEnvV2` (Discrete(4), 10–11 obs, shaped reward, per-episode tolerance sampling), `RISK_TOLERANCE_MDD`, **and V2-owned `train_agent_v2` / `train_best_of_n_v2` / `run_episode_v2`** (golden trainers can't be reused without editing the frozen file) |
| `core/ml_dispatch.py` | thin additive branch calling the V2 trainers when `model_version` is a `rita_ddqn_v2` stem (golden path untouched) |
| `core/backtest_dispatch.py` | V2-vs-static comparison helper (new function) |
| `core/classifier.py` | **new** Execution-Analyst intent (name + seed phrases + handler + dispatch) **+** new `INTENT_TO_AGENT` entry; recommendation-only |
| `tests/unit/test_trading_env_v2.py` | **NEW** — action/obs/reward shape, hedge semantics, tolerance mapping, no-order guarantee |
| `docs/` (this file) | design record |

Golden `core/trading_env.py` and `rita_ddqn_model.zip`: **0 changes.**

---

## 10. Open questions / risks

- **Q1 — hedge payoff fidelity:** the protective-put approximation in the env (truncated downside − amortised premium) is a simplification. Is backtest-grade fidelity enough for Phase 3, or do we reuse the BSM pricing from `equity_hedge_scenarios` per-step? (Recommend: start simple, document the approximation.)
- **Q2 — `RISK_TOLERANCE_MDD` calibration:** the low/med/high → −8/−15/−25% mapping is an initial guess; should it be config-driven or learned? Flag for review.
- **Q3 — sparse breach events:** historical MDD breaches may be few per instrument; backtest significance could be thin. May need multi-instrument pooling.
- **Risk — scope creep into live execution:** the recommendation-only guarantee is load-bearing. QA must assert the `execution_analyst` path has no import of any order/trade-execution function.

---

## 11. Next step

Design review → on approval, branch off `june-release-golden` and hand the file change list (§9) to the Engineer for Phase 3 implementation. No prod `master` commit until the Phase 5 rollout gate.
