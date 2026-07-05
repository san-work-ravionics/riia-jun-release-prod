"""Feature 32 — agent-team performance timeline (activity + risk-adjusted health).

Composes the per-bucket activity (invocations / outcome-match, from the repository)
with a **cumulative Sortino** of advised returns through each bucket — a smooth
risk-adjusted health line that, unlike the directional match-rate, penalises leaving
the user exposed to realized drawdowns. Cumulative (not per-bucket) because a single
bucket usually has too few scored recommendations for a stable ratio.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from rita.core.agent_outcomes import advised_return, parse_recommendation, sortino
from rita.repositories.agent_performance import AgentPerformanceRepository
from rita.services.agent_outcome_backfill import PriceLoader, _default_price_loader


def performance_timeline(
    db: Session,
    start: datetime,
    end: datetime,
    bucket_days: int,
    price_loader: Optional[PriceLoader] = None,
) -> dict[str, Any]:
    """Return {buckets, totals, bucket_days} for the dashboard timeline plot.

    Each bucket gains a ``sortino`` field = cumulative Sortino of advised returns
    from the period start through that bucket (None until enough downside accrues).
    """
    loader = price_loader or _default_price_loader
    repo = AgentPerformanceRepository(db)
    buckets = repo.timeline_buckets(start, end, bucket_days)
    n = len(buckets)

    # Group advised returns by bucket index, then accumulate for a cumulative Sortino.
    per_bucket: list[list[float]] = [[] for _ in range(n)]
    cache: dict[str, Any] = {}
    for r in repo.scored_rows_in_range(start, end):
        created = r.created_at
        created_naive = created.replace(tzinfo=None) if created.tzinfo else created
        idx = (created_naive - start.replace(tzinfo=None)).days // bucket_days
        if idx < 0 or idx >= n:
            continue
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
            per_bucket[idx].append(ar)

    running: list[float] = []
    for i, b in enumerate(buckets):
        running.extend(per_bucket[i])
        b["sortino"] = sortino(running)

    total_inv = sum(b["invocations"] for b in buckets)
    total_eval = sum(b["evaluated"] for b in buckets)
    total_match = sum(b["matches"] for b in buckets)
    return {
        "bucket_days": bucket_days,
        "buckets": buckets,
        "totals": {
            "invocations": total_inv,
            "evaluated": total_eval,
            "match_rate": (total_match / total_eval) if total_eval else None,
            "sortino": sortino(running),
        },
    }
