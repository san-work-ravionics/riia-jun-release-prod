"""Diagnostic — why RL underperforms the static baseline at LOW tolerance.

Traces RL vs static on the same held-out window at low tol:
  1. Hedge usage split by market up-day vs down-day (is RL paying carry on up-days?)
  2. RL allocation mix (is RL trimming/cashing and missing rallies?)
  3. Drawdown path + the max-DD event context.
  4. Per-breach-episode hedge coverage (did RL actually cover the breach windows?)

Read-only analysis; no model writes.
"""
from __future__ import annotations
import os
from pathlib import Path
import numpy as np

AUG_MARKER = "riia-cowork-aug-demo"
import rita.core.trading_env_v2 as tv2
assert AUG_MARKER in tv2.__file__

from rita.core.data_understanding import find_instrument_csv
from rita.core.data_loader import load_ohlcv_csv
from rita.core.technical_analyzer import calculate_indicators
from rita.core.trading_env_v2 import (
    run_episode_v2, run_static_baseline_v2, load_agent_v2, RISK_TOLERANCE_MDD,
    HEDGE_COST_PER_DAY, HEDGE_DAILY_FLOOR, temporal_split,
)

INSTRUMENT = os.environ.get("INSTRUMENT", "ASML").upper()
TOL = "low"
APP_ROOT = Path(__file__).resolve().parents[1]
mdd_tol = RISK_TOLERANCE_MDD[TOL]

csv_path = (Path.cwd() / find_instrument_csv(INSTRUMENT)).resolve()
df = calculate_indicators(load_ohlcv_csv(str(csv_path)))
_, _, val_df = temporal_split(df)   # diagnose on the same held-out TEST window
model = load_agent_v2(str(APP_ROOT / "rita_output" / "models_v2" / INSTRUMENT / f"rita_ddqn_v2_{INSTRUMENT.lower()}.zip"))

rl = run_episode_v2(model, val_df, risk_tolerance=TOL)
st = run_static_baseline_v2(val_df, risk_tolerance=TOL)
print(f"low-tol  mdd_tol={mdd_tol:.0%}  cost/day={HEDGE_COST_PER_DAY}  floor={HEDGE_DAILY_FLOOR}\n")


def market_daily_rets(res):
    b = np.array(res["benchmark_values"])
    return b[1:] / b[:-1] - 1.0  # raw market return per step (len = n_steps)


def dd_series(res):
    p = np.array(res["portfolio_values"])
    peak = np.maximum.accumulate(p)
    return (p - peak) / peak  # <= 0


def summarise(name, res):
    mkt = market_daily_rets(res)
    hedged = np.array(res["hedge_flags"], dtype=bool)
    alloc = np.array(res["allocations"])
    up = mkt > 0
    down = mkt < 0
    n = len(hedged)
    print(f"── {name} ──")
    print(f"  hedge usage      : {res['hedge_usage_pct']:.1f}%  ({hedged.sum()}/{n} steps)")
    if hedged.sum():
        print(f"  hedged on UP days  : {(hedged & up).sum():>4}  ({100*(hedged & up).sum()/hedged.sum():.0f}% of hedged) — pays carry, no protection")
        print(f"  hedged on DOWN days: {(hedged & down).sum():>4}  ({100*(hedged & down).sum()/hedged.sum():.0f}% of hedged) — floor actually helps")
    # carry bleed: cost paid on up-days where hedge gave no downside benefit
    carry_wasted = (hedged & up).sum() * HEDGE_COST_PER_DAY
    print(f"  carry paid on up-days ≈ {carry_wasted*100:.1f}% cumulative drag")
    vals, cnts = np.unique(alloc, return_counts=True)
    print(f"  allocation mix     : " + "  ".join(f"{v:.1f}×{c}" for v, c in zip(vals, cnts)))
    ds = dd_series(res)
    print(f"  max drawdown       : {ds.min()*100:.2f}%  at step {int(ds.argmin())}")
    print()
    return mkt, hedged, ds


rl_mkt, rl_h, rl_dd = summarise("RL", rl)
st_mkt, st_h, st_dd = summarise("STATIC", st)

# ── Breach episodes (contiguous windows where drawdown <= mdd_tol) ────────────
def breach_episodes(dd):
    breached = dd <= mdd_tol
    eps, start = [], None
    for i, b in enumerate(breached):
        if b and start is None:
            start = i
        elif not b and start is not None:
            eps.append((start, i - 1)); start = None
    if start is not None:
        eps.append((start, len(breached) - 1))
    return eps

# use static's dd path to define "historical breach events" (instrument-driven)
eps = breach_episodes(st_dd[1:])  # align to step index
print(f"── Breach episodes (static dd ≤ {mdd_tol:.0%}): {len(eps)} windows ──")
print(f"{'window':<16}{'len':>4}{'  RL hedge cov':>16}{'  static cov':>14}{'  RL worst dd':>14}{'  stat worst dd':>16}")
for (s, e) in eps[:12]:
    L = e - s + 1
    rl_cov = 100 * rl_h[s:e+1].sum() / L
    st_cov = 100 * st_h[s:e+1].sum() / L
    rl_wd = rl_dd[s+1:e+2].min() * 100
    st_wd = st_dd[s+1:e+2].min() * 100
    print(f"{str(s)+'–'+str(e):<16}{L:>4}{rl_cov:>14.0f}%{st_cov:>12.0f}%{rl_wd:>13.2f}%{st_wd:>15.2f}%")

print(f"\n[totals] RL final value {rl['portfolio_values'][-1]:.3f}  vs static {st['portfolio_values'][-1]:.3f}")
