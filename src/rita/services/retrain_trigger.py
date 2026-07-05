"""Feature 32 Phase 4.1 — RISK-ADJUSTED retrain trigger.

Decides whether an agent's policy should be retrained from the realized,
risk-adjusted quality of its recommendations in agent_performance.

Health metric = **Sortino ratio of advised returns** over a window: each scored
recommendation is replayed into the return it would have produced (a hedge call
caps downside, a no-hedge call takes full exposure — see agent_outcomes.advised_return),
and we score mean / downside-deviation. Unlike a directional match-rate, this
PENALISES leaving the user exposed to realized drawdowns, so it agrees with the
RL-vs-static Sharpe gate (under which the policy under-hedges). Two conditions fire:
  • FLOOR  — current-window Sortino below an absolute floor (risk-adjusted losses), or
  • DRIFT  — Sortino fell by a material *fraction* versus the prior window.

Pure decision function — it NEVER retrains or swaps a model. (ADR-006.)
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from rita.core.agent_outcomes import advised_return, sortino as _sortino
from rita.repositories.agent_performance import AgentPerformanceRepository
from rita.services.agent_outcome_backfill import PriceLoader, _default_price_loader

DEFAULT_MIN_SAMPLES = 5       # need at least this many scored recs in the current window
DEFAULT_SORTINO_FLOOR = 0.0   # below this → recs are net-negative risk-adjusted → retrain
DEFAULT_DRIFT_FRACTION = 0.30 # Sortino fell ≥ this fraction vs prior window → retrain


def _advised_returns(rows, loader: PriceLoader) -> list[float]:
    cache: dict[str, Any] = {}
    out: list[float] = []
    for r in rows:
        from rita.core.agent_outcomes import parse_recommendation
        instrument = parse_recommendation(r.recommendation).get("instrument")
        if not instrument:
            continue
        if instrument not in cache:
            try:
                cache[instrument] = loader(instrument)
            except Exception:
                cache[instrument] = None
        ar = advised_return(r.intent, r.recommendation, r.created_at, cache[instrument])
        if ar is not None:
            out.append(ar)
    return out


def evaluate_retrain_trigger(
    db: Session,
    agent: str = "Execution Analyst",
    window_days: int = 30,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    sortino_floor: float = DEFAULT_SORTINO_FLOOR,
    drift_fraction: float = DEFAULT_DRIFT_FRACTION,
    price_loader: Optional[PriceLoader] = None,
) -> dict[str, Any]:
    """Return a structured, risk-adjusted retrain decision for one agent."""
    loader = price_loader or _default_price_loader
    repo = AgentPerformanceRepository(db)
    cur_rows, prior_rows = repo.scored_rows_windows(agent, window_days)

    cur_ret = _advised_returns(cur_rows, loader)
    prior_ret = _advised_returns(prior_rows, loader)
    cur_sortino = _sortino(cur_ret)
    prior_sortino = _sortino(prior_ret)

    decision: dict[str, Any] = {
        "agent": agent,
        "window_days": window_days,
        "metric": "sortino(advised_returns)",
        "current_sortino": cur_sortino,
        "current_n": len(cur_ret),
        "prior_sortino": prior_sortino,
        "prior_n": len(prior_ret),
        "should_retrain": False,
        "reason": "",
    }

    if len(cur_ret) < min_samples or cur_sortino is None:
        decision["reason"] = f"insufficient samples ({len(cur_ret)} < {min_samples}) — no decision"
        return decision

    reasons: list[str] = []
    if cur_sortino < sortino_floor:
        reasons.append(f"Sortino {cur_sortino:.2f} below floor {sortino_floor:.2f}")
    if prior_sortino is not None and prior_sortino > 0 and \
            (prior_sortino - cur_sortino) / prior_sortino >= drift_fraction:
        reasons.append(
            f"Sortino dropped {prior_sortino:.2f}→{cur_sortino:.2f} "
            f"(≥ {drift_fraction:.0%} relative drift)"
        )

    decision["should_retrain"] = bool(reasons)
    decision["reason"] = "; ".join(reasons) if reasons else "within thresholds — healthy"
    return decision
