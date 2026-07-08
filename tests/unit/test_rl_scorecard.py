"""Unit tests for rita.core.rl_scorecard (Feature 32, Phase 3.6).

Covers: all 10 parameters (F1-F5, T1-T5) computed from a synthetic episode,
JSON persistence (including NaN-safety), and a handful of edge cases
(insufficient regime data, single-seed T4, missing episode_metrics for T3).
"""
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rita.core.rl_scorecard import compute_scorecard, save_scorecard


def _make_regime_df(n: int = 300, seed: int = 0) -> pd.DataFrame:
    """Synthetic OHLCV+indicators frame with a bull -> bear -> sideways price path
    so market-regime classification (and therefore F3/F5/T5) has real per-regime
    buckets to work with."""
    rng = np.random.default_rng(seed)
    third = n // 3
    prices = [100.0]
    for i in range(1, n):
        if i < third:
            step = 0.0025 + rng.normal(0, 0.001)       # smooth uptrend -> bull
        elif i < 2 * third:
            noise_scale = 0.002 + 0.02 * ((i - third) / third)
            step = -0.003 + rng.normal(0, noise_scale)  # volatile downtrend -> bear
        else:
            step = rng.normal(0, 0.001)                 # flat/noisy -> sideways
        prices.append(prices[-1] * (1 + step))

    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    close = pd.Series(prices, index=idx)
    daily_return = close.pct_change().fillna(0.0)

    return pd.DataFrame({
        "Close":        close,
        "daily_return": daily_return,
        "rsi_14":       np.full(n, 55.0),
        "macd":         np.full(n, 1.5),
        "macd_signal":  np.full(n, 1.0),
        "bb_pct_b":     np.full(n, 0.5),
        "trend_score":  np.full(n, 0.2),
        "atr_14":       np.full(n, 2.0),
    }, index=idx)


class _CyclicStubModel:
    """Cycles through all 4 actions so entropy/T5 have non-degenerate data."""

    def __init__(self, n_obs: int = 13):
        self.observation_space = type("S", (), {"shape": (n_obs,)})()
        self._i = 0

    def predict(self, obs, deterministic=True):
        a = self._i % 4
        self._i += 1
        return np.array(a), None


class _FixedStubModel:
    def __init__(self, action: int, n_obs: int = 13):
        self.observation_space = type("S", (), {"shape": (n_obs,)})()
        self._action = action

    def predict(self, obs, deterministic=True):
        return np.array(self._action), None


def _synthetic_episode_metrics(n: int = 50) -> list[dict]:
    """Reward approaches a final plateau ~80% of the way through training."""
    final = 1.0
    rewards = [final * (1 - math.exp(-i / 10)) for i in range(n)]
    return [{"episode": i + 1, "timestep": i * 1000, "reward": r, "loss": 0.1} for i, r in enumerate(rewards)]


def test_compute_scorecard_returns_all_10_parameters():
    train_df = _make_regime_df(n=300, seed=1)
    test_df = _make_regime_df(n=300, seed=2)
    model = _CyclicStubModel(n_obs=13)

    scorecard = compute_scorecard(
        model=model,
        test_df=test_df,
        train_df=train_df,
        episode_metrics=_synthetic_episode_metrics(),
        seed_results=[{"seed": 0, "val_sharpe": 0.8}, {"seed": 1, "val_sharpe": 1.1}, {"seed": 2, "val_sharpe": 0.6}],
        instrument="TESTINSTR",
        run_id="run123",
    )

    functional_keys = {
        "F1_sharpe_test", "F2_max_drawdown_test", "F3_market_regime_performance",
        "F4_win_rate", "F5_baseline_relative",
    }
    technical_keys = {
        "T1_action_entropy", "T2_train_test_sharpe_gap", "T3_reward_convergence_pct",
        "T4_seed_consistency_cv", "T5_per_regime_action_distribution",
    }
    assert functional_keys.issubset(scorecard["functional"].keys())
    assert technical_keys.issubset(scorecard["technical"].keys())
    assert scorecard["instrument"] == "TESTINSTR"
    assert scorecard["run_id"] == "run123"
    assert scorecard["config_source"] == "default"


def test_f1_f2_are_numeric_and_bounded():
    df = _make_regime_df(n=200, seed=3)
    model = _FixedStubModel(action=2)
    sc = compute_scorecard(model=model, test_df=df, train_df=df)
    assert isinstance(sc["functional"]["F1_sharpe_test"]["value"], float)
    mdd = sc["functional"]["F2_max_drawdown_test"]["value"]
    assert -1.0 <= mdd <= 0.0


def test_f3_per_regime_has_all_three_regimes():
    df = _make_regime_df(n=300, seed=4)
    model = _CyclicStubModel()
    sc = compute_scorecard(model=model, test_df=df, train_df=df)
    per_regime = sc["functional"]["F3_market_regime_performance"]
    assert set(per_regime.keys()) == {"bull", "bear", "sideways"}
    for regime, data in per_regime.items():
        assert "sharpe" in data and "n_days" in data


def test_t1_action_entropy_max_for_uniform_cyclic_actions():
    df = _make_regime_df(n=400, seed=5)
    model = _CyclicStubModel()
    sc = compute_scorecard(model=model, test_df=df, train_df=df)
    entropy = sc["technical"]["T1_action_entropy"]["value"]
    max_entropy = sc["technical"]["T1_action_entropy"]["max_possible"]
    assert max_entropy == pytest.approx(2.0, abs=1e-6)
    # Cycling uniformly through 4 actions should approach max entropy.
    assert entropy > 1.9


def test_t1_action_entropy_zero_for_single_action_policy():
    df = _make_regime_df(n=200, seed=6)
    model = _FixedStubModel(action=2)  # always "full"
    sc = compute_scorecard(model=model, test_df=df, train_df=df)
    assert sc["technical"]["T1_action_entropy"]["value"] == pytest.approx(0.0)


def test_t3_reward_convergence_within_bounds():
    df = _make_regime_df(n=200, seed=7)
    model = _FixedStubModel(action=2)
    sc = compute_scorecard(
        model=model, test_df=df, train_df=df,
        episode_metrics=_synthetic_episode_metrics(60),
    )
    pct = sc["technical"]["T3_reward_convergence_pct"]["value"]
    assert pct is not None
    assert 0.0 < pct <= 100.0


def test_t3_missing_episode_metrics_reports_insufficient_data():
    df = _make_regime_df(n=100, seed=8)
    model = _FixedStubModel(action=2)
    sc = compute_scorecard(model=model, test_df=df, train_df=df, episode_metrics=None)
    t3 = sc["technical"]["T3_reward_convergence_pct"]
    assert t3["value"] is None
    assert t3["note"] == "insufficient_data"


def test_t4_single_seed_reports_insufficient_seeds():
    df = _make_regime_df(n=100, seed=9)
    model = _FixedStubModel(action=2)
    sc = compute_scorecard(model=model, test_df=df, train_df=df, seed_results=[{"val_sharpe": 0.9}])
    t4 = sc["technical"]["T4_seed_consistency_cv"]
    assert t4["value"] is None
    assert t4["note"] == "insufficient_seeds"


def test_t4_multi_seed_cv_computed():
    df = _make_regime_df(n=100, seed=10)
    model = _FixedStubModel(action=2)
    seed_results = [{"val_sharpe": 1.0}, {"val_sharpe": 1.2}, {"val_sharpe": 0.8}]
    sc = compute_scorecard(model=model, test_df=df, train_df=df, seed_results=seed_results)
    t4 = sc["technical"]["T4_seed_consistency_cv"]
    assert t4["value"] is not None
    assert t4["n_seeds"] == 3


def test_t5_regime_blind_true_for_constant_action_policy():
    """A policy that always takes the same action, in every regime, must be
    flagged regime-blind (identical distribution across regimes -> JSD ~ 0)."""
    df = _make_regime_df(n=300, seed=11)
    model = _FixedStubModel(action=2)
    sc = compute_scorecard(model=model, test_df=df, train_df=df)
    t5 = sc["technical"]["T5_per_regime_action_distribution"]
    assert t5["regime_blind"] is True


def test_baseline_relative_divide_by_zero_safe():
    """F5: a flat (zero-vol) df could make the static baseline Sharpe ~0 —
    must not raise ZeroDivisionError (edge case 5)."""
    n = 60
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    flat_df = pd.DataFrame({
        "Close": np.full(n, 100.0),
        "daily_return": np.zeros(n),
        "rsi_14": np.full(n, 50.0),
        "macd": np.full(n, 0.0),
        "macd_signal": np.full(n, 0.0),
        "bb_pct_b": np.full(n, 0.5),
        "trend_score": np.full(n, 0.0),
        "atr_14": np.full(n, 1.0),
    }, index=idx)
    model = _FixedStubModel(action=2)
    sc = compute_scorecard(model=model, test_df=flat_df, train_df=flat_df)
    overall = sc["functional"]["F5_baseline_relative"]["overall"]
    assert math.isfinite(overall)


# ── save_scorecard persistence ─────────────────────────────────────────────────

def test_save_scorecard_writes_valid_json_roundtrip():
    df = _make_regime_df(n=150, seed=12)
    model = _CyclicStubModel()
    sc = compute_scorecard(model=model, test_df=df, train_df=df, instrument="NIFTY", run_id="abc123")

    with tempfile.TemporaryDirectory() as d:
        path = save_scorecard(sc, output_dir=d, instrument="NIFTY", run_id="abc123")
        assert Path(path).exists()
        assert Path(path).parent == Path(d) / "NIFTY"
        loaded = json.loads(Path(path).read_text())
        assert loaded["instrument"] == "NIFTY"
        assert loaded["run_id"] == "abc123"
        assert "functional" in loaded and "technical" in loaded


def test_save_scorecard_nan_becomes_null_in_json():
    """Edge case 3: NaN must never be written into the JSON literally."""
    sc = {
        "instrument": "X", "run_id": "y", "config_source": "default",
        "regime_window": 20, "generated_at": "now",
        "functional": {"F1_sharpe_test": {"value": float("nan"), "healthy": False}},
        "technical": {},
    }
    with tempfile.TemporaryDirectory() as d:
        path = save_scorecard(sc, output_dir=d, instrument="X", run_id="y")
        raw_text = Path(path).read_text()
        assert "NaN" not in raw_text
        loaded = json.loads(raw_text)
        assert loaded["functional"]["F1_sharpe_test"]["value"] is None
