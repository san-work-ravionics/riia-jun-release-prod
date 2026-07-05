"""Phase 3 — train + backtest RIIATradingEnvV2 for one instrument (aug workspace).

ISOLATION GUARANTEES (assert hard, fail fast):
  * the imported `rita` package must come from aug-demo (not jun-demo),
  * the resolved input CSV must live under aug-demo,
  * the model output dir is an explicit aug-demo path.
Nothing reads or writes the June folder.

Run:
  cd riia-cowork-aug-demo/riia-jun-release
  PYTHONPATH=$PWD/src TIMESTEPS=4000 INSTRUMENT=ASML \
      /Users/sgawde/work/py-shared-env/dev/bin/python3 scripts/train_v2.py
"""
from __future__ import annotations

import os
from pathlib import Path

AUG_MARKER = "riia-cowork-aug-demo"

import rita.core.trading_env_v2 as tv2
assert AUG_MARKER in tv2.__file__, f"NOT aug code — refusing to run: {tv2.__file__}"

from rita.core.data_understanding import find_instrument_csv
from rita.core.data_loader import load_ohlcv_csv
from rita.core.technical_analyzer import calculate_indicators
from rita.core.trading_env_v2 import train_agent_v2, run_episode_v2, temporal_split

INSTRUMENT = os.environ.get("INSTRUMENT", "ASML").upper()
TIMESTEPS = int(os.environ.get("TIMESTEPS", "4000"))
SEED = int(os.environ.get("SEED", "42"))

APP_ROOT = Path(__file__).resolve().parents[1]
assert AUG_MARKER in str(APP_ROOT), f"APP_ROOT not in aug: {APP_ROOT}"

csv_path = (Path.cwd() / find_instrument_csv(INSTRUMENT)).resolve()
assert AUG_MARKER in str(csv_path), f"CSV not under aug — refusing: {csv_path}"
assert csv_path.exists(), f"CSV missing: {csv_path}"
print(f"[isolation] rita = {tv2.__file__}")
print(f"[isolation] csv  = {csv_path}")

df = calculate_indicators(load_ohlcv_csv(str(csv_path)))
print(f"[data] {INSTRUMENT}: {len(df)} rows after indicators")

# 3-way chronological split: train (fit) → val (best-of-N selection) → test
# (untouched, for final unbiased reporting; removes selection-on-val bias).
train_df, val_df, test_df = temporal_split(df)
print(f"[split] train={len(train_df)}  val={len(val_df)}  test={len(test_df)} (test = held-out, report only)")

out_dir = str(APP_ROOT / "rita_output" / "models_v2" / INSTRUMENT)
assert AUG_MARKER in out_dir
os.makedirs(out_dir, exist_ok=True)

N_SEEDS = int(os.environ.get("N_SEEDS", "1"))
model_name = f"rita_ddqn_v2_{INSTRUMENT.lower()}"

if N_SEEDS > 1:
    from rita.core.trading_env_v2 import train_best_of_n_v2
    print(f"[train] best-of-{N_SEEDS}  timesteps={TIMESTEPS}/seed  (select by val Sharpe) …")
    model, cb, seed_info = train_best_of_n_v2(
        train_df=train_df,
        val_df=val_df,
        output_dir=out_dir,
        timesteps=TIMESTEPS,
        n_seeds=N_SEEDS,
        model_name=model_name,
    )
    print(f"[train] seed results: {seed_info['seed_results']}")
    print(f"[train] best seed = {seed_info['best_seed']}")
else:
    print(f"[train] RIIATradingEnvV2  timesteps={TIMESTEPS}  seed={SEED} …")
    model, cb = train_agent_v2(
        train_df=train_df,
        output_dir=out_dir,
        timesteps=TIMESTEPS,
        seed=SEED,
        model_name=model_name,
    )
print(f"[train] saved → {out_dir}/{model_name}.zip")

print("[backtest] run_episode_v2 on held-out TEST window, per tolerance:")
res_by_tol = {}
for tol in ("low", "medium", "high"):
    res = run_episode_v2(model, test_df, risk_tolerance=tol)
    res_by_tol[tol] = res
    p = res["performance"]
    print(f"  tol={tol:<6} sharpe={p.get('sharpe_ratio'):>6.3f}  "
          f"max_dd={p.get('max_drawdown_pct'):>7.2f}%  "
          f"hedge_usage={res['hedge_usage_pct']:>5.1f}%  "
          f"port_return={p.get('portfolio_total_return_pct', p.get('portfolio_cagr_pct')):>7.2f}")

# ── Bridge to the Agent Performance dashboard (Execution Analyst scorecard) ────
import json
import numpy as np
from datetime import datetime, timezone

res_med = res_by_tol["medium"]
daily = np.asarray(res_med["daily_returns"], dtype=float)
win_rate = float((daily >= 0).mean()) if daily.size else None


def _mean_episode_reward(mdl, frame, tol="medium", n_episodes=20):
    """Roll the trained policy through the env; return mean reward PER DECISION.

    The dashboard contract defines avg_reward as the "mean RL reward signal per
    decision" — a per-step quantity on the same scale as the per-step env reward
    (a tolerance-penalised daily portfolio return). We therefore average each
    episode's cumulative reward over its step count, NOT the raw cumulative total
    (which is unbounded and grows with episode length — a scale mismatch against
    the per-decision baseline). Computed directly from the environment so it does
    not depend on SB3's training-logger internals."""
    from rita.core.trading_env_v2 import RIIATradingEnvV2
    env = RIIATradingEnvV2(frame, fixed_tolerance=tol)
    per_decision = []
    for _ in range(n_episodes):
        obs, _ = env.reset()
        ep, steps, done = 0.0, 0, False
        while not done:
            a, _ = mdl.predict(obs, deterministic=True)
            obs, r, term, trunc, _ = env.step(int(a))
            ep += float(r)
            steps += 1
            done = term or trunc
        if steps:
            per_decision.append(ep / steps)
    return round(float(np.mean(per_decision)), 4) if per_decision else None


avg_reward = _mean_episode_reward(model, test_df, tol="medium")

base_cols = ["daily_return", "rsi_14", "macd", "macd_signal",
             "bb_pct_b", "trend_score", "Close", "atr_14"]
data_coverage = round(float(test_df[base_cols].notna().all(axis=1).mean()), 4)

summary = {
    "agent_name":      "Execution Analyst",
    "instrument":      INSTRUMENT,
    "outcome_match":   round(win_rate, 4) if win_rate is not None else None,
    "avg_reward":      avg_reward,
    "data_coverage":   data_coverage,
    "invocations":     len(res_med["allocations"]),
    "hedge_usage_pct": res_med["hedge_usage_pct"],
    "sharpe":          round(float(res_med["performance"].get("sharpe_ratio", 0.0)), 3),
    "timesteps":       TIMESTEPS,
    "trained_at":      datetime.now(timezone.utc).isoformat(),
}
perf_dir = APP_ROOT / "rita_output" / "models_v2"
perf_dir.mkdir(parents=True, exist_ok=True)
perf_path = perf_dir / f"agent_perf_v2_{INSTRUMENT.lower()}.json"
perf_path.write_text(json.dumps(summary, indent=2))
print(f"[bridge] wrote dashboard metrics → {perf_path}")
print(f"[bridge] {summary}")
print("[done]")
