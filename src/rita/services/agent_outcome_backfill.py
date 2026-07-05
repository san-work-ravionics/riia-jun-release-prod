"""Feature 32 Phase 4 — backfill realized outcomes onto agent_performance rows.

Walks rows whose outcome_status is still NULL, evaluates each against realized
price over the intent's horizon (see rita.core.agent_outcomes), and writes the
verdict back. Rows that are not yet mature stay NULL and resurface next run.
Offline / idempotent — safe to run repeatedly (e.g. nightly).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
from sqlalchemy.orm import Session

from rita.core.agent_outcomes import evaluate_outcome, parse_recommendation
from rita.repositories.agent_performance import AgentPerformanceRepository

PriceLoader = Callable[[str], Optional[pd.DataFrame]]


def _default_price_loader(instrument: str) -> Optional[pd.DataFrame]:
    """Load an instrument's OHLCV frame (DatetimeIndex, 'Close') from its CSV."""
    from rita.core.data_loader import load_ohlcv_csv
    from rita.core.data_understanding import find_instrument_csv

    path = (Path.cwd() / find_instrument_csv(instrument)).resolve()
    return load_ohlcv_csv(str(path))


def backfill_agent_outcomes(
    db: Session,
    price_loader: Optional[PriceLoader] = None,
    now: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> dict[str, int]:
    """Evaluate + persist outcomes for pending rows. Returns a verdict tally.

    Tally keys: match / miss / neutral / not_evaluable / pending (left NULL).
    """
    loader = price_loader or _default_price_loader
    repo = AgentPerformanceRepository(db)
    rows = repo.pending_outcomes(limit=limit)

    price_cache: dict[str, Optional[pd.DataFrame]] = {}
    tally: Counter[str] = Counter()

    for row in rows:
        instrument = parse_recommendation(row.recommendation).get("instrument")
        price_df: Optional[pd.DataFrame] = None
        if instrument:
            if instrument not in price_cache:
                try:
                    price_cache[instrument] = loader(instrument)
                except Exception:
                    price_cache[instrument] = None
            price_df = price_cache[instrument]

        status = evaluate_outcome(row.intent, row.recommendation, row.created_at, price_df, now)
        if status is None:
            tally["pending"] += 1  # immature — leave NULL, revisit next run
            continue
        repo.set_outcome(row.perf_id, status)
        tally[status] += 1

    return dict(tally)
