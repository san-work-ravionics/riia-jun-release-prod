"""RITA Core — ASML Investment Environment (Feature 32, Phase 3)

Standalone RL environment for ASML hedge-advisory training and finetuning.
Based on RIIATradingEnvV2 — a SEPARATE, parallel environment to the golden
``RIIATradingEnv`` (``trading_env.py``). Design: ``docs/design-RIIATradingEnvV2-phase3.md``.

Differences from golden (see design doc §3–§5):
  * Action space ``Discrete(4)`` — adds action 3 = "Hedged" (stay invested with
    a protective overlay) on top of the golden {Cash, Half, Full}.
  * Observation +2 features — ``dd_vs_tolerance`` and ``is_hedged`` (10–11 total).
  * Reward shaping — graded, *tolerance-relative* unhedged-drawdown penalty
    (tolerance from Financial Goal ``risk_tolerance``), plus a hedge carry cost.
  * Per-episode tolerance sampling so one policy generalises across low/med/high.

The golden ``train_agent`` / ``run_episode`` hardcode ``RIIATradingEnv`` and the
3-action map, so V2 ships its OWN ``train_agent_v2`` / ``train_best_of_n_v2`` /
``run_episode_v2``. The shared, env-agnostic ``TrainingProgressCallback`` and
``compute_all_metrics`` are imported from the golden module unchanged.

OFFLINE TRAIN + BACKTEST ONLY in Phase 3 — no production model swap.
"""

from __future__ import annotations

import os
from typing import Tuple

import numpy as np
import pandas as pd
import gymnasium as gym
import structlog
from gymnasium import spaces
from stable_baselines3 import DQN
from stable_baselines3.common.monitor import Monitor

from rita.core.performance import compute_all_metrics
from rita.core.trading_env import TrainingProgressCallback  # shared, env-agnostic
from rita.logging_config import log_event

log = structlog.get_logger(__name__)


# ── Reward / hedge hyper-params (calibration defaults — tunable) ───────────────
# Map the Financial Goal categorical risk_tolerance → a max-drawdown threshold.
RISK_TOLERANCE_MDD = {"low": -0.08, "medium": -0.15, "high": -0.25}
_TOLERANCE_LEVELS = ("low", "medium", "high")

LAMBDA_BREACH      = 0.5      # graded penalty coeff for unhedged DD past tolerance
HEDGE_COST_PER_DAY = 0.0002   # amortised protective-put carry while hedged (~5%/yr)
HEDGE_DAILY_FLOOR  = -0.015    # per-day downside truncation when hedged (put payoff approx)

# Action → (allocation, hedged?)
_ACTION_MAP = {0: (0.0, False), 1: (0.5, False), 2: (1.0, False), 3: (1.0, True)}

# Action → (short label, advisory detail) for the execution_analyst recommendation.
_ACTION_LABEL = {
    0: ("move to cash", "de-risk fully — exit the position"),
    1: ("trim to ~50%", "reduce exposure by roughly half"),
    2: ("stay fully invested", "hold exposure — no hedge indicated"),
    3: ("apply a protective hedge", "stay invested but add downside protection"),
}


# ── Gymnasium trading environment V2 ──────────────────────────────────────────

class RIIATradingEnvV2(gym.Env):
    """Custom gymnasium env with a hedge action and tolerance-relative reward.

    Observation (10 or 11 features):
        [daily_return_scaled, rsi_norm, macd_norm, bb_pct_b, trend_score,
         current_allocation, days_remaining_norm, atr_ratio,
         (ema_ratio_norm — if present),
         dd_vs_tolerance, is_hedged]

    Action (Discrete 4):
        0 → Cash   (0%,   unhedged)
        1 → Half   (50%,  unhedged)
        2 → Full   (100%, unhedged)
        3 → Hedged (100% invested + protective overlay)

    Reward:
        portfolio_return (hedge carry/floor already reflected when hedged)
        − LAMBDA_BREACH · max(0, |drawdown| − |mdd_tolerance|)  when UNHEDGED
    """

    metadata = {"render_modes": []}

    def __init__(self, df: pd.DataFrame, episode_length: int = 252,
                 fixed_tolerance: str | None = None):
        super().__init__()

        self._base_cols = [
            "daily_return", "rsi_14", "macd", "macd_signal",
            "bb_pct_b", "trend_score", "Close", "atr_14",
        ]
        has_ema_ratio = "ema_ratio" in df.columns and not df["ema_ratio"].isna().all()
        self._use_ema_ratio = has_ema_ratio
        # golden 8 (or 9 w/ ema) + dd_vs_tolerance + is_hedged
        self._n_features = (9 if has_ema_ratio else 8) + 2

        required_cols = self._base_cols + (["ema_ratio"] if has_ema_ratio else [])
        self.df = df.dropna(subset=required_cols).copy()
        self.episode_length = min(episode_length, len(self.df) - 1)

        # fixed_tolerance pins the risk level (used for deterministic eval);
        # None → sampled per episode in reset() so the policy generalises.
        self._fixed_tolerance = fixed_tolerance

        self.observation_space = spaces.Box(
            low=-3.0, high=3.0, shape=(self._n_features,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(4)

        self._reset_state()

    def _reset_state(self) -> None:
        self._step_idx = 0
        self._start_idx = 0
        self._portfolio_value = 1.0
        self._peak_value = 1.0
        self._current_allocation = 0.0
        self._is_hedged = 0.0
        self._mdd_tolerance = RISK_TOLERANCE_MDD["medium"]
        self._portfolio_history: list[float] = []

    def _current_drawdown(self) -> float:
        return (self._portfolio_value - self._peak_value) / self._peak_value

    def _get_obs(self) -> np.ndarray:
        row = self.df.iloc[self._start_idx + self._step_idx]
        obs_list = [
            float(np.clip(row["daily_return"] * 10, -3, 3)),
            float(np.clip(row["rsi_14"] / 100.0, 0, 1)),
            float(np.clip((row["macd"] / row["Close"]) * 1000, -3, 3)),
            float(np.clip(row["bb_pct_b"], -0.5, 1.5)),
            float(np.clip(row["trend_score"], -1, 1)),
            float(self._current_allocation),
            float(1.0 - self._step_idx / self.episode_length),
            float(np.clip(row["atr_14"] / row["Close"] * 100, 0, 3)),
        ]
        if self._use_ema_ratio:
            obs_list.append(float(np.clip((row["ema_ratio"] - 1.0) * 20, -3, 3)))
        # V2 features: how deep the drawdown is relative to THIS user's tolerance,
        # and whether a hedge is currently active.
        dd_vs_tol = self._current_drawdown() / self._mdd_tolerance  # both negative → positive ratio
        obs_list.append(float(np.clip(dd_vs_tol, 0, 3)))
        obs_list.append(float(self._is_hedged))
        return np.array(obs_list, dtype=np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        max_start = max(0, len(self.df) - self.episode_length - 1)
        self._start_idx = int(self.np_random.integers(0, max_start + 1))
        self._step_idx = 0
        self._portfolio_value = 1.0
        self._peak_value = 1.0
        self._current_allocation = 0.0
        self._is_hedged = 0.0
        # Sample tolerance per episode (unless pinned) so one policy serves all
        # risk levels and dd_vs_tolerance carries real signal.
        level = self._fixed_tolerance or _TOLERANCE_LEVELS[int(self.np_random.integers(0, 3))]
        self._mdd_tolerance = RISK_TOLERANCE_MDD[level]
        self._portfolio_history = [1.0]
        return self._get_obs(), {}

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, dict]:
        allocation, hedged = _ACTION_MAP[int(action)]
        self._current_allocation = allocation
        self._is_hedged = 1.0 if hedged else 0.0

        row = self.df.iloc[self._start_idx + self._step_idx]
        daily_ret = float(row["daily_return"])

        # Hedged: truncate per-day downside (protective-put payoff approx) and pay
        # the amortised carry. Unhedged: raw exposure.
        if hedged:
            effective_ret = max(daily_ret, HEDGE_DAILY_FLOOR)
            portfolio_ret = allocation * effective_ret - HEDGE_COST_PER_DAY
        else:
            portfolio_ret = allocation * daily_ret

        self._portfolio_value *= (1 + portfolio_ret)
        self._portfolio_history.append(self._portfolio_value)

        self._peak_value = max(self._peak_value, self._portfolio_value)
        current_dd = self._current_drawdown()

        reward = portfolio_ret
        if not hedged:
            breach = abs(current_dd) - abs(self._mdd_tolerance)
            if breach > 0:
                reward -= LAMBDA_BREACH * breach

        self._step_idx += 1
        terminated = self._step_idx >= self.episode_length
        truncated = False

        obs = self._get_obs() if not terminated else np.zeros(self._n_features, dtype=np.float32)
        price = float(row["Close"]) if "Close" in row.index else None
        info = {
            "portfolio_value": self._portfolio_value,
            "allocation":      self._current_allocation,
            "is_hedged":       self._is_hedged,
            "drawdown":        current_dd,
            "mdd_tolerance":   self._mdd_tolerance,
        }
        log_event(
            log, "info", "trade.executed",
            symbol="NIFTY", action=int(action), qty=self._current_allocation,
            hedged=bool(hedged), price=price,
            portfolio_value=round(self._portfolio_value, 6),
        )
        return obs, reward, terminated, truncated, info


# ── Training (V2-owned — golden trainers hardcode RIIATradingEnv) ──────────────

def train_agent_v2(
    train_df: pd.DataFrame,
    output_dir: str,
    timesteps: int,
    learning_rate: float = 1e-4,
    buffer_size: int = 100_000,
    exploration_fraction: float = 0.5,
    seed: int = 42,
    model_name: str = "rita_ddqn_v2_model",
    progress_fn=None,
) -> Tuple[DQN, TrainingProgressCallback]:
    """Train a Double-DQN agent on RIIATradingEnvV2 and save the model.

    Mirrors golden ``train_agent`` but binds ``RIIATradingEnvV2`` (4 actions).
    """
    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(output_dir, model_name)

    env = Monitor(RIIATradingEnvV2(train_df))

    model = DQN(
        policy="MlpPolicy",
        env=env,
        learning_rate=learning_rate,
        buffer_size=buffer_size,
        learning_starts=2_000,
        batch_size=64,
        tau=0.005,
        gamma=0.99,
        train_freq=4,
        gradient_steps=1,
        target_update_interval=1,
        exploration_fraction=exploration_fraction,
        exploration_final_eps=0.05,
        policy_kwargs={"net_arch": [256, 256]},
        seed=seed,
        verbose=0,
    )

    progress_cb = TrainingProgressCallback(log_interval=1_000, progress_fn=progress_fn)
    model.learn(total_timesteps=timesteps, callback=progress_cb)
    model.save(model_path)

    return model, progress_cb


# ── Inference / backtest (V2-owned — handles the 4-action map) ─────────────────

def load_agent_v2(model_path: str) -> DQN:
    """Load a saved V2 DDQN model from disk (advisory use only in Phase 3)."""
    return DQN.load(model_path)


def run_episode_v2(model: DQN, df: pd.DataFrame, risk_tolerance: str = "medium") -> dict:
    """Run the V2 model deterministically through the full DataFrame.

    ``risk_tolerance`` pins the tolerance for evaluation (one of low/medium/high)
    so dd_vs_tolerance is computed consistently. Returns the same shape as golden
    ``run_episode`` plus ``hedged_steps`` / ``hedge_usage_pct``.
    """
    n_obs = model.observation_space.shape[0]
    mdd_tol = RISK_TOLERANCE_MDD.get(risk_tolerance, RISK_TOLERANCE_MDD["medium"])

    required = [
        "daily_return", "rsi_14", "macd", "macd_signal",
        "bb_pct_b", "trend_score", "Close", "atr_14",
    ]
    has_ema = "ema_ratio" in df.columns and not df["ema_ratio"].isna().all()
    if n_obs >= 11 and has_ema:
        required.append("ema_ratio")

    data = df.dropna(subset=required).copy()
    if len(data) == 0:
        raise ValueError("DataFrame has no valid rows after dropping NaN indicators.")

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
        if n_obs >= 11 and has_ema:
            obs_list.append(float(np.clip((row["ema_ratio"] - 1.0) * 20, -3, 3)))
        obs_list.append(float(np.clip(current_dd / mdd_tol, 0, 3)))
        obs_list.append(float(prev_hedged))

        obs = np.array(obs_list, dtype=np.float32)
        action, _ = model.predict(obs, deterministic=True)
        allocation, hedged = _ACTION_MAP[int(action)]

        next_row = data.iloc[i + 1]
        daily_ret = float(next_row["daily_return"])
        if hedged:
            effective_ret = max(daily_ret, HEDGE_DAILY_FLOOR)
            portfolio_ret = allocation * effective_ret - HEDGE_COST_PER_DAY
        else:
            portfolio_ret = allocation * daily_ret
        portfolio_value *= (1 + portfolio_ret)
        peak_value = max(peak_value, portfolio_value)

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


# ── Recommendation-only advisory (Execution Analyst intent) ───────────────────

def recommend_hedge(
    df: pd.DataFrame,
    model: DQN,
    risk_tolerance: str = "medium",
    lookback: int = 60,
) -> dict:
    """Single-shot hedge recommendation from a trained V2 policy.

    ADVISORY ONLY — builds the current observation, asks the policy, and returns
    a labelled recommendation. It NEVER places, routes, or simulates an order.

    Drawdown is proxied from the instrument's own recent ``lookback`` closes
    (peak-to-current) since live portfolio state isn't available in the chat
    path. Returns: action, label, detail, drawdown_pct, mdd_tolerance_pct, breach.
    """
    n_obs = model.observation_space.shape[0]
    mdd_tol = RISK_TOLERANCE_MDD.get(risk_tolerance, RISK_TOLERANCE_MDD["medium"])

    required = [
        "daily_return", "rsi_14", "macd", "macd_signal",
        "bb_pct_b", "trend_score", "Close", "atr_14",
    ]
    has_ema = "ema_ratio" in df.columns and not df["ema_ratio"].isna().all()
    if n_obs >= 11 and has_ema:
        required.append("ema_ratio")

    data = df.dropna(subset=required).copy()
    if len(data) == 0:
        raise ValueError("DataFrame has no valid rows after dropping NaN indicators.")

    recent = data["Close"].tail(lookback).to_numpy()
    peak = float(np.max(recent))
    cur = float(recent[-1])
    current_dd = (cur - peak) / peak if peak > 0 else 0.0

    row = data.iloc[-1]
    # Assume the user is fully invested and unhedged when asking whether to hedge.
    obs_list = [
        float(np.clip(row["daily_return"] * 10, -3, 3)),
        float(np.clip(row["rsi_14"] / 100.0, 0, 1)),
        float(np.clip((row["macd"] / row["Close"]) * 1000, -3, 3)),
        float(np.clip(row["bb_pct_b"], -0.5, 1.5)),
        float(np.clip(row["trend_score"], -1, 1)),
        1.0,                                   # current_allocation
        0.0,                                   # days_remaining_norm (point-in-time)
        float(np.clip(row["atr_14"] / row["Close"] * 100, 0, 3)),
    ]
    if n_obs >= 11 and has_ema:
        obs_list.append(float(np.clip((row["ema_ratio"] - 1.0) * 20, -3, 3)))
    obs_list.append(float(np.clip(current_dd / mdd_tol, 0, 3)))
    obs_list.append(0.0)                       # is_hedged

    obs = np.array(obs_list, dtype=np.float32)
    action = int(model.predict(obs, deterministic=True)[0])
    label, detail = _ACTION_LABEL[action]

    return {
        "action":             action,
        "label":              label,
        "detail":             detail,
        "drawdown_pct":       round(current_dd * 100, 2),
        "mdd_tolerance_pct":  round(mdd_tol * 100, 2),
        "breach":             abs(current_dd) > abs(mdd_tol),
    }
