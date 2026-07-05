"""Phase 3.5 end-to-end evaluation — signal sanity + retrain + acceptance gate.

Runs tasks 3.5.6 and 3.5.7 in sequence:
  1. Signal sanity check (Spearman corr of features vs forward returns)
  2. Train V2 with DSR reward (best-of-N seeds)
  3. Compare RL policy vs static baseline on held-out test window
  4. Report acceptance gate: Sharpe>1 AND MDD>-10% AND >= static baseline

Run:
  cd riia-cowork-aug-demo/riia-jun-release
  PYTHONPATH=$PWD/src INSTRUMENT=ASML N_SEEDS=3 TIMESTEPS=50000 \
      /Users/sgawde/work/py-shared-env/dev/bin/python3 scripts/run_phase35_eval.py

Environment variables:
  INSTRUMENT   — ticker (default: ASML)
  TIMESTEPS    — training steps per seed (default: 50000)
  N_SEEDS      — number of seeds for best-of-N (default: 3)
  SKIP_SANITY  — set to 1 to skip the signal sanity check
  SKIP_TRAIN   — set to 1 to skip training (use existing model)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

AUG_MARKER = "riia-cowork-aug-demo"

import rita.core.trading_env_v2 as tv2
assert AUG_MARKER in tv2.__file__, f"NOT aug code — refusing to run: {tv2.__file__}"

from rita.core.data_understanding import find_instrument_csv
from rita.core.data_loader import load_ohlcv_csv
from rita.core.technical_analyzer import calculate_indicators
from rita.core.trading_env_v2 import (
    temporal_split, train_best_of_n_v2, train_agent_v2,
    run_episode_v2, run_static_baseline_v2, load_agent_v2,
)

INSTRUMENT = os.environ.get("INSTRUMENT", "ASML").upper()
TIMESTEPS = int(os.environ.get("TIMESTEPS", "50000"))
N_SEEDS = int(os.environ.get("N_SEEDS", "3"))
SKIP_SANITY = os.environ.get("SKIP_SANITY", "0") == "1"
SKIP_TRAIN = os.environ.get("SKIP_TRAIN", "0") == "1"

APP_ROOT = Path(__file__).resolve().parents[1]
assert AUG_MARKER in str(APP_ROOT)

csv_path = (Path.cwd() / find_instrument_csv(INSTRUMENT)).resolve()
assert csv_path.exists(), f"CSV missing: {csv_path}"

print(f"{'=' * 70}")
print(f" Phase 3.5 Evaluation — {INSTRUMENT}")
print(f" DSR reward | hard MDD -10% | causal alignment | temporal split")
print(f"{'=' * 70}\n")

# ── Load and prepare data ────────────────────────────────────────────────────

df = calculate_indicators(load_ohlcv_csv(str(csv_path)))
train_df, val_df, test_df = temporal_split(df)
print(f"[data] {INSTRUMENT}: {len(df)} rows total")
print(f"[split] train={len(train_df)}  val={len(val_df)}  test={len(test_df)}")
print(f"[split] train: {train_df.index[0].date()} → {train_df.index[-1].date()}")
print(f"[split] val:   {val_df.index[0].date()} → {val_df.index[-1].date()}")
print(f"[split] test:  {test_df.index[0].date()} → {test_df.index[-1].date()}\n")

# ── Task 3.5.6: Signal sanity check ─────────────────────────────────────────

if not SKIP_SANITY:
    print(f"{'─' * 70}")
    print(" Task 3.5.6 — Signal Sanity Check")
    print(f" Spearman rank corr of features vs 1/2/5-day forward returns (train split)")
    print(f"{'─' * 70}")

    features = ["rsi_14", "macd", "bb_pct_b", "trend_score", "atr_14"]
    if "ema_ratio" in train_df.columns and not train_df["ema_ratio"].isna().all():
        features.append("ema_ratio")

    horizons = [1, 2, 5]
    any_pass = False
    results = []

    for horizon in horizons:
        fwd_ret = train_df["daily_return"].shift(-horizon)
        valid = fwd_ret.notna()
        for feat in features:
            feat_valid = train_df[feat].notna() & valid
            if feat_valid.sum() < 30:
                continue
            rho, p = spearmanr(
                train_df.loc[feat_valid, feat],
                fwd_ret[feat_valid],
            )
            passed = abs(rho) > 0.02 and p < 0.05
            if passed:
                any_pass = True
            results.append((horizon, feat, rho, p, passed))

    print(f"\n {'horizon':<10} {'feature':<14} {'rho':>8} {'p-value':>10} {'verdict':<6}")
    print(f" {'-'*10} {'-'*14} {'-'*8} {'-'*10} {'-'*6}")
    for horizon, feat, rho, p, passed in results:
        if passed or abs(rho) > 0.01:
            print(f" {horizon:>3}d       {feat:<14} {rho:>8.4f} {p:>10.4f} {'PASS' if passed else '    '}")

    print()
    if any_pass:
        print(" [3.5.6 GATE] PASS — at least one feature has predictive signal.")
        print("              Proceeding to training.\n")
    else:
        print(" [3.5.6 GATE] FAIL — no feature meets |rho|>0.02 & p<0.05.")
        print("              Prescribed outcome: ship static baseline; RL only where it adds edge.")
        print("              Stopping evaluation.\n")
        sys.exit(1)
else:
    print("[3.5.6] Skipped (SKIP_SANITY=1)\n")

# ── Task 3.5.7a: Train V2 with DSR reward ───────────────────────────────────

out_dir = str(APP_ROOT / "rita_output" / "models_v2" / INSTRUMENT)
os.makedirs(out_dir, exist_ok=True)
model_name = f"rita_ddqn_v2_{INSTRUMENT.lower()}"
model_path = Path(out_dir) / f"{model_name}.zip"

if not SKIP_TRAIN:
    print(f"{'─' * 70}")
    print(f" Task 3.5.7a — Train V2 (DSR reward)")
    print(f" seeds={N_SEEDS}  timesteps={TIMESTEPS}/seed  select=val Sharpe")
    print(f"{'─' * 70}\n")

    if N_SEEDS > 1:
        model, cb, seed_info = train_best_of_n_v2(
            train_df=train_df,
            val_df=val_df,
            output_dir=out_dir,
            timesteps=TIMESTEPS,
            n_seeds=N_SEEDS,
            model_name=model_name,
            test_df=test_df,
        )
        print(f"\n[train] seed results:")
        for sr in seed_info["seed_results"]:
            print(f"  seed {sr['seed']}: val_sharpe={sr['val_sharpe']:.4f}  "
                  f"hedge={sr['hedge_usage_pct']:.1f}%")
        print(f"[train] best seed = {seed_info['best_seed']}")
        if "test_sharpe" in seed_info:
            print(f"[train] test_sharpe={seed_info['test_sharpe']:.4f}  "
                  f"test_mdd={seed_info['test_mdd']:.4f}  "
                  f"test_return={seed_info['test_return']:.4f}")
    else:
        model, cb = train_agent_v2(
            train_df=train_df,
            output_dir=out_dir,
            timesteps=TIMESTEPS,
            seed=42,
            model_name=model_name,
        )

    print(f"[train] saved → {model_path}\n")
else:
    print(f"[train] Skipped (SKIP_TRAIN=1) — loading {model_path}")
    assert model_path.exists(), f"Model not found: {model_path}"
    model = load_agent_v2(str(model_path))
    print()

# ── Task 3.5.7b: Evaluate on held-out test window ───────────────────────────

print(f"{'─' * 70}")
print(f" Task 3.5.7b — RL vs Static Baseline (held-out test window)")
print(f"{'─' * 70}\n")

SHARPE_SLACK = 0.05
MDD_SLACK_PCT = 0.50


def _m(res):
    p = res["performance"]
    return {
        "sharpe": float(p.get("sharpe_ratio", 0.0)),
        "max_dd": float(p.get("max_drawdown_pct", 0.0)),
        "ret": float(p.get("portfolio_total_return_pct",
                           p.get("portfolio_cagr_pct", 0.0))),
        "hedge_pct": float(res["hedge_usage_pct"]),
    }


hdr = (f" {'tol':<7} {'Sharpe (RL/stat)':<20} {'maxDD% (RL/stat)':<22} "
       f"{'hedge% (RL/stat)':<20} {'return (RL/stat)':<22} verdict")
print(hdr)
print(f" {'-' * (len(hdr) - 1)}")

all_pass_nw = True
gate_results = {}
for tol in ("low", "medium", "high"):
    rl = _m(run_episode_v2(model, test_df, risk_tolerance=tol))
    st = _m(run_static_baseline_v2(test_df, risk_tolerance=tol))

    dd_ok = rl["max_dd"] >= st["max_dd"] - MDD_SLACK_PCT
    sharpe_ok = rl["sharpe"] >= st["sharpe"] - SHARPE_SLACK
    ok = dd_ok and sharpe_ok
    all_pass_nw = all_pass_nw and ok
    gate_results[tol] = {"rl": rl, "static": st, "pass": ok}

    print(f" {tol:<7} "
          f"{rl['sharpe']:>6.3f} / {st['sharpe']:<7.3f}   "
          f"{rl['max_dd']:>7.2f} / {st['max_dd']:<7.2f}     "
          f"{rl['hedge_pct']:>5.1f} / {st['hedge_pct']:<5.1f}      "
          f"{rl['ret']:>7.2f} / {st['ret']:<7.2f}    "
          f"{'PASS' if ok else 'FAIL'}")

# ── Acceptance gate ──────────────────────────────────────────────────────────

print(f"\n{'=' * 70}")
print(f" ACCEPTANCE GATE — Phase 3.5")
print(f"{'=' * 70}\n")

med = gate_results["medium"]["rl"]
sharpe_gate = med["sharpe"] > 1.0
mdd_gate = med["max_dd"] > -10.0
baseline_gate = all_pass_nw

print(f" AC-1  Sharpe > 1.0 on test (medium):   {med['sharpe']:.3f}  "
      f"{'PASS' if sharpe_gate else 'FAIL'}")
print(f" AC-2  MDD > -10% on test (medium):     {med['max_dd']:.2f}%  "
      f"{'PASS' if mdd_gate else 'FAIL'}")
print(f" AC-3  RL >= static baseline (all tol):  "
      f"{'PASS' if baseline_gate else 'FAIL'}")

all_pass = sharpe_gate and mdd_gate and baseline_gate
print(f"\n {'PASS ✅' if all_pass else 'FAIL ❌'}  "
      f"— Phase 3.5 acceptance gate {'met' if all_pass else 'not met'}.")

if not all_pass:
    print("\n Diagnosis:")
    if not sharpe_gate:
        print(f"   Sharpe {med['sharpe']:.3f} < 1.0 — DSR may need more timesteps, "
              f"or features lack sufficient signal for this instrument.")
    if not mdd_gate:
        print(f"   MDD {med['max_dd']:.2f}% ≤ -10% — hard termination at -10% should "
              f"prevent this; check for a data/eval mismatch.")
    if not baseline_gate:
        for tol, r in gate_results.items():
            if not r["pass"]:
                print(f"   tol={tol}: RL underperforms static "
                      f"(sharpe {r['rl']['sharpe']:.3f} vs {r['static']['sharpe']:.3f}, "
                      f"mdd {r['rl']['max_dd']:.2f} vs {r['static']['max_dd']:.2f})")

print(f"\n{'=' * 70}")
