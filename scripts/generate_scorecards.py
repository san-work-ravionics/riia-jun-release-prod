"""Generate RL diagnostic scorecards for all 11 F34 instruments.

Uses the f34p25 model zips + the same date-based splits as train_f34_instrument.py.
Scorecards are saved to rita_output/models_v2/<INST>/<INST>/scorecard_*.json
so the /experience/rita/agent-performance/scorecards endpoint picks them up.

Run from repo root:
    /Users/sgawde/work/py-shared-env/dev/bin/python3 scripts/generate_scorecards.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
os.chdir(APP_ROOT)

from rita.core.data_loader import load_ohlcv_csv
from rita.core.data_understanding import find_instrument_csv
from rita.core.instrument_config import load_instrument_env_config, list_instrument_ids
from rita.core.technical_analyzer import calculate_indicators
from rita.core.rl_scorecard import compute_scorecard, save_scorecard

TRAIN_END = "2022-12-31"
BACKTEST_START = "2025-01-01"

OUTPUT_BASE = APP_ROOT / "rita_output" / "models_v2"

instruments = list_instrument_ids()
print(f"Generating scorecards for {len(instruments)} instruments: {instruments}\n")

for inst in instruments:
    model_path = APP_ROOT / "models" / inst / f"rita_ddqn_v2_{inst.lower()}_f34p25.zip"
    if not model_path.exists():
        print(f"[SKIP] {inst}: no model at {model_path}")
        continue

    try:
        csv_path = find_instrument_csv(inst)
        df = calculate_indicators(load_ohlcv_csv(str(csv_path)))

        train_df = df.loc[:TRAIN_END]
        test_df = df.loc[BACKTEST_START:]

        if len(train_df) < 60 or len(test_df) < 60:
            print(f"[SKIP] {inst}: insufficient data (train={len(train_df)}, test={len(test_df)})")
            continue

        from stable_baselines3 import DQN
        model = DQN.load(str(model_path))

        env_config = load_instrument_env_config(inst)

        scorecard = compute_scorecard(
            model=model,
            test_df=test_df,
            train_df=train_df,
            episode_metrics=None,
            seed_results=None,
            env_config=env_config,
            instrument=inst,
            run_id=f"f34p25-{inst.lower()}",
        )

        out_dir = str(OUTPUT_BASE / inst)
        path = save_scorecard(scorecard, out_dir, inst, f"f34p25-{inst.lower()}")

        f1 = scorecard.get("functional", {}).get("F1_sharpe_test", {})
        print(f"[OK]   {inst}: Sharpe(test)={f1.get('value', '?'):.3f}  → {path}")

    except Exception as exc:
        print(f"[FAIL] {inst}: {exc}")
