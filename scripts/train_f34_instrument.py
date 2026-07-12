"""F34 Phase 2.5 — train one instrument's Double-DQN (RIIATradingEnvV2) and
record the round in models/<INSTRUMENT>/training_history.csv.

Date-based windows (match training_history.csv column semantics exactly):
    train    = rows  < 2023-01-01
    val      = 2023-01-01 .. 2024-12-31   -> val_* columns
    backtest = rows >= 2025-01-01         -> backtest_* columns (Jan 2025-present)

Per-instrument hyperparameters come from config/instruments/<inst>.yaml:
the ``training:`` section (lr / buffer / exploration) via load_instrument_defaults,
the ``env:`` section via load_instrument_env_config. TIMESTEPS is overridden
from the environment (F34 Phase 2.5 budget: 50000), n_seeds forced to 1.

Run (from anywhere — the script chdirs to the repo root):
    INSTRUMENT=ASML TIMESTEPS=50000 \
        /Users/sgawde/work/py-shared-env/dev/bin/python3 scripts/train_f34_instrument.py

Env vars:
    INSTRUMENT  required — one of the 11 instrument ids
    TIMESTEPS   default 50000
    SEED        default 42
    OUTPUT_DIR  default <settings.model.path>/<INSTRUMENT>  (override for smoke tests)
    RECORD      default 1 — set 0 to skip the training_history.csv append (smoke tests)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
os.chdir(APP_ROOT)

from rita.config import settings
from rita.core.data_loader import load_ohlcv_csv
from rita.core.data_understanding import find_instrument_csv
from rita.core.instrument_config import load_instrument_env_config
from rita.core.ml_dispatch import load_instrument_defaults
from rita.core.technical_analyzer import calculate_indicators
from rita.core.trading_env_v2 import run_episode_v2, train_agent_v2
from rita.core.training_tracker import TrainingTracker

TRAIN_END = "2022-12-31"
VAL_START, VAL_END = "2023-01-01", "2024-12-31"
BACKTEST_START = "2025-01-01"

SHARPE_FLOOR = 1.0     # same constraints the DDQN training loop reports on
MDD_CEILING_PCT = 10.0

INSTRUMENT = os.environ.get("INSTRUMENT", "").upper()
if not INSTRUMENT:
    sys.exit("INSTRUMENT env var is required")
TIMESTEPS = int(os.environ.get("TIMESTEPS", "50000"))
SEED = int(os.environ.get("SEED", "42"))
RECORD = os.environ.get("RECORD", "1") != "0"
out_dir = Path(os.environ.get("OUTPUT_DIR") or Path(settings.model.path) / INSTRUMENT)
out_dir.mkdir(parents=True, exist_ok=True)

# ── 1. Data + indicators ──────────────────────────────────────────────────────
csv_path = find_instrument_csv(INSTRUMENT)
df = calculate_indicators(load_ohlcv_csv(str(csv_path)))
print(f"[data] {INSTRUMENT}: {csv_path} — {len(df)} rows "
      f"({df.index.min().date()} → {df.index.max().date()})")

train_df = df.loc[:TRAIN_END]
val_df = df.loc[VAL_START:VAL_END]
backtest_df = df.loc[BACKTEST_START:]
print(f"[split] train={len(train_df)}  val(2023-24)={len(val_df)}  "
      f"backtest(2025+)={len(backtest_df)}")
for name, frame in (("train", train_df), ("val", val_df), ("backtest", backtest_df)):
    if len(frame) < 60:
        sys.exit(f"[abort] {name} window too small for {INSTRUMENT}: {len(frame)} rows")

# ── 2. Per-instrument config ──────────────────────────────────────────────────
defaults = load_instrument_defaults(INSTRUMENT)
env_config = load_instrument_env_config(INSTRUMENT)
print(f"[config] episode_length={env_config.episode_length}  "
      f"lr={defaults.get('learning_rate', 1e-4)}  "
      f"exploration={defaults.get('exploration_pct', 0.5)}")

# ── 3. Train (single seed — F34 Phase 2.5 50k budget) ────────────────────────
model_name = f"rita_ddqn_v2_{INSTRUMENT.lower()}_f34p25"
print(f"[train] {model_name}  timesteps={TIMESTEPS}  seed={SEED} …")
model, progress_cb = train_agent_v2(
    train_df=train_df,
    output_dir=str(out_dir),
    timesteps=TIMESTEPS,
    learning_rate=float(defaults.get("learning_rate", 1e-4)),
    buffer_size=int(defaults.get("buffer_size", 100_000)),
    exploration_fraction=float(defaults.get("exploration_pct", 0.5)),
    seed=SEED,
    model_name=model_name,
    env_config=env_config,
)
model_path = out_dir / f"{model_name}.zip"
print(f"[train] saved → {model_path}")


def _episode_metrics(frame, label: str) -> dict:
    res = run_episode_v2(model, frame, risk_tolerance="medium", env_config=env_config)
    p = res["performance"]
    p["constraints_met"] = (
        p.get("sharpe_ratio", 0.0) >= SHARPE_FLOOR
        and abs(p.get("max_drawdown_pct", 100.0)) < MDD_CEILING_PCT
    )
    print(f"[{label}] sharpe={p.get('sharpe_ratio'):.3f}  "
          f"mdd={p.get('max_drawdown_pct'):.2f}%  "
          f"return={p.get('portfolio_total_return_pct', 0.0):.2f}%  "
          f"trades={p.get('total_trades', 0)}  "
          f"constraints_met={p['constraints_met']}")
    return p


# ── 4. Evaluate on the two reporting windows ─────────────────────────────────
val_perf = _episode_metrics(val_df, "val 2023-24")
bt_perf = _episode_metrics(backtest_df, "backtest 2025+")

# ── 5. Record round in models/<INST>/training_history.csv ────────────────────
if RECORD:
    tracker = TrainingTracker(str(out_dir))
    round_num = tracker.record_round(
        training_metrics={"timesteps_trained": TIMESTEPS, "source": "trained", "seed": SEED},
        val_metrics=val_perf,
        backtest_metrics=bt_perf,
        notes=f"F34-P2.5 50k seed{SEED} {model_name}",
    )
    print(f"[tracker] round {round_num} → {tracker.history_path}")
else:
    print("[tracker] RECORD=0 — history append skipped")

print("[SUMMARY] " + json.dumps({
    "instrument": INSTRUMENT,
    "timesteps": TIMESTEPS,
    "model_path": str(model_path),
    "val_sharpe": round(float(val_perf.get("sharpe_ratio", 0.0)), 4),
    "val_mdd_pct": round(float(val_perf.get("max_drawdown_pct", 0.0)), 2),
    "backtest_sharpe": round(float(bt_perf.get("sharpe_ratio", 0.0)), 4),
    "backtest_mdd_pct": round(float(bt_perf.get("max_drawdown_pct", 0.0)), 2),
    "backtest_constraints_met": bool(bt_perf.get("constraints_met", False)),
    "finished_at": datetime.now(timezone.utc).isoformat(),
}))
print("[done]")
