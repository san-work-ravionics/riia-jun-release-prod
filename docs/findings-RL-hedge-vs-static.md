# Findings — RL Hedge Policy vs. Static Rule (Feature 32, RIIATradingEnvV2)

| Field | Value |
|---|---|
| **Status** | Findings / decision pending |
| **Date** | 2026-06-27 |
| **Workspace** | aug-demo (offline experiment; nothing in jun or prod) |
| **Related** | ADR-006; `design-RIIATradingEnvV2-phase3.md`; PLAN_STATUS Feature 32 |

---

## Goal

Train an RL policy (the **Execution Analyst**) to give *better hedge timing* than
RITA's simple rule, and close the loop so it improves from realized outcomes.

## What was built (sound, reusable)

- **`RIIATradingEnvV2`** — Discrete(4) (cash / half / full / hedged), tolerance-relative
  reward, per-episode tolerance sampling, tolerance observation feature.
- **Best-of-N training** with a 3-way chronological **train / val / test** split —
  select on val, report on an untouched test window (removes selection-on-val bias).
- **Gate harness** — `compare_v2_vs_static.py`: RL vs a rule-based static baseline
  (`run_static_baseline_v2`, "hedge while drawdown breaches tolerance") per tolerance.
- **Closed-loop data layer** — `agent_outcomes.py` (per-intent realized-outcome
  evaluation), backfill service + job, post-dispatch recommendation capture,
  outcome-driven retrain trigger (`retrain_trigger.py`). 800+ unit tests green.

## The core finding

**The env underpriced hedging, and that — not RL skill — drove every apparent win.**

- The −1.5%/day hedge floor was worth **≈0.36%/day** on ASML returns; the carry was
  only **0.15%/day** → **+0.21%/day of free alpha** for hedging (~+53%/yr).
- With that artifact, best-of-N winners hit Sharpe ~2.1 and "beat" the static rule —
  but they did it by **hedging ~90% of the time, tolerance-blind** ("always buy puts").
  The RL simply exploited the cheap hedge harder than the static rule did.

**Recalibrating the carry to break-even (0.0036) removed the artifact and changed the verdict:**

| | Free-alpha env | Fairly-priced env |
|---|---|---|
| Winner behaviour | always-hedge (87–90%) | selective, tolerance-aware (42/15/6%) |
| RL Sharpe (l/m/h) | ~2.1 | 0.50 / 0.44 / 0.41 |
| Static Sharpe | ~1.0–1.3 | 0.63 / 0.68 / 0.69 |
| Gate | PASS (artifact) | **FAIL — RL < static** |

Once hedging is fairly priced, **the RL policy no longer beats the simple
"hedge-on-breach" rule** — and the static rule's own Sharpe also fell (its returns
dropped from ~490–940 to ~133–167), confirming the prior numbers were inflated for
everyone.

## Reward-tuning attempts (did not recover a win)

| Change | Effect |
|---|---|
| Outcome-match term (Phase 4.2) | shifts seed population to selective hedging, but the heavy-hedge seed still won on Sharpe (pre-recal) |
| Break-even pricing | fixes always-hedge; exposes RL ≤ static; policy now **under-hedges** (outcome term penalizes hedging into rallies) |
| Lower `LAMBDA_OUTCOME` + downside-semivariance penalty | med/high reach **parity** with static (within slack); **low tol breaks** (58% hedge, Sharpe 0.30, maxDD −36%) |

Across **6 training cycles**, lambda-tuning is whack-a-mole: it moves *which tolerance*
fails without producing a decisive, stable RL win. The learnable signal is weak once
the artifact is gone (best val Sharpe ~1.1, most seeds 0.3–0.9).

## Conclusion

The RL hedge advisor, with this env / feature set / objective, **does not reliably
beat a simple static breach-rule under honest pricing.** The static rule is simple,
explainable, and at least as good. More reward-constant tuning will not change this.

## Recommendation (decision deferred by user)

1. **Default / cheapest:** keep the **static breach-rule** as the Execution Analyst
   hedge advisor; mark the RL policy **not-promotable**. Don't ship the RL artifact.
2. **If RL is still wanted:** treat it as a real R&D redesign, not tuning —
   richer features, a Sharpe/Sortino-native objective, and **Sharpe-aware best-of-N
   selection** (not val-Sharpe alone). Open-ended, no guarantee.

## What's preserved regardless

The env, the 3-way-split training harness, the **RL-vs-static gate**, and the full
**closed-loop outcome pipeline** (backfill, recommendation capture, retrain trigger)
are all sound and reusable — and the gate harness is exactly what caught the pricing
artifact. The honest-pricing result is itself a valuable outcome.
