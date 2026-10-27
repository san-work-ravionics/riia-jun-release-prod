"""F44 P4 — rationale parity: the observation ``core/jarvis_rationale`` recomputes equals the
observation the replay passed to ``model.predict`` on every bar.

- DDQN v2: ``run_policy`` (P3 replay: consecutive training-length episodes, ``predict_last`` on
  today's partial episode) with a recording policy;
- ASTA: ``run_episode_asta`` over a prepared frame, plus the extra obs for today's action.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rita.core.asta_trading_env import (
    _ASTA_NUMERIC_COLS,
    _STRUCTURAL_BASE_COLS,
    _ema_ratio_enabled,
    _prepare_asta_columns,
    run_episode_asta,
)
from rita.core.goal_model_runs import run_policy, window_frame
from rita.core.instrument_config import DEFAULT_ENV_CONFIG
from rita.core.jarvis_rationale import (
    action_name,
    asta_observations,
    asta_rationale,
    v2_episode_observations,
    v2_rationale,
)

from .f44_p3_helpers import SPLIT, PolicyModel, indicator_frame


@pytest.mark.parametrize("tolerance", ["low", "medium", "high"])
@pytest.mark.parametrize("with_ema", [True, False])
def test_v2_observation_parity_on_every_bar(tolerance, with_ema):
    cfg = DEFAULT_ENV_CONFIG
    df = indicator_frame(seed=3, drift=0.0005, with_ema=with_ema, end="2026-06-30")
    data = window_frame(df, SPLIT.train_end)
    use_ema = _ema_ratio_enabled(data, cfg)
    model = PolicyModel(n_obs=14 if use_ema else 13)
    run = run_policy(model, df, cfg, SPLIT, tolerance, instrument="E1", lineage="f34p25", model_sha12="x" * 12)

    L, n = int(cfg.episode_length), len(data)
    expected: list[np.ndarray] = []
    a = 0
    while a < n - 1:
        end = min(a + L, n - 1)
        frame = data.iloc[a:end + 1]
        today_inside = end == n - 1 and (end - a) < L
        obs = v2_episode_observations(frame, run.allocations[a:end], run.hedge_flags[a:end], cfg, tolerance, L,
                                      use_ema)
        expected.extend(obs if today_inside else obs[:-1])
        a = end
    if len(model.calls) == len(expected) + 1:      # today closed a full episode: a fresh 1-bar one
        expected.extend(v2_episode_observations(data.iloc[n - 1:n], [], [], cfg, tolerance, L, use_ema))
    assert len(model.calls) == len(expected) and len(expected) > 300
    for k, (got, exp) in enumerate(zip(model.calls, expected)):
        np.testing.assert_allclose(got, exp, rtol=0, atol=1e-6, err_msg=f"bar {k}")


def test_v2_rationale_rows_match_the_observation():
    cfg = DEFAULT_ENV_CONFIG
    df = indicator_frame(seed=5)
    data = window_frame(df, SPLIT.train_end)
    obs = v2_episode_observations(data.iloc[:30], [1.0] * 29, [0.0] * 29, cfg, "medium", 252, True)
    inputs, state = v2_rationale(data.iloc[29], obs[29], "medium", True)
    names = [i["name"] for i in inputs]
    assert names == ["daily_return", "rsi_14", "macd_over_close", "bb_pct_b", "trend_score", "atr_over_close",
                     "ema_ratio"]
    assert inputs[1]["raw"] == pytest.approx(float(data.iloc[29]["rsi_14"]))
    assert inputs[1]["model_input"] == pytest.approx(float(obs[29][1]))
    st = {s["name"]: s["value"] for s in state}
    assert st["prev_allocation"] == 1.0 and st["tolerance_level"] == "medium"
    assert st["days_remaining"] == pytest.approx(1 - 29 / 252, abs=1e-6)


def _asta_frame(seed: int = 1, n_days: str = "2026-06-30") -> pd.DataFrame:
    df = indicator_frame(seed=seed, start="2024-01-01", end=n_days)
    k = np.arange(len(df))
    df["asta_signal"] = np.where(k % 17 == 0, "BUY", np.where(k % 23 == 0, "SELL", "HOLD"))
    df["asta_confidence"] = 0.5 + 0.4 * np.sin(k / 5.0)
    df["stoch_k"] = 50 + 40 * np.sin(k / 6.0)
    df["adx"] = 25 + 10 * np.cos(k / 8.0)
    df["tide_macd_hist_uptick"] = k % 3 == 0
    df["tide_macd_hist_downtick"] = k % 5 == 0
    df["bb_squeeze"] = k % 7 == 0
    df["vol_ratio"] = 1.0 + 0.5 * np.sin(k / 4.0)
    return df


class _AstaPolicy(PolicyModel):
    def __init__(self, n_obs: int):
        super().__init__(n_obs=n_obs, tol_sensitive=False)

    def predict(self, obs, deterministic=True):
        obs = np.asarray(obs, dtype=np.float32)
        self.calls.append(obs.copy())
        score = float(obs[0]) + 0.3 * float(obs[-7])     # daily return + ASTA signal
        return np.array(2 if score > 0.05 else 3 if score > 0 else 1 if score > -0.1 else 0), None


@pytest.mark.parametrize("with_ema", [True, False])
def test_asta_observation_parity_on_every_bar(with_ema):
    cfg = DEFAULT_ENV_CONFIG
    df = _asta_frame()
    if not with_ema:
        df = df.drop(columns=["ema_ratio"])
    prepared = _prepare_asta_columns(df)
    use_ema = _ema_ratio_enabled(prepared, cfg)
    model = _AstaPolicy(21 if use_ema else 20)
    res = run_episode_asta(model, df, env_config=cfg)
    required = list(_STRUCTURAL_BASE_COLS) + list(_ASTA_NUMERIC_COLS) + (["ema_ratio"] if use_ema else [])
    data = prepared.dropna(subset=required)
    obs = asta_observations(data, res["allocations"], res["hedge_flags"], cfg, "medium", use_ema)
    assert len(obs) == len(model.calls) + 1          # + today's observation (not predicted by the replay)
    for k, (got, exp) in enumerate(zip(model.calls, obs)):
        np.testing.assert_allclose(got, exp, rtol=0, atol=1e-6, err_msg=f"bar {k}")
    assert obs[-1].shape == obs[0].shape
    inputs, state = asta_rationale(data.iloc[10], obs[10], use_ema)
    names = {i["name"] for i in inputs}
    assert {"asta_signal_enc", "asta_confidence", "stoch_k", "adx", "vol_ratio"} <= names
    assert not any(s["name"] == "tolerance_level" for s in state)


def test_action_names():
    assert [action_name(*a) for a in ((0, 0), (0.5, 0), (1, 0), (1, 1))] == ["cash", "half", "full", "hedged"]
