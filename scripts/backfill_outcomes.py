"""Run the agent-performance outcome backfill (Feature 32 Phase 4).

Evaluates every pending agent_performance row against realized price and writes
the verdict. Idempotent — safe to run on a schedule.

Run:
  cd riia-cowork-aug-demo/riia-jun-release
  PYTHONPATH=$PWD/src /Users/sgawde/work/py-shared-env/dev/bin/python3 scripts/backfill_outcomes.py
"""
from __future__ import annotations

from rita.database import SessionLocal
from rita.services.agent_outcome_backfill import backfill_agent_outcomes

if __name__ == "__main__":
    db = SessionLocal()
    try:
        tally = backfill_agent_outcomes(db)
    finally:
        db.close()

    print("[backfill] outcome verdicts written:")
    for k in ("match", "miss", "neutral", "not_evaluable", "pending"):
        if k in tally:
            print(f"  {k:<14} {tally[k]}")
    if not tally:
        print("  (no pending rows)")
