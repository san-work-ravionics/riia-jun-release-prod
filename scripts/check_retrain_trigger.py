"""Check the outcome-driven retrain trigger (Feature 32 Phase 4.1).

Prints the decision and exits 1 when a retrain is indicated (0 otherwise), so an
existing scheduled job can gate a retrain on it without a new scheduler:

  PYTHONPATH=$PWD/src python scripts/check_retrain_trigger.py || python scripts/train_v2.py

Run:
  cd riia-cowork-aug-demo/riia-jun-release
  PYTHONPATH=$PWD/src /Users/sgawde/work/py-shared-env/dev/bin/python3 scripts/check_retrain_trigger.py
"""
from __future__ import annotations

import sys

from rita.database import SessionLocal
from rita.services.retrain_trigger import evaluate_retrain_trigger

if __name__ == "__main__":
    agent = sys.argv[1] if len(sys.argv) > 1 else "Execution Analyst"
    db = SessionLocal()
    try:
        d = evaluate_retrain_trigger(db, agent=agent)
    finally:
        db.close()

    cur = f"{d['current_sortino']:.2f}" if d["current_sortino"] is not None else "—"
    pri = f"{d['prior_sortino']:.2f}" if d["prior_sortino"] is not None else "—"
    print(f"[retrain-trigger] {d['agent']}: Sortino {cur} (n={d['current_n']}) "
          f"vs prior {pri} (n={d['prior_n']})")
    print(f"[retrain-trigger] should_retrain={d['should_retrain']} — {d['reason']}")
    sys.exit(1 if d["should_retrain"] else 0)
