"""Seed synthetic agent_performance rows (Feature 32 Phase 4 dev/testing).

The table is empty in dev (instrumentation only fires on live chat). This inserts
a realistic spread of rows across all 7 agents — matured directional calls (so the
backfill can score them), not-evaluable intents, and a few recent/immature rows —
all anchored to real dates in the instrument's price history.

Run:
  cd riia-cowork-aug-demo/riia-jun-release
  PYTHONPATH=$PWD/src INSTRUMENT=ASML \
      /Users/sgawde/work/py-shared-env/dev/bin/python3 scripts/seed_agent_performance.py
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from rita.core.agent_outcomes import build_recommendation
from rita.core.data_loader import load_ohlcv_csv
from rita.core.data_understanding import find_instrument_csv
from rita.database import SessionLocal
from rita.models.agent_performance import AgentPerformance

INSTRUMENT = os.environ.get("INSTRUMENT", "ASML").upper()

# (intent, agent, direction) — directional rows are scoreable; "none" → not_evaluable.
SAMPLES = [
    ("trend_direction", "Technical Analyst", "up"),
    ("trend_direction", "Technical Analyst", "down"),
    ("rsi_reading", "Technical Analyst", "up"),
    ("return_1m", "Financial Goal", "up"),
    ("return_3m", "Financial Goal", "up"),
    ("invest_now", "Execution Analyst", "buy"),
    ("hedge_advice", "Execution Analyst", "hedge"),
    ("hedge_advice", "Execution Analyst", "nohedge"),
    ("market_sentiment", "Sentiment Analyst", "none"),       # not_evaluable
    ("stress_crash_20", "Scenario Analyst", "none"),         # not_evaluable
    ("allocation_level", "Strategy Analyst", "none"),        # not_evaluable
    ("backtest_performance", "Outcome Analyst", "none"),     # not_evaluable
]


def main() -> None:
    csv_path = (Path.cwd() / find_instrument_csv(INSTRUMENT)).resolve()
    price_df = load_ohlcv_csv(str(csv_path))
    dates = list(price_df.index)
    if len(dates) < 400:
        raise SystemExit(f"Not enough price history to seed: {len(dates)} rows")

    # Matured anchors: ~1 year back (plenty of forward bars for every horizon).
    matured_dates = [dates[-300], dates[-280], dates[-260], dates[-240], dates[-220], dates[-200]]
    # Immature anchor: last bar (no forward data → stays pending).
    immature_date = dates[-1]

    db = SessionLocal()
    inserted = 0
    try:
        for i, (intent, agent, direction) in enumerate(SAMPLES):
            created = matured_dates[i % len(matured_dates)].to_pydatetime()
            db.add(AgentPerformance(
                perf_id=str(uuid.uuid4()),
                agent_name=agent,
                intent=intent,
                recommendation=build_recommendation(INSTRUMENT, direction),
                outcome_status=None,
                created_at=created,
            ))
            inserted += 1

        # A couple of fresh, immature directional rows → should resolve to "pending".
        for intent, agent in (("trend_direction", "Technical Analyst"), ("invest_now", "Execution Analyst")):
            db.add(AgentPerformance(
                perf_id=str(uuid.uuid4()),
                agent_name=agent,
                intent=intent,
                recommendation=build_recommendation(INSTRUMENT, "up"),
                outcome_status=None,
                created_at=immature_date.to_pydatetime(),
            ))
            inserted += 1

        db.commit()
    finally:
        db.close()

    print(f"[seed] inserted {inserted} agent_performance rows for {INSTRUMENT} "
          f"({len(SAMPLES)} matured + 2 immature)")


if __name__ == "__main__":
    main()
