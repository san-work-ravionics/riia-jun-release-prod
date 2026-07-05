# ADR-006: Closed-Loop Retraining for the Execution Analyst (Feature 32 Phase 4)

| Field | Value |
|---|---|
| **Status** | Accepted (experimental — aug workspace; not yet in jun/prod) |
| **Date** | 2026-06-27 |
| **Feature** | 32 — RIIA Agent Performance + RL Improvement |
| **Supersedes** | — |
| **Related** | ADR-002 (repository pattern); `design-RIIATradingEnvV2-phase3.md` |

---

## Context

Feature 32 Phase 3 shipped an RL hedge policy (`RIIATradingEnvV2`, the Execution
Analyst) trained offline and surfaced as advice. Phase 4 asks for a **closed loop**:
realized outcomes should feed back so the policy keeps improving rather than going
stale. When we went to build it we found the data layer did not exist:

- the `agent_performance` table was **empty** and the instrumentation hook never
  captured the **recommendation** (recorded at classify time, before dispatch) or
  any **outcome** (`outcome_status` always NULL);
- there was no definition of what "outcome" even means per agent;
- there was no trigger to decide *when* a retrain is warranted.

We also carried a known Phase 3 limitation: the env **underpriced hedging**
(the −1.5%/day floor was worth ~0.36%/day on ASML vs a 0.15%/day carry — a
+0.21%/day edge), so every best-of-N winner converged to an "always hedge"
policy that ignored risk tolerance.

---

## Decision

Build the closed loop in three grounded pieces, plus fix the hedge pricing.

### 1. Outcome signal — realized price, per intent (`core/agent_outcomes.py`)
- Each intent has a forward **evaluation horizon** (e.g. trend 5d, return_1m 21d,
  hedge 21d). The implied directional call (up / down / buy / hedge / nohedge) is
  **captured at record time** (now post-dispatch in `chat.py`) and encoded into the
  existing free-text `recommendation` column (`instrument=…;dir=…`) — no migration.
- `evaluate_outcome()` compares the call to the realized return over the horizon →
  `match` / `miss` / `neutral`. Hypotheticals and reports (scenario stress, sentiment
  without a feed, backtest reports) are explicitly **`not_evaluable`**, never faked.
- A backfill job (`services/agent_outcome_backfill.py`) scores matured rows
  idempotently; immature rows stay NULL and resurface next run.

### 2. Reward — outcome-match as a secondary term (Phase 4.2)
- `RIIATradingEnvV2` reward gains `+ LAMBDA_OUTCOME · sign(hedge call vs realized
  forward move)`, using the **same** match rule (`outcome_match_sign`) the dashboard
  reports. The policy is therefore trained on exactly what we measure.

### 3. Retrain trigger — RISK-ADJUSTED outcome drift (Phase 4.1, `services/retrain_trigger.py`)
- Health metric = **Sortino ratio of advised returns** over the window: each scored
  recommendation is replayed into the return it would have produced (a hedge call caps
  downside per `agent_outcomes.advised_return`, a no-hedge call takes full exposure),
  and we score mean / downside-deviation. Fires when current Sortino is **below an
  absolute floor (0.0 → net-negative risk-adjusted)** or **drops ≥ 30% relative** to
  the prior window, subject to a minimum sample count.
- **Why not a directional match-rate?** A match-rate rewards "no-hedge" in a rising
  market (markets mostly rise), so it rates an *under-hedging* policy "healthy" and
  disagrees with the RL-vs-static Sharpe gate. Sortino penalises leaving the user
  exposed to *realized drawdowns*, so it agrees with the gate. (The dashboard still
  shows the directional match-rate as an accuracy display.)
- It is a **pure decision function** — it never retrains or swaps a model. A `script`
  exits non-zero when a retrain is indicated so an **existing** scheduled job (the
  data-refresh run) can gate a retrain on it. **No new scheduler** (resolves Q3).

### 4. Hedge pricing recalibration (highest-leverage fix)
- `HEDGE_COST_PER_DAY` set to the **break-even** carry (≈ `E[max(FLOOR − daily, 0)]`
  on training returns, 0.0036) so blanket hedging is no longer free alpha and the
  policy must hedge **selectively**.

### Guardrail
No automatic production model swap. A retrain produces a candidate; promotion
requires the Phase 5 gate (RL-vs-static on held-out data) **and** explicit human
sign-off (consistent with Phase 3's gate).

---

## Consequences

**Positive**
- Realized outcomes now exist as a first-class, price-grounded signal feeding both
  the dashboard `outcome_match_rate` and the RL reward — a genuine closed loop.
- The retrain trigger is cheap, explainable, and rides existing scheduling.
- Break-even hedge pricing removes the artifact that forced "always hedge."

**Negative / risks**
- Long-horizon intents (e.g. `return_1y`) can never be both matured **and** inside
  the 30-day dashboard window — inherent; those rates lag.
- Best-of-N still selects on validation Sharpe; until selection also rewards
  outcome-match / selectivity, a hedge-heavy seed can still win even post-recalibration.
  (Tracked as a follow-up.)
- All of the above is **aug-workspace, offline, uncommitted** — not in jun or prod.

---

## Status of acceptance gates
- Phase 4.1 trigger: unit-tested (floor, drift, insufficient-samples, healthy).
- Phase 4.2 reward term: backtested on the held-out test window — gate PASS.
- Hedge recalibration: validated by retrain (see Feature 32 PLAN_STATUS session log).
