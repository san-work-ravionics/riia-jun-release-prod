"""End-to-end closed-loop cycle (Feature 32) — Execution + Outcome Analyst.

Runs every stage of the loop against the real ASML RL model and DB:

  1. CAPTURE  — the trained RL policy makes a hedge recommendation at a series of
                historical anchor dates (as-of that date); each is recorded as an
                Execution Analyst agent_performance row (real recommendation).
  2. BACKFILL — the Outcome Analyst pipeline scores each recommendation against the
                realized forward price move (match / miss / neutral).
  3. REPORT   — outcome distribution + outcome-match rate for the Execution Analyst.
  4. TRIGGER  — the retrain trigger reads the realized match rate and decides.
  5. RETRAIN  — if triggered (and RETRAIN=1), retrain to close the loop.

Anchors are chosen in the matured region so outcomes resolve immediately. A wide
trigger window is used (the hedge horizon is 21d, longer than the 30d dashboard
window — see findings doc); set CYCLE_WINDOW_DAYS to change it.

Run:
  cd riia-cowork-aug-demo/riia-jun-release
  PYTHONPATH=$PWD/src INSTRUMENT=ASML \
      /Users/sgawde/work/py-shared-env/dev/bin/python3 scripts/run_closed_loop_cycle.py
  # RETRAIN=1 to actually retrain when the trigger fires (quick: N_SEEDS=1 TIMESTEPS small)
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

from rita.core.data_loader import load_ohlcv_csv
from rita.core.data_understanding import find_instrument_csv
from rita.core.technical_analyzer import calculate_indicators
from rita.core.agent_outcomes import build_recommendation, EVAL_HORIZON_DAYS
from rita.core.trading_env_v2 import load_agent_v2, recommend_hedge
from rita.database import SessionLocal
from rita.models.agent_performance import AgentPerformance
from rita.repositories.agent_performance import AgentPerformanceRepository
from rita.services.agent_outcome_backfill import backfill_agent_outcomes
from rita.services.retrain_trigger import evaluate_retrain_trigger

INSTRUMENT = os.environ.get("INSTRUMENT", "ASML").upper()
AGENT = "Execution Analyst"
INTENT = "hedge_advice"
WINDOW_DAYS = int(os.environ.get("CYCLE_WINDOW_DAYS", "400"))
APP_ROOT = Path(__file__).resolve().parents[1]


def _hr(title: str) -> None:
    print(f"\n{'─' * 4} {title} {'─' * (60 - len(title))}")


def capture(db, df, model) -> int:
    """Stage 1 — RL recommendations at historical anchors → agent_performance rows."""
    # Clear prior rows for this agent so the cycle's count/rate is clean on re-run.
    db.query(AgentPerformance).filter(
        AgentPerformance.agent_name == AGENT
    ).delete()
    db.commit()

    horizon = EVAL_HORIZON_DAYS[INTENT]
    n = len(df)
    # Matured anchors: leave > horizon forward bars; spread across ~1y of history.
    positions = list(range(n - 250, n - horizon - 2, 18))
    written = 0
    for pos in positions:
        anchor = df.index[pos]
        as_of = df.iloc[: pos + 1]                       # data known as of the anchor
        rec = recommend_hedge(as_of, model, risk_tolerance="medium")
        direction = "hedge" if rec["action"] == 3 else "nohedge"
        db.add(AgentPerformance(
            perf_id=str(uuid.uuid4()), agent_name=AGENT, intent=INTENT,
            recommendation=build_recommendation(INSTRUMENT, direction),
            outcome_status=None, created_at=anchor.to_pydatetime(),
        ))
        written += 1
        print(f"  {anchor.date()}  dd={rec['drawdown_pct']:>6.1f}%  → policy: {direction:<7} ({rec['label']})")
    db.commit()
    return written


def main() -> int:
    csv_path = (Path.cwd() / find_instrument_csv(INSTRUMENT)).resolve()
    df = calculate_indicators(load_ohlcv_csv(str(csv_path)))
    model_path = APP_ROOT / "rita_output" / "models_v2" / INSTRUMENT / f"rita_ddqn_v2_{INSTRUMENT.lower()}.zip"
    model = load_agent_v2(str(model_path))

    db = SessionLocal()
    try:
        _hr("1. CAPTURE — RL hedge recommendations (as-of historical dates)")
        n_written = capture(db, df, model)
        print(f"  captured {n_written} Execution Analyst recommendations")

        _hr("2. BACKFILL — Outcome Analyst scores them vs realized price")
        tally = backfill_agent_outcomes(db)
        print("  " + "  ".join(f"{k}={v}" for k, v in sorted(tally.items())))

        _hr("3. REPORT — realized outcome metrics")
        repo = AgentPerformanceRepository(db)
        cur, cur_n, prior, prior_n = repo.outcome_match_windows(AGENT, window_days=WINDOW_DAYS)
        rate = f"{cur:.2f}" if cur is not None else "—"
        print(f"  {AGENT}: directional match-rate = {rate} (dashboard display) over {cur_n} scored recs")

        _hr("4. TRIGGER — risk-adjusted (Sortino) retrain decision")
        sortino_floor = float(os.environ.get("CYCLE_SORTINO_FLOOR", "0.0"))
        decision = evaluate_retrain_trigger(
            db, agent=AGENT, window_days=WINDOW_DAYS, min_samples=5, sortino_floor=sortino_floor)
        s = f"{decision['current_sortino']:.2f}" if decision["current_sortino"] is not None else "—"
        print(f"  Sortino(advised returns) = {s} over {decision['current_n']} recs")
        print(f"  should_retrain = {decision['should_retrain']} — {decision['reason']}")

        _hr("5. RETRAIN — close the loop")
        if decision["should_retrain"] and os.environ.get("RETRAIN") == "1":
            print("  trigger fired + RETRAIN=1 → retraining (quick: N_SEEDS=1)…")
            env = {**os.environ, "PYTHONPATH": str(APP_ROOT / "src"),
                   "N_SEEDS": "1", "TIMESTEPS": os.environ.get("TIMESTEPS", "8000"),
                   "INSTRUMENT": INSTRUMENT}
            subprocess.run([sys.executable, str(APP_ROOT / "scripts" / "train_v2.py")], env=env, check=True)
            print("  retrain complete — loop closed; re-run this script to re-evaluate.")
        elif decision["should_retrain"]:
            print("  trigger fired. Set RETRAIN=1 to retrain now, or run:")
            print(f"    PYTHONPATH=$PWD/src N_SEEDS=10 INSTRUMENT={INSTRUMENT} python scripts/train_v2.py")
        else:
            print("  no retrain indicated — loop healthy.")
    finally:
        db.close()

    print("\n[cycle] end-to-end closed loop complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
