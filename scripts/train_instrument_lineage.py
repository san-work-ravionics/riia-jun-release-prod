"""Train one instrument under a named lineage with caller-supplied date windows.

Env vars (all required except TIMESTEPS/SEED/RECORD/OUTPUT_DIR):
    INSTRUMENT        upper-case instrument id
    LINEAGE_NAME      lineage name used in the model filename
    TRAIN_END         inclusive last date for training (YYYY-MM-DD)
    VAL_START         first date for validation window
    VAL_END           last date for validation window
    BACKTEST_START    first date for backtest window (runs to present)
    TIMESTEPS         default 50000
    SEED              default 42
    RECORD            default 1 — set 0 to skip training_history.csv append
    OUTPUT_DIR        default <settings.model.path>/<INSTRUMENT>

Usage:
    INSTRUMENT=JIOFIN LINEAGE_NAME=jiofin_v1 \\
    TRAIN_END=2025-07-31 VAL_START=2025-08-01 VAL_END=2026-03-31 BACKTEST_START=2026-04-01 \\
    TIMESTEPS=50000 \\
    ~/work/py-shared-env/dev/bin/python3 scripts/train_instrument_lineage.py
"""
from __future__ import annotations

import json
import os
import sys
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


def _require(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"[abort] {name} env var is required")
    return v


INSTRUMENT     = _require("INSTRUMENT").upper()
LINEAGE_NAME   = _require("LINEAGE_NAME")
TRAIN_END      = _require("TRAIN_END")
VAL_START      = _require("VAL_START")
VAL_END        = _require("VAL_END")
BACKTEST_START = _require("BACKTEST_START")
TIMESTEPS      = int(os.environ.get("TIMESTEPS", "50000"))
SEED           = int(os.environ.get("SEED", "42"))
RECORD         = os.environ.get("RECORD", "1") != "0"

SHARPE_FLOOR    = 1.0
MDD_CEILING_PCT = 10.0

out_dir = Path(os.environ.get("OUTPUT_DIR") or Path(settings.model.path) / INSTRUMENT)
out_dir.mkdir(parents=True, exist_ok=True)

# ── 1. Data + indicators ──────────────────────────────────────────────────────
csv_path = find_instrument_csv(INSTRUMENT)
df = calculate_indicators(load_ohlcv_csv(str(csv_path)))
print(f"[data] {INSTRUMENT}: {csv_path} — {len(df)} rows "
      f"({df.index.min().date()} → {df.index.max().date()})")

train_df    = df.loc[:TRAIN_END]
val_df      = df.loc[VAL_START:VAL_END]
backtest_df = df.loc[BACKTEST_START:]
print(f"[split] train={len(train_df)}  val={len(val_df)}  backtest={len(backtest_df)}")
for name, frame in (("train", train_df), ("val", val_df), ("backtest", backtest_df)):
    if len(frame) < 60:
        sys.exit(f"[abort] {name} window too small for {INSTRUMENT}: {len(frame)} rows")

# ── 2. Per-instrument config ──────────────────────────────────────────────────
defaults   = load_instrument_defaults(INSTRUMENT)
env_config = load_instrument_env_config(INSTRUMENT)
print(f"[config] episode_length={env_config.episode_length}  "
      f"lr={defaults.get('learning_rate', 1e-4)}  "
      f"exploration={defaults.get('exploration_pct', 0.5)}")

# ── 3. Train ──────────────────────────────────────────────────────────────────
model_name = f"rita_ddqn_v2_{INSTRUMENT.lower()}_{LINEAGE_NAME}"
print(f"[train] {model_name}  timesteps={TIMESTEPS}  seed={SEED} …")
model, _ = train_agent_v2(
    train_df=train_df,
    output_dir=str(out_dir),
    timesteps=TIMESTEPS,
    learning_rate=float(defaults.get("learning_rate", 1e-4)),
    buffer_size=int(defaults.get("buffer_size", 50_000)),
    exploration_fraction=float(defaults.get("exploration_pct", 0.5)),
    seed=SEED,
    model_name=model_name,
    env_config=env_config,
)
model_path = out_dir / f"{model_name}.zip"
print(f"[train] saved → {model_path}")


# ── 4. Evaluate ───────────────────────────────────────────────────────────────
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


val_perf = _episode_metrics(val_df, f"val {VAL_START[:7]}–{VAL_END[:7]}")
bt_perf  = _episode_metrics(backtest_df, f"backtest {BACKTEST_START[:7]}+")

# ── 5. Record ─────────────────────────────────────────────────────────────────
if RECORD:
    tracker = TrainingTracker(str(out_dir))
    round_num = tracker.record_round(
        training_metrics={"timesteps_trained": TIMESTEPS, "source": "trained",
                          "seed": SEED, "lineage": LINEAGE_NAME},
        val_metrics=val_perf,
        backtest_metrics=bt_perf,
        notes=f"{LINEAGE_NAME} 50k seed{SEED} {model_name}",
    )
    print(f"[tracker] round {round_num} → {tracker.history_path}")
else:
    print("[tracker] RECORD=0 — history append skipped")

print("[SUMMARY] " + json.dumps({
    "instrument": INSTRUMENT,
    "lineage": LINEAGE_NAME,
    "timesteps": TIMESTEPS,
    "model_path": str(model_path),
    "val_sharpe": round(float(val_perf.get("sharpe_ratio", 0.0)), 4),
    "val_mdd_pct": round(float(val_perf.get("max_drawdown_pct", 0.0)), 2),
    "backtest_sharpe": round(float(bt_perf.get("sharpe_ratio", 0.0)), 4),
    "backtest_mdd_pct": round(float(bt_perf.get("max_drawdown_pct", 0.0)), 2),
    "constraints_met": bool(val_perf.get("constraints_met") and bt_perf.get("constraints_met")),
}, indent=2))
