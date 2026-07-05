"""Unit tests for RIIATradingEnvV2 (Feature 32, Phase 3 + 3.5).

Covers env mechanics only — action/obs shapes, the hedge action's payoff
truncation + carry, DSR reward, hard MDD termination at -10%, causal alignment
(next-bar return), per-episode tolerance sampling, run_episode_v2 with a stub
policy, and a guard that the golden RIIATradingEnv stays frozen at Discrete(3).
No SB3 training (too slow for a unit).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rita.core.trading_env_v2 import (
    RIIATradingEnvV2,
    RISK_TOLERANCE_MDD,
    HEDGE_DAILY_FLOOR,
    HEDGE_COST_PER_DAY,
    HARD_MDD_LIMIT,
    MDD_TERMINAL_PENALTY,
    RF_DAILY,
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


def _make_varying_df(daily_returns: list[float], with_ema: bool = False) -> pd.DataFrame:
    """Synthetic frame where daily_return varies per row."""
    n = len(daily_returns)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    data = {
        "daily_return": np.array(daily_returns, dtype=float),
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

    def __init__(self, action: int, n_obs: int = 13):
        self.observation_space = type("S", (), {"shape": (n_obs,)})()
        self._action = action

    def predict(self, obs, deterministic=True):
        return np.array(self._action), None


def test_action_space_is_discrete_4():
    env = RIIATradingEnvV2(_make_df())
    assert env.action_space.n == 4


def test_obs_shape_13_without_ema_14_with_ema():
    # golden 8 (+ema) + A + B + dd_vs_hard_limit + is_hedged + tolerance_norm
    assert RIIATradingEnvV2(_make_df(with_ema=False)).observation_space.shape == (13,)
    assert RIIATradingEnvV2(_make_df(with_ema=True)).observation_space.shape == (14,)


def test_tolerance_norm_is_last_obs_feature():
    from rita.core.trading_env_v2 import _tol_norm, RISK_TOLERANCE_MDD
    for level in ("low", "medium", "high"):
        env = RIIATradingEnvV2(_make_df(), fixed_tolerance=level)
        obs, _ = env.reset(seed=1)
        assert obs[-1] == pytest.approx(_tol_norm(RISK_TOLERANCE_MDD[level]), abs=1e-6)
    # conservative < aggressive on the tolerance feature
    assert _tol_norm(RISK_TOLERANCE_MDD["low"]) < _tol_norm(RISK_TOLERANCE_MDD["high"])


def test_reset_returns_obs_of_declared_shape():
    env = RIIATradingEnvV2(_make_df())
    obs, info = env.reset(seed=0)
    assert obs.shape == (13,)
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
    # NOT take the raw -5%. With causal alignment, step reads NEXT bar's return.
    # Since _make_df creates constant daily_return=-0.05, the next bar also has -0.05.
    env = RIIATradingEnvV2(_make_df(daily_return=-0.05), fixed_tolerance="medium")
    env.reset(seed=2)
    _, reward, _, _, info = env.step(3)
    expected_ret = max(-0.05, HEDGE_DAILY_FLOOR) - HEDGE_COST_PER_DAY
    assert info["is_hedged"] == 1.0
    assert env._portfolio_value == pytest.approx(1 + expected_ret, abs=1e-9)


def test_full_unhedged_takes_raw_return():
    # With causal alignment, step reads NEXT bar's return.
    # Constant daily_return=-0.05: next bar is also -0.05.
    env = RIIATradingEnvV2(_make_df(daily_return=-0.05), fixed_tolerance="medium")
    env.reset(seed=3)
    _, _, _, _, info = env.step(2)  # Full, unhedged
    assert info["is_hedged"] == 0.0
    assert env._portfolio_value == pytest.approx(0.95, abs=1e-9)


def test_hard_mdd_terminates_episode():
    # Drive the portfolio past the hard MDD limit (-10%) unhedged.
    # With daily_return=-0.05 (constant), after 2 full unhedged steps the
    # portfolio is ~0.9025 → drawdown ~-9.75%. After step 3: ~0.8574 → ~-14.26%.
    # Termination should happen at step 3 (when dd exceeds -10%).
    for tol in ("low", "medium", "high"):
        env = RIIATradingEnvV2(_make_df(daily_return=-0.05), fixed_tolerance=tol)
        env.reset(seed=4)
        terminated = False
        terminal_reward = None
        for step_num in range(10):
            _, reward, term, _, info = env.step(2)  # Full, unhedged
            if term:
                terminated = True
                terminal_reward = reward
                break
        assert terminated, f"episode never terminated for tolerance={tol}"
        assert terminal_reward == MDD_TERMINAL_PENALTY


def test_run_episode_v2_with_stub_model_reports_hedge_usage():
    df = _make_df(daily_return=0.001)
    model = _StubModel(action=3, n_obs=13)  # always hedge
    result = run_episode_v2(model, df, risk_tolerance="medium")
    assert result["hedge_usage_pct"] == pytest.approx(100.0)
    for k in ("portfolio_values", "benchmark_values", "allocations",
              "hedge_flags", "performance", "dates"):
        assert k in result


def test_run_episode_v2_cash_action_keeps_capital_flat():
    df = _make_df(daily_return=0.02)  # market rises, but agent stays in cash
    model = _StubModel(action=0, n_obs=13)
    result = run_episode_v2(model, df, risk_tolerance="high")
    assert result["portfolio_values"][-1] == pytest.approx(1.0, abs=1e-9)
    assert result["hedge_usage_pct"] == pytest.approx(0.0)


def test_action_map_shapes():
    assert _ACTION_MAP == {0: (0.0, False), 1: (0.5, False), 2: (1.0, False), 3: (1.0, True)}


def test_temporal_split_is_chronological_and_non_overlapping():
    from rita.core.trading_env_v2 import temporal_split
    df = _make_df(n=1000)
    tr, va, te = temporal_split(df, train_frac=0.70, val_frac=0.15)
    # sizes ~ 70/15/15, cover the whole frame with no gaps or overlap
    assert len(tr) + len(va) + len(te) == len(df)
    assert (len(tr), len(va), len(te)) == (700, 150, 150)
    # strictly increasing in time: train precedes val precedes test
    assert tr.index.max() < va.index.min() < va.index.max() < te.index.min()


def test_static_baseline_matches_run_episode_result_shape():
    from rita.core.trading_env_v2 import run_static_baseline_v2
    df = _make_df(daily_return=0.001)
    result = run_static_baseline_v2(df, risk_tolerance="medium")
    for k in ("portfolio_values", "benchmark_values", "allocations",
              "hedge_flags", "hedged_steps", "hedge_usage_pct",
              "daily_returns", "dates", "performance"):
        assert k in result
    # Rising market never breaches tolerance → static rule never hedges.
    assert result["hedge_usage_pct"] == pytest.approx(0.0)
    assert all(a == 1.0 for a in result["allocations"])  # always fully invested


def test_static_baseline_hedges_after_drawdown_breach():
    from rita.core.trading_env_v2 import run_static_baseline_v2
    df = _make_df(daily_return=-0.05)  # steep, sustained drawdown
    result = run_static_baseline_v2(df, risk_tolerance="low")
    # A deep persistent drawdown must trip the threshold rule into hedging.
    assert result["hedged_steps"] > 0


def test_golden_env_is_frozen_discrete_3():
    """Regression guard: V2 must not have altered the golden env's action space."""
    from rita.core.trading_env import RIIATradingEnv
    env = RIIATradingEnv(_make_df())
    assert env.action_space.n == 3, "golden RIIATradingEnv must stay Discrete(3)"


# ── Execution Analyst intent (recommendation-only) ────────────────────────────

def test_recommend_hedge_returns_labelled_recommendation():
    from rita.core.trading_env_v2 import recommend_hedge, _ACTION_LABEL
    df = _make_df(daily_return=-0.01)
    model = _StubModel(action=3, n_obs=13)
    rec = recommend_hedge(df, model, risk_tolerance="medium")
    assert rec["action"] == 3
    assert rec["label"] == _ACTION_LABEL[3][0]
    for k in ("drawdown_pct", "mdd_tolerance_pct", "breach"):
        assert k in rec


def test_hedge_advice_intent_registered_and_mapped():
    from rita.core.classifier import INTENTS, INTENT_TO_AGENT
    intent = next((i for i in INTENTS if i.name == "hedge_advice"), None)
    assert intent is not None, "hedge_advice intent must be registered"
    assert intent.handler == "execution_hedge"
    assert INTENT_TO_AGENT["hedge_advice"] == "Execution Analyst"


def test_execution_hedge_dispatch_graceful_when_untrained(tmp_path):
    """No V2 model artifact → advisory message, never an error, never an order."""
    from rita.core.classifier import INTENTS, IntentResult, dispatch
    intent = next(i for i in INTENTS if i.name == "hedge_advice")
    result = IntentResult(intent=intent, confidence=0.9, low_confidence=False)
    out = dispatch(result, _make_df(), output_dir=str(tmp_path))  # empty dir
    assert "not yet trained" in out.lower()
    assert "advisory" in out.lower()


def test_train_best_of_n_v2_selects_and_returns_structure():
    """Tiny best-of-2 smoke — verifies seed loop + winner selection structure."""
    import tempfile
    from rita.core.trading_env_v2 import train_best_of_n_v2
    df = _make_df(daily_return=0.001, n=320)
    with tempfile.TemporaryDirectory() as d:
        _model, _cb, info = train_best_of_n_v2(
            train_df=df, val_df=df, output_dir=d,
            timesteps=400, n_seeds=2, model_name="rita_ddqn_v2_test",
        )
    assert info["n_seeds_tried"] == 2
    assert len(info["seed_results"]) == 2
    assert info["best_seed"] in (0, 1)
    assert all("val_sharpe" in r and "hedge_usage_pct" in r for r in info["seed_results"])


def test_trading_env_v2_has_no_order_execution_paths():
    """Load-bearing: the V2 module is advisory only — no order/trade routing."""
    import rita.core.trading_env_v2 as mod
    src = open(mod.__file__, encoding="utf-8").read().lower()
    for forbidden in ("place_order", "submit_order", "execute_trade",
                      "create_order", "broker.", "send_order"):
        assert forbidden not in src, f"advisory module must not reference {forbidden}"


# ── Phase 3.5 new tests ─────────────────────────────────────────────────────

def test_causal_alignment_step_earns_next_bar_return():
    """Action at bar t should earn bar t+1's return, not bar t's."""
    daily_returns = [0.0, 0.02, 0.03, 0.04, 0.05]
    df = _make_varying_df(daily_returns)
    env = RIIATradingEnvV2(df, fixed_tolerance="medium")
    env.reset(seed=0)
    env._start_idx = 0
    # _start_idx pinned to 0, _step_idx is 0.
    # step() reads next_row = df.iloc[0 + 0 + 1] = row 1, daily_ret = 0.02
    # Full unhedged (action 2): portfolio_ret = 1.0 * 0.02 = 0.02
    _, _, _, _, info = env.step(2)
    assert env._portfolio_value == pytest.approx(1.02, abs=1e-9)


def test_dsr_reward_positive_after_warmup():
    """Under constant positive returns well above RF, DSR reward should turn positive."""
    df = _make_df(daily_return=0.005, n=300)
    env = RIIATradingEnvV2(df, fixed_tolerance="medium")
    env.reset(seed=0)
    positive_rewards = 0
    for step_num in range(50):
        _, reward, term, _, _ = env.step(2)  # Full unhedged
        if term:
            break
        if step_num >= 10 and reward > 0:
            positive_rewards += 1
    # After warmup, we should see positive DSR rewards for positive excess returns.
    assert positive_rewards > 0, "DSR reward never turned positive under consistent gains"


def test_hard_mdd_terminates_for_all_tolerances():
    """The -10% hard MDD limit must engage for ALL tolerance levels."""
    for tol in ("low", "medium", "high"):
        env = RIIATradingEnvV2(_make_df(daily_return=-0.06, n=300), fixed_tolerance=tol)
        env.reset(seed=0)
        terminated = False
        terminal_reward = None
        for _ in range(20):
            _, reward, term, _, _ = env.step(2)  # Full unhedged
            if term:
                terminated = True
                terminal_reward = reward
                break
        assert terminated, f"episode never terminated for tolerance={tol}"
        assert terminal_reward == MDD_TERMINAL_PENALTY, (
            f"terminal reward was {terminal_reward}, expected {MDD_TERMINAL_PENALTY} for tol={tol}"
        )


# ── QA Agent: Additional Phase 3.5 coverage tests ─────────────────────────────


def test_dsr_reward_is_zero_at_cold_start():
    """Edge case 1: At episode start A=B=0, var=0, DSR reward must be 0.0."""
    df = _make_df(daily_return=0.01, n=300)
    env = RIIATradingEnvV2(df, fixed_tolerance="medium")
    env.reset(seed=0)
    _, reward, _, _, _ = env.step(2)  # Full unhedged, first step
    assert reward == 0.0, f"DSR reward at cold start should be 0.0, got {reward}"


def test_reset_zeros_running_moments():
    """reset() must zero _A and _B — fresh DSR baseline each episode."""
    df = _make_df(daily_return=0.01, n=300)
    env = RIIATradingEnvV2(df, fixed_tolerance="medium")
    env.reset(seed=0)
    # Take several steps to accumulate non-zero A and B
    for _ in range(10):
        _, _, term, _, _ = env.step(2)
        if term:
            break
    assert env._A != 0.0 or env._B != 0.0, "A/B should be non-zero after steps"
    # Reset must zero them for the next episode
    env.reset(seed=1)
    assert env._A == 0.0
    assert env._B == 0.0


def test_portfolio_ret_clipped_to_safe_range():
    """Edge case 3: Extreme daily returns are clipped so portfolio value cannot go negative."""
    # daily_return = -2.0 everywhere: unhedged portfolio_ret = 1.0 * (-2.0) = -2.0
    # Clip to -1.0 → portfolio_value = 1 * (1 + (-1)) = 0.0 (not -1.0)
    df = _make_df(daily_return=-2.0, n=300)
    env = RIIATradingEnvV2(df, fixed_tolerance="medium")
    env.reset(seed=0)
    env.step(2)  # Full unhedged
    assert env._portfolio_value == pytest.approx(0.0, abs=1e-9), (
        "Portfolio value should be 0.0 after clip, not negative"
    )


def test_half_position_earns_half_return():
    """Action 1 (half position) should earn exactly 50% of the next bar's return."""
    daily_returns = [0.0, 0.04, 0.04, 0.04, 0.04]
    df = _make_varying_df(daily_returns)
    env = RIIATradingEnvV2(df, fixed_tolerance="medium")
    env.reset(seed=0)
    env._start_idx = 0
    # step reads next bar (index 1) with daily_return = 0.04
    # Half unhedged: portfolio_ret = 0.5 * 0.04 = 0.02
    _, _, _, _, info = env.step(1)
    assert env._portfolio_value == pytest.approx(1.02, abs=1e-9)
    assert info["allocation"] == 0.5
    assert info["is_hedged"] == 0.0


def test_patch_stack_constants_removed():
    """Phase 3.5 removed LAMBDA_BREACH/CASH_BY_TOL/OUTCOME/DOWNSIDE from module."""
    import rita.core.trading_env_v2 as mod
    for removed in ("LAMBDA_BREACH", "LAMBDA_CASH_BY_TOL", "LAMBDA_OUTCOME",
                     "LAMBDA_DOWNSIDE", "OUTCOME_HORIZON_DAYS"):
        assert not hasattr(mod, removed), f"{removed} should have been removed in Phase 3.5"


def test_episode_length_guard_prevents_out_of_bounds():
    """Edge case: small DF must not cause IndexError; episode_length capped at len(df)-2."""
    df = _make_df(daily_return=0.001, n=10)
    env = RIIATradingEnvV2(df, episode_length=252)
    # episode_length should be min(252, 10-2) = 8
    assert env.episode_length == 8
    obs, _ = env.reset(seed=0)
    # Run through all steps without IndexError
    for _ in range(env.episode_length):
        obs, _, term, _, _ = env.step(2)
        if term:
            break


def test_dsr_constants_match_design():
    """DSR hyper-params must match the Architect design specification exactly."""
    from rita.core.trading_env_v2 import ETA, DSR_EPS, RF_DAILY
    assert ETA == pytest.approx(0.004)
    assert DSR_EPS == pytest.approx(1e-12)
    assert RF_DAILY == pytest.approx(0.07 / 252, rel=1e-6)
    assert HARD_MDD_LIMIT == pytest.approx(-0.10)
    assert MDD_TERMINAL_PENALTY == pytest.approx(-5.0)


def test_obs_running_moments_update_across_steps():
    """Running A and B must change after steps — policy perceives Sharpe state (F5)."""
    df = _make_df(daily_return=0.01, n=300)
    env = RIIATradingEnvV2(df, fixed_tolerance="medium")
    env.reset(seed=0)
    # First step: A and B start at 0, should update
    env.step(2)
    a1, b1 = env._A, env._B
    assert a1 != 0.0 or b1 != 0.0, "A/B should be non-zero after first step"
    # Second step: A and B should change again
    env.step(2)
    assert (env._A, env._B) != (a1, b1), "A/B should update on each step"


def test_recommend_hedge_obs_matches_env_dimension():
    """recommend_hedge must build obs matching the env obs dimension (13 or 14)."""
    from rita.core.trading_env_v2 import recommend_hedge
    for with_ema in (False, True):
        df = _make_df(daily_return=-0.01, n=100, with_ema=with_ema)
        expected_dim = 14 if with_ema else 13
        model = _StubModel(action=2, n_obs=expected_dim)
        rec = recommend_hedge(df, model, risk_tolerance="medium")
        assert "action" in rec
        assert "label" in rec
        assert "breach" in rec


def test_train_best_of_n_v2_with_test_df_returns_test_metrics():
    """When test_df is provided, result dict must include test_sharpe/mdd/return."""
    import tempfile
    from rita.core.trading_env_v2 import train_best_of_n_v2
    df = _make_df(daily_return=0.001, n=320)
    with tempfile.TemporaryDirectory() as d:
        _model, _cb, info = train_best_of_n_v2(
            train_df=df, val_df=df, output_dir=d,
            timesteps=400, n_seeds=2, model_name="v2_test_df_test",
            test_df=df,
        )
    assert "test_sharpe" in info, "test_sharpe missing when test_df provided"
    assert "test_mdd" in info, "test_mdd missing when test_df provided"
    assert "test_return" in info, "test_return missing when test_df provided"
    assert "test_hedge_usage_pct" in info, "test_hedge_usage_pct missing when test_df provided"
