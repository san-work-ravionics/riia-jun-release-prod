"""Phase 3 acceptance gate — RL hedge policy vs static-threshold baseline.

Runs the trained RIIATradingEnvV2 winner and the rule-based static-threshold
baseline through the SAME held-out validation window, per risk tolerance, and
reports Sharpe / max-drawdown / hedge-usage / total-return side by side.

Gate (per the PLAN_STATUS acceptance criterion): RL hedge timing must be
"no worse than the static threshold on historical MDD-breach events" — operatio-
nalised here as: on every tolerance, RL max-drawdown is no deeper than static
(within tol) AND RL Sharpe is no lower than static (within tol). Offline only —
never swaps a production model.

Run:
  cd riia-cowork-aug-demo/riia-jun-release
  PYTHONPATH=$PWD/src INSTRUMENT=ASML \
      /Users/sgawde/work/py-shared-env/dev/bin/python3 scripts/compare_v2_vs_static.py
"""
from __future__ import annotations

import os
from pathlib import Path

AUG_MARKER = "riia-cowork-aug-demo"
import rita.core.trading_env_v2 as tv2
assert AUG_MARKER in tv2.__file__, f"NOT aug code: {tv2.__file__}"

from rita.core.data_understanding import find_instrument_csv
from rita.core.data_loader import load_ohlcv_csv
from rita.core.technical_analyzer import calculate_indicators
from rita.core.trading_env_v2 import (
    run_episode_v2, run_static_baseline_v2, load_agent_v2, temporal_split,
)

INSTRUMENT = os.environ.get("INSTRUMENT", "ASML").upper()
APP_ROOT = Path(__file__).resolve().parents[1]
assert AUG_MARKER in str(APP_ROOT)

# Tolerances for "no worse" — small slack so floating noise doesn't fail the gate.
SHARPE_SLACK = 0.05
MDD_SLACK_PCT = 0.50  # percentage points

csv_path = (Path.cwd() / find_instrument_csv(INSTRUMENT)).resolve()
df = calculate_indicators(load_ohlcv_csv(str(csv_path)))
_, _, val_df = temporal_split(df)   # gate measured on the untouched TEST window
print(f"[data] {INSTRUMENT}: test rows = {len(val_df)} (held-out, never used for selection)")

model_path = APP_ROOT / "rita_output" / "models_v2" / INSTRUMENT / f"rita_ddqn_v2_{INSTRUMENT.lower()}.zip"
model = load_agent_v2(str(model_path))
print(f"[model] {model_path}\n")


def _metrics(res: dict) -> dict:
    p = res["performance"]
    return {
        "sharpe":    float(p.get("sharpe_ratio", 0.0)),
        "max_dd":    float(p.get("max_drawdown_pct", 0.0)),  # negative %
        "ret":       float(p.get("portfolio_total_return_pct", p.get("portfolio_cagr_pct", 0.0))),
        "hedge_pct": float(res["hedge_usage_pct"]),
    }


hdr = f"{'tol':<7} {'Sharpe (RL/stat)':<20} {'maxDD% (RL/stat)':<22} {'hedge% (RL/stat)':<20} {'return (RL/stat)':<22} verdict"
print(hdr)
print("-" * len(hdr))

all_pass = True
for tol in ("low", "medium", "high"):
    rl = _metrics(run_episode_v2(model, val_df, risk_tolerance=tol))
    st = _metrics(run_static_baseline_v2(val_df, risk_tolerance=tol))

    # "no worse": RL drawdown not materially deeper AND Sharpe not materially lower.
    dd_ok = rl["max_dd"] >= st["max_dd"] - MDD_SLACK_PCT     # less negative = shallower = better
    sharpe_ok = rl["sharpe"] >= st["sharpe"] - SHARPE_SLACK
    ok = dd_ok and sharpe_ok
    all_pass = all_pass and ok

    print(f"{tol:<7} "
          f"{rl['sharpe']:>6.3f} / {st['sharpe']:<7.3f}   "
          f"{rl['max_dd']:>7.2f} / {st['max_dd']:<7.2f}     "
          f"{rl['hedge_pct']:>5.1f} / {st['hedge_pct']:<5.1f}      "
          f"{rl['ret']:>7.2f} / {st['ret']:<7.2f}    "
          f"{'PASS' if ok else 'FAIL'}{'' if ok else f'  (dd_ok={dd_ok} sharpe_ok={sharpe_ok})'}")

print("-" * len(hdr))
print(f"\n[gate] RL is no-worse-than-static on all tolerances: {'PASS ✅' if all_pass else 'FAIL ❌'}")
print(f"[gate] criteria: RL maxDD ≥ static−{MDD_SLACK_PCT}pp  AND  RL Sharpe ≥ static−{SHARPE_SLACK}")
