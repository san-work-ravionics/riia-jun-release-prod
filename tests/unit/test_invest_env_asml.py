"""Unit tests for ASML Investment Environment (Feature 32, Phase 3).

Covers env mechanics only — action/obs shapes, the hedge action's payoff
truncation + carry, the tolerance-relative breach penalty, per-episode tolerance
sampling, run_episode_v2 with a stub policy, and a guard that the golden
RIIATradingEnv stays frozen at Discrete(3). No SB3 training (too slow for a unit).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rita.core.invest_env_asml import (
    RIIATradingEnvV2,
    RISK_TOLERANCE_MDD,
    HEDGE_DAILY_FLOOR,
    HEDGE_COST_PER_DAY,
    run_episode_v2,
    _ACTION_MAP,
)


def _make_df(daily_return: float = 0.001, n: int = 300, with_ema: bool = False) -> pd.DataFrame:
    """Synthetic OHLCV+indicators frame with all required columns non-NaN."""
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    data = {
        "daily_return": np.full(n, daily_return, dtype=float),
        "rsi_14":       np.full(n, 55.0),
        "macd":         np.full(n, 1.5),
        "macd_signal":  np.full(n, 1.0),
        "bb_pct_b":     np.full(n, 0.5),
        "trend_score":  np.full(n, 0.2),
        "Close":        np.full(n, 100.0),
        "atr_14":       np.full(n, 2.0),
    }
    if with_ema:
        data["ema_ratio"] = np.full(n, 1.01)
    return pd.DataFrame(data, index=idx)


class _StubModel:
    """Minimal stand-in for a trained DQN — always returns `action`."""

    def __init__(self, action: int, n_obs: int = 10):
        self.observation_space = type("S", (), {"shape": (n_obs,)})()
        self._action = action

    def predict(self, obs, deterministic=True):
        return np.array(self._action), None


def test_action_space_is_discrete_4():
    env = RIIATradingEnvV2(_make_df())
    assert env.action_space.n == 4


def test_obs_shape_10_without_ema_11_with_ema():
    assert RIIATradingEnvV2(_make_df(with_ema=False)).observation_space.shape == (10,)
    assert RIIATradingEnvV2(_make_df(with_ema=True)).observation_space.shape == (11,)


def test_reset_returns_obs_of_declared_shape():
    env = RIIATradingEnvV2(_make_df())
    obs, info = env.reset(seed=0)
    assert obs.shape == (10,)
    assert info == {}


def test_fixed_tolerance_pins_level_else_sampled_from_valid_set():
    env = RIIATradingEnvV2(_make_df(), fixed_tolerance="low")
    env.reset(seed=1)
    assert env._mdd_tolerance == RISK_TOLERANCE_MDD["low"]

    sampled = set()
    env2 = RIIATradingEnvV2(_make_df())
    for s in range(20):
        env2.reset(seed=s)
        sampled.add(env2._mdd_tolerance)
    assert sampled.issubset(set(RISK_TOLERANCE_MDD.values()))


def test_hedge_action_truncates_downside_and_pays_carry():
    # Big daily loss: hedged (action 3) should floor the per-day loss and pay carry,
    # NOT take the raw -5%.
    env = RIIATradingEnvV2(_make_df(daily_return=-0.05), fixed_tolerance="medium")
    env.reset(seed=2)
    _, reward, _, _, info = env.step(3)
    expected_ret = max(-0.05, HEDGE_DAILY_FLOOR) - HEDGE_COST_PER_DAY
    assert info["is_hedged"] == 1.0
    assert env._portfolio_value == pytest.approx(1 + expected_ret, abs=1e-9)
    # hedged steps get no breach penalty → reward == portfolio_ret
    assert reward == pytest.approx(expected_ret, abs=1e-9)


def test_full_unhedged_takes_raw_return():
    env = RIIATradingEnvV2(_make_df(daily_return=-0.05), fixed_tolerance="medium")
    env.reset(seed=3)
    _, _, _, _, info = env.step(2)  # Full, unhedged
    assert info["is_hedged"] == 0.0
    assert env._portfolio_value == pytest.approx(0.95, abs=1e-9)


def test_unhedged_breach_incurs_graded_penalty():
    # Drive the portfolio past the low tolerance (-8%) unhedged; once breached,
    # reward must be strictly below the raw portfolio return.
    env = RIIATradingEnvV2(_make_df(daily_return=-0.05), fixed_tolerance="low")
    env.reset(seed=4)
    breached = False
    for _ in range(5):
        _, reward, term, _, info = env.step(2)  # Full, unhedged
        if abs(info["drawdown"]) > abs(RISK_TOLERANCE_MDD["low"]):
            # portfolio_ret for a full unhedged step is -0.05; penalty makes reward < that
            assert reward < -0.05 + 1e-9
            breached = True
            break
        if term:
            break
    assert breached, "drawdown never exceeded tolerance — test setup wrong"


def test_run_episode_v2_with_stub_model_reports_hedge_usage():
    df = _make_df(daily_return=0.001)
    model = _StubModel(action=3, n_obs=10)  # always hedge
    result = run_episode_v2(model, df, risk_tolerance="medium")
    assert result["hedge_usage_pct"] == pytest.approx(100.0)
    for k in ("portfolio_values", "benchmark_values", "allocations",
              "hedge_flags", "performance", "dates"):
        assert k in result


def test_run_episode_v2_cash_action_keeps_capital_flat():
    df = _make_df(daily_return=0.02)  # market rises, but agent stays in cash
    model = _StubModel(action=0, n_obs=10)
    result = run_episode_v2(model, df, risk_tolerance="high")
    assert result["portfolio_values"][-1] == pytest.approx(1.0, abs=1e-9)
    assert result["hedge_usage_pct"] == pytest.approx(0.0)


def test_action_map_shapes():
    assert _ACTION_MAP == {0: (0.0, False), 1: (0.5, False), 2: (1.0, False), 3: (1.0, True)}


def test_golden_env_is_frozen_discrete_3():
    """Regression guard: V2 must not have altered the golden env's action space."""
    from rita.core.trading_env import RIIATradingEnv
    env = RIIATradingEnv(_make_df())
    assert env.action_space.n == 3, "golden RIIATradingEnv must stay Discrete(3)"


# ── Standalone module tests ──────────────────────────────────────────────────

def test_recommend_hedge_returns_labelled_recommendation():
    from rita.core.invest_env_asml import recommend_hedge, _ACTION_LABEL
    df = _make_df(daily_return=-0.01)
    model = _StubModel(action=3, n_obs=10)
    rec = recommend_hedge(df, model, risk_tolerance="medium")
    assert rec["action"] == 3
    assert rec["label"] == _ACTION_LABEL[3][0]
    for k in ("drawdown_pct", "mdd_tolerance_pct", "breach"):
        assert k in rec


def test_invest_env_asml_has_no_order_execution_paths():
    """Load-bearing: the module is advisory only — no order/trade routing."""
    import rita.core.invest_env_asml as mod
    src = open(mod.__file__, encoding="utf-8").read().lower()
    for forbidden in ("place_order", "submit_order", "execute_trade",
                      "create_order", "broker.", "send_order"):
        assert forbidden not in src, f"advisory module must not reference {forbidden}"
