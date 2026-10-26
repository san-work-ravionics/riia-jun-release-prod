"""F44 P3 — DDQN v2 model replay (``core/goal_model_runs.py``) and the additive
``run_episode_v2`` keywords (design rev 1 A3, R2-2, N7).

DoD items covered here:
- golden frozen / additive only: with default arguments ``run_episode_v2`` is byte-identical to
  the pre-P3 function (verbatim copy below, from commit 51c07d8)
- train/eval alignment: every replay observation — including today's ``predict_last`` one —
  equals the observation ``RIIATradingEnvV2`` builds at the same step (episode length,
  ``days_remaining``, DSR moments, drawdown, clip)
- episodes of the training ``episode_length`` anchored after ``train_end``; state resets; oob_bars
- lineage split AST-parsed from the training script and pinned to the registry
- deterministic output
"""
from __future__ import annotations

import pickle
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from stable_baselines3 import DQN

from rita.config import get_settings
from rita.core.goal_model_runs import (
    ACTION_NAMES,
    ModelRun,
    _episode_oob,
    check_bad_data,
    check_compat,
    parse_lineage_split,
    required_columns,
    run_policy,
    window_frame,
)
from rita.core.instrument_config import DEFAULT_ENV_CONFIG, InstrumentEnvConfig
from rita.core.performance import compute_all_metrics
from rita.core.trading_env_v2 import (
    _ACTION_MAP,
    _STRUCTURAL_BASE_COLS,
    RIIATradingEnvV2,
    _ema_ratio_enabled,
    _tol_norm,
    run_episode_v2,
)

from .f44_p3_helpers import SPLIT, PolicyModel, indicator_frame

_ROOT = Path(__file__).resolve().parents[2]


# Pre-P3 run_episode_v2, verbatim (git show 51c07d8:src/rita/core/trading_env_v2.py).
def _reference_run_episode_v2(
    model: DQN,
    df: pd.DataFrame,
    risk_tolerance: str = "medium",
    env_config: InstrumentEnvConfig | None = None,
) -> dict:
    """Run the V2 model deterministically through the full DataFrame.

    ``risk_tolerance`` pins the tolerance for evaluation (one of low/medium/high)
    so tolerance_norm is computed consistently. Returns the same shape as golden
    ``run_episode`` plus ``hedged_steps`` / ``hedge_usage_pct``.

    ``env_config`` (Phase 3.6) must be the SAME config used to train ``model``
    for the observation encoding and reward/eval mechanics to line up —
    train/eval consistency.
    """
    cfg = env_config or DEFAULT_ENV_CONFIG
    n_obs = model.observation_space.shape[0]
    mdd_tol = cfg.risk_tolerance_mdd.get(risk_tolerance, cfg.risk_tolerance_mdd["medium"])

    required = list(_STRUCTURAL_BASE_COLS)
    has_ema = _ema_ratio_enabled(df, cfg)
    if n_obs >= 14 and has_ema:
        required.append("ema_ratio")

    data = df.dropna(subset=required).copy()
    if len(data) == 0:
        raise ValueError("DataFrame has no valid rows after dropping NaN indicators.")

    tol_feat = _tol_norm(mdd_tol)
    portfolio_value = 1.0
    peak_value = 1.0
    portfolio_values = [1.0]
    benchmark_values = [1.0]
    allocations: list[float] = []
    hedge_flags: list[float] = []
    dates = [data.index[0]]
    close_prices = [float(data["Close"].iloc[0])]

    prev_alloc = 0.0
    prev_hedged = 0.0
    A = 0.0
    B = 0.0

    for i in range(len(data) - 1):
        row = data.iloc[i]
        current_dd = (portfolio_value - peak_value) / peak_value
        obs_list = [
            float(np.clip(row["daily_return"] * 10, -3, 3)),
            float(np.clip(row["rsi_14"] / 100.0, 0, 1)),
            float(np.clip((row["macd"] / row["Close"]) * 1000, -3, 3)),
            float(np.clip(row["bb_pct_b"], -0.5, 1.5)),
            float(np.clip(row["trend_score"], -1, 1)),
            float(prev_alloc),
            float(1.0 - i / len(data)),
            float(np.clip(row["atr_14"] / row["Close"] * 100, 0, 3)),
        ]
        if n_obs >= 14 and has_ema:
            obs_list.append(float(np.clip((row["ema_ratio"] - 1.0) * 20, -3, 3)))
        # Phase 3.5: running Sharpe moments.
        obs_list.append(float(np.clip(A * 100, -3, 3)))
        obs_list.append(float(np.clip(B * 1000, 0, 3)))
        # Drawdown relative to hard MDD limit.
        obs_list.append(float(np.clip(current_dd / cfg.hard_mdd_limit, 0, 3)))
        obs_list.append(float(prev_hedged))
        obs_list.append(tol_feat)

        obs = np.array(obs_list, dtype=np.float32)
        action, _ = model.predict(obs, deterministic=True)
        allocation, hedged = _ACTION_MAP[int(action)]

        next_row = data.iloc[i + 1]
        daily_ret = float(next_row["daily_return"])
        if hedged:
            effective_ret = max(daily_ret, cfg.hedge_daily_floor)
            portfolio_ret = allocation * effective_ret - cfg.hedge_cost_per_day
        else:
            portfolio_ret = allocation * daily_ret
        portfolio_value *= (1 + portfolio_ret)
        peak_value = max(peak_value, portfolio_value)

        # Update running moments for DSR obs alignment with training.
        R_t = portfolio_ret - cfg.rf_daily
        A += cfg.dsr_eta * (R_t - A)
        B += cfg.dsr_eta * (R_t ** 2 - B)

        bench_value = benchmark_values[-1] * (1 + daily_ret)

        portfolio_values.append(portfolio_value)
        benchmark_values.append(bench_value)
        allocations.append(allocation)
        hedge_flags.append(1.0 if hedged else 0.0)
        dates.append(data.index[i + 1])
        close_prices.append(float(next_row["Close"]))
        prev_alloc = allocation
        prev_hedged = 1.0 if hedged else 0.0

    port_arr = np.array(portfolio_values)
    bench_arr = np.array(benchmark_values)
    perf = compute_all_metrics(port_arr, bench_arr)

    alloc_arr = np.array(allocations)
    perf["total_trades"] = int((np.abs(np.diff(alloc_arr)) > 0).sum()) if len(alloc_arr) > 1 else 0

    hedged_steps = int(sum(hedge_flags))
    return {
        "portfolio_values": portfolio_values,
        "benchmark_values": benchmark_values,
        "allocations":      allocations,
        "hedge_flags":      hedge_flags,
        "hedged_steps":     hedged_steps,
        "hedge_usage_pct":  round(100 * hedged_steps / max(1, len(hedge_flags)), 2),
        "daily_returns":    list(np.diff(port_arr) / port_arr[:-1]),
        "dates":            pd.DatetimeIndex(dates),
        "close_prices":     close_prices,
        "performance":      perf,
    }


# ── default path byte parity ───────────────────────────────────────────────────

@pytest.mark.parametrize("with_ema", [True, False])
@pytest.mark.parametrize("tol", ["low", "medium", "high"])
def test_default_path_is_byte_identical_to_pre_p3(with_ema, tol):
    df = indicator_frame(seed=3, start="2023-01-01", end="2023-12-31", with_ema=with_ema)
    df.iloc[5, df.columns.get_loc("daily_return")] = 1.7   # > +100 % step: clip must stay off
    cfg = InstrumentEnvConfig(rf_daily=0.0001)
    n_obs = 14 if with_ema else 13
    new = run_episode_v2(PolicyModel(n_obs), df, tol, cfg)
    ref = _reference_run_episode_v2(PolicyModel(n_obs), df, tol, cfg)
    assert list(new) == list(ref)
    assert pickle.dumps(new) == pickle.dumps(ref)
    # default env_config too
    assert pickle.dumps(run_episode_v2(PolicyModel(n_obs), df)) == \
        pickle.dumps(_reference_run_episode_v2(PolicyModel(n_obs), df))


def test_keywords_are_keyword_only():
    import inspect

    params = inspect.signature(run_episode_v2).parameters
    for name in ("days_denominator", "predict_last", "clip_step_return"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert params[name].default in (None, False)


def test_clip_step_return_matches_training_clip():
    df = indicator_frame(seed=1, start="2023-01-01", end="2023-03-31")
    df.iloc[10, df.columns.get_loc("daily_return")] = 2.5
    model = PolicyModel()
    raw = run_episode_v2(model, df, "medium", DEFAULT_ENV_CONFIG)
    clipped = run_episode_v2(model, df, "medium", DEFAULT_ENV_CONFIG, clip_step_return=True)
    assert max(raw["daily_returns"]) > 1.0
    assert max(clipped["daily_returns"]) <= 1.0 + 1e-12


def test_days_denominator_sets_days_remaining_feature():
    df = indicator_frame(seed=2, start="2023-01-01", end="2023-02-28")
    m = PolicyModel()
    run_episode_v2(m, df, "medium", DEFAULT_ENV_CONFIG, days_denominator=252)
    assert [round(float(o[6]), 6) for o in m.calls[:3]] == \
        [round(1 - i / 252, 6) for i in range(3)]


# ── train / eval observation parity (incl. today's action) ─────────────────────

@pytest.mark.parametrize("tol", ["low", "high"])
def test_replay_and_today_observations_equal_the_training_env(tol):
    L = 60
    full = indicator_frame(seed=4, start="2023-01-02", end="2023-12-29", vol=0.004)
    frame = full.iloc[:41]                       # a partial episode: today = step 40 < L
    cfg = InstrumentEnvConfig(episode_length=L, rf_daily=0.0001)
    rec = PolicyModel()
    res = run_episode_v2(rec, frame, tol, cfg, days_denominator=L, predict_last=True,
                         clip_step_return=True)
    assert "last_action" in res and len(rec.calls) == len(frame)

    env = RIIATradingEnvV2(full, episode_length=L, fixed_tolerance=tol, env_config=cfg)
    obs, _ = env.reset(seed=0)
    env._start_idx = 0
    obs = env._get_obs()
    for k, (alloc, hedged) in enumerate(zip(res["allocations"], res["hedge_flags"])):
        np.testing.assert_allclose(rec.calls[k], obs, atol=1e-6, err_msg=f"step {k}")
        action = next(a for a, (al, h) in _ACTION_MAP.items() if al == alloc and float(h) == hedged)
        obs, _r, term, _t, info = env.step(action)
        assert not term
        assert info["portfolio_value"] == pytest.approx(res["portfolio_values"][k + 1], rel=1e-12)
    # today's observation (predict_last) == the env's observation at that step
    np.testing.assert_allclose(rec.calls[-1], obs, atol=1e-6)


# ── run_policy: episodes, today, oob ───────────────────────────────────────────

def _cfg(L=40):
    return InstrumentEnvConfig(episode_length=L, rf_daily=0.0001)


def test_run_policy_consecutive_episodes_after_train_end():
    df = indicator_frame(seed=5, start="2022-06-01", end="2023-06-30")
    L = 40
    run = run_policy(PolicyModel(), df, _cfg(L), SPLIT, "medium", instrument="AEX",
                     lineage="f34p25", model_sha12="x" * 12)
    window = window_frame(df, SPLIT.train_end)
    assert run.window_start == window.index[0].date() > SPLIT.train_end
    assert run.as_of == df.index[-1].date()
    # every bar after the first has exactly one return, no gaps, no duplicates
    assert run.dates == [d.date() for d in window.index[1:]]
    assert len(run.daily_returns) == len(run.allocations) == len(window) - 1
    # episode anchors every L bars from the first bar after train_end
    assert run.episode_starts[:3] == [window.index[i].date() for i in (0, L, 2 * L)]
    # today: inside the last episode
    n = len(window)
    assert run.episode_day == (n - 1) % L and run.episode_start == run.episode_starts[-1]
    assert run.today_action in ACTION_NAMES.values()


def test_each_episode_resets_state_like_env_reset():
    df = indicator_frame(seed=6, start="2022-12-01", end="2023-04-30")
    L = 30
    rec = PolicyModel()
    run_policy(rec, df, _cfg(L), SPLIT, "medium", instrument="X", lineage="f", model_sha12="s")
    # observation 0 of each episode: allocation 0, days_remaining 1, A = B = 0, dd 0, not hedged
    for k in (0, L):   # episode 1 makes L predictions (rows 0..L-1); episode 2 starts at call L
        o = rec.calls[k]
        assert o[5] == 0.0 and o[6] == pytest.approx(1.0)
        assert o[9] == 0.0 and o[10] == 0.0 and o[11] == 0.0 and o[12] == 0.0


def test_today_on_an_episode_boundary_starts_a_new_episode():
    df = indicator_frame(seed=7, start="2022-12-01", end="2023-06-30")
    window = window_frame(df, SPLIT.train_end)
    L = 20
    df = df.iloc[: len(df) - len(window) + 2 * L + 1]     # window = exactly 2 full episodes + 1 bar
    rec = PolicyModel()
    run = run_policy(rec, df, _cfg(L), SPLIT, "low", instrument="X", lineage="f", model_sha12="s")
    assert run.episode_day == 0 and run.episode_start == run.as_of
    assert rec.calls[-1][6] == pytest.approx(1.0) and rec.calls[-1][5] == 0.0


def test_oob_bars_counts_bars_after_a_breach_inside_an_episode():
    assert _episode_oob([1.0, 1.0, 0.95, 0.89, 0.9, 0.92], -0.10) == 2
    assert _episode_oob([1.0, 1.02, 0.99], -0.10) == 0


def test_run_policy_is_deterministic_and_round_trips():
    df = indicator_frame(seed=8, start="2022-10-01", end="2023-09-30")
    a = run_policy(PolicyModel(), df, _cfg(), SPLIT, "high", instrument="X", lineage="f",
                   model_sha12="s")
    b = run_policy(PolicyModel(), df, _cfg(), SPLIT, "high", instrument="X", lineage="f",
                   model_sha12="s")
    assert a.fingerprint() == b.fingerprint()
    assert ModelRun.from_dict(a.to_dict()).fingerprint() == a.fingerprint()


def test_tolerance_is_the_only_difference_between_tau_runs():
    df = indicator_frame(seed=9, start="2022-10-01", end="2023-09-30")
    runs = {t: run_policy(PolicyModel(tol_sensitive=False), df, _cfg(), SPLIT, t,
                          instrument="X", lineage="f", model_sha12="s") for t in ("low", "high")}
    assert runs["low"].daily_returns == runs["high"].daily_returns
    assert runs["low"].tolerance_mdd == -0.08 and runs["high"].tolerance_mdd == -0.25


# ── compat + bad data ──────────────────────────────────────────────────────────

def test_check_compat_obs_width_and_actions():
    df = indicator_frame(seed=1, start="2023-01-01", end="2023-02-01")
    assert check_compat(PolicyModel(14), df, DEFAULT_ENV_CONFIG) is None
    assert check_compat(PolicyModel(13), df, DEFAULT_ENV_CONFIG) == "feature_mismatch"
    assert check_compat(PolicyModel(14, n_actions=3), df, DEFAULT_ENV_CONFIG) == "feature_mismatch"
    no_ema = InstrumentEnvConfig(feature_columns=list(_STRUCTURAL_BASE_COLS))
    assert check_compat(PolicyModel(13), df, no_ema) is None
    assert check_compat(object(), df, DEFAULT_ENV_CONFIG) == "feature_mismatch"


def test_check_bad_data():
    df = indicator_frame(seed=1, start="2023-01-01", end="2023-02-01")
    cols = required_columns(df, DEFAULT_ENV_CONFIG, 14)
    assert "ema_ratio" in cols and check_bad_data(df, cols) is None
    bad = df.copy()
    bad.iloc[3, bad.columns.get_loc("rsi_14")] = np.nan
    assert "non-finite" in check_bad_data(bad, cols)
    neg = df.copy()
    neg.iloc[4, neg.columns.get_loc("Close")] = -1.0
    assert check_bad_data(neg, cols) == "non-positive close"


# ── lineage split ──────────────────────────────────────────────────────────────

def test_parse_lineage_split_from_source():
    src = 'TRAIN_END = "2022-12-31"\nVAL_START, VAL_END = "2023-01-01", "2024-12-31"\n' \
          'BACKTEST_START = "2025-01-01"\n'
    assert parse_lineage_split(src) == SPLIT
    with pytest.raises(ValueError):
        parse_lineage_split('TRAIN_END = "2022-12-31"\n')


def test_registry_split_is_inherited_from_the_training_script():
    """train_end is never hand-set: the registry dates must equal the script's constants."""
    lin = get_settings().goal_selection.model_lineages[0]
    script = _ROOT / lin.source
    assert script.is_file()
    parsed = parse_lineage_split(script.read_text(encoding="utf-8"))
    assert (parsed.train_end, parsed.val_start, parsed.val_end, parsed.backtest_start) == \
        (lin.train_end, lin.val_start, lin.val_end, lin.backtest_start)
    assert lin.name == "f34p25" and lin.engine == "ddqn_v2"
    assert lin.pattern.format(inst="aex") == "rita_ddqn_v2_aex_f34p25.zip"


def test_split_hash_changes_with_dates():
    other = SPLIT.__class__(date(2023, 12, 31), SPLIT.val_start, SPLIT.val_end, SPLIT.backtest_start)
    assert SPLIT.split_hash() != other.split_hash()
