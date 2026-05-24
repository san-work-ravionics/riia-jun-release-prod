"""RITA Core — Trading Environment & Agent Utilities

RIIATradingEnv: gymnasium environment for Nifty 50 / any OHLCV instrument.
TrainingProgressCallback: SB3 callback that records training metrics.
train_agent: create, train and save a Double-DQN model.
train_best_of_n: train N seeds, return the winner by validation Sharpe.
run_episode: deterministic episode for validation / backtest.
validate_agent: run_episode + constraint check.
load_agent: load a saved model from disk.

Ported from: poc/rita-cowork-demo/src/rita/core/rl_agent.py
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
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.monitor import Monitor

from rita.core.performance import compute_all_metrics
from rita.logging_config import log_event

log = structlog.get_logger(__name__)


# ── Reward hyper-params ───────────────────────────────────────────────────────
DRAWDOWN_THRESHOLD = -0.10   # -10% cumulative drawdown penalty trigger


# ── Training progress callback ────────────────────────────────────────────────

class TrainingProgressCallback(BaseCallback):
    """Records TD loss and mean episode reward at regular intervals.

    Attributes:
        records: list of dicts with keys: timestep, loss, ep_rew_mean
        progress_fn: optional callable(record) called on every append — use to
                     push live progress to an in-memory store for polling.
    """

    def __init__(self, log_interval: int = 1_000, progress_fn=None):
        super().__init__(verbose=0)
        self.log_interval = log_interval
        self.records: list[dict] = []
        self._progress_fn = progress_fn

    def _on_step(self) -> bool:
        if self.n_calls % self.log_interval == 0:
            vals = self.model.logger.name_to_value
            record = {
                "timestep":    self.num_timesteps,
                "loss":        vals.get("train/loss", float("nan")),
                "ep_rew_mean": vals.get("rollout/ep_rew_mean", float("nan")),
            }
            self.records.append(record)
            if self._progress_fn is not None:
                try:
                    self._progress_fn(record)
                except Exception:
                    pass
        return True


# ── Gymnasium trading environment ─────────────────────────────────────────────

class RIIATradingEnv(gym.Env):
    """Custom gymnasium environment for Nifty 50 / generic OHLCV trading.

    Each episode covers a random 252-day (≈1 year) window from the DataFrame.

    Observation (8 or 9 features):
        [daily_return_scaled, rsi_norm, macd_norm, bb_pct_b,
         trend_score, current_allocation, days_remaining_norm, atr_ratio,
         (ema_ratio_norm — if column present)]

    Action (Discrete 3):
        0 → 0%   invested (Cash)
        1 → 50%  invested (Half)
        2 → 100% invested (Full)

    Reward:
        portfolio_return per step
        − 0.005 flat penalty per step when cumulative drawdown < −10%
    """

    metadata = {"render_modes": []}

    def __init__(self, df: pd.DataFrame, episode_length: int = 252):
        super().__init__()

        self._base_cols = [
            "daily_return", "rsi_14", "macd", "macd_signal",
            "bb_pct_b", "trend_score", "Close", "atr_14",
        ]
        has_ema_ratio = "ema_ratio" in df.columns and not df["ema_ratio"].isna().all()
        self._use_ema_ratio = has_ema_ratio
        self._n_features = 9 if has_ema_ratio else 8

        required_cols = self._base_cols + (["ema_ratio"] if has_ema_ratio else [])
        self.df = df.dropna(subset=required_cols).copy()
        self.episode_length = min(episode_length, len(self.df) - 1)

        # ATR and MACD normalised as % of price — scale-invariant across all instruments and price regimes

        self.observation_space = spaces.Box(
            low=-3.0, high=3.0, shape=(self._n_features,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)

        self._reset_state()

    def _reset_state(self) -> None:
        self._step_idx = 0
        self._start_idx = 0
        self._portfolio_value = 1.0
        self._peak_value = 1.0
        self._current_allocation = 0.0
        self._portfolio_history: list[float] = []

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
        return np.array(obs_list, dtype=np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        max_start = max(0, len(self.df) - self.episode_length - 1)
        self._start_idx = int(self.np_random.integers(0, max_start + 1))
        self._step_idx = 0
        self._portfolio_value = 1.0
        self._peak_value = 1.0
        self._current_allocation = 0.0
        self._portfolio_history = [1.0]
        return self._get_obs(), {}

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, dict]:
        alloc_map = {0: 0.0, 1: 0.5, 2: 1.0}
        self._current_allocation = alloc_map[int(action)]

        row = self.df.iloc[self._start_idx + self._step_idx]
        daily_ret = float(row["daily_return"])

        portfolio_ret = self._current_allocation * daily_ret
        self._portfolio_value *= (1 + portfolio_ret)
        self._portfolio_history.append(self._portfolio_value)

        self._peak_value = max(self._peak_value, self._portfolio_value)
        current_dd = (self._portfolio_value - self._peak_value) / self._peak_value

        reward = portfolio_ret
        if current_dd < DRAWDOWN_THRESHOLD:
            reward -= 0.005

        self._step_idx += 1
        terminated = self._step_idx >= self.episode_length
        truncated = False

        obs = self._get_obs() if not terminated else np.zeros(self._n_features, dtype=np.float32)
        price = float(row["Close"]) if "Close" in row.index else None
        info = {
            "portfolio_value": self._portfolio_value,
            "allocation":      self._current_allocation,
            "drawdown":        current_dd,
        }
        log_event(
            log, "info", "trade.executed",
            symbol="NIFTY",
            action=int(action),
            qty=self._current_allocation,
            price=price,
            portfolio_value=round(self._portfolio_value, 6),
        )
        return obs, reward, terminated, truncated, info


# ── Training ──────────────────────────────────────────────────────────────────

def train_agent(
    train_df: pd.DataFrame,
    output_dir: str,
    timesteps: int,
    learning_rate: float = 1e-4,
    buffer_size: int = 100_000,
    exploration_fraction: float = 0.5,
    seed: int = 42,
    model_name: str = "rita_ddqn_model",
    progress_fn=None,
) -> Tuple[DQN, TrainingProgressCallback]:
    """Train a Double-DQN agent and save the model.

    Args:
        progress_fn: optional callable(record) invoked every log_interval steps
                     with {timestep, loss, ep_rew_mean} — used for live polling.

    Returns:
        model: trained DQN model
        progress_cb: callback holding .records (timestep, loss, ep_rew_mean)
    """
    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(output_dir, model_name)

    env = Monitor(RIIATradingEnv(train_df))

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


# ── Inference / validation ────────────────────────────────────────────────────

def run_episode(model: DQN, df: pd.DataFrame) -> dict:
    """Run the trained model deterministically through the full DataFrame.

    Used for validation (held-out period) and backtest.

    Returns dict with:
        portfolio_values, benchmark_values, allocations,
        daily_returns, dates, close_prices, performance
    """
    n_obs = model.observation_space.shape[0]

    required = [
        "daily_return", "rsi_14", "macd", "macd_signal",
        "bb_pct_b", "trend_score", "Close", "atr_14",
    ]
    if n_obs >= 9 and "ema_ratio" in df.columns:
        required.append("ema_ratio")

    data = df.dropna(subset=required).copy()
    if len(data) == 0:
        raise ValueError("DataFrame has no valid rows after dropping NaN indicators.")

    has_ema  = "ema_ratio" in data.columns and not data["ema_ratio"].isna().all()

    portfolio_value = 1.0
    peak_value = 1.0
    portfolio_values = [1.0]
    benchmark_values = [1.0]
    allocations: list[float] = []
    dates = [data.index[0]]
    close_prices = [float(data["Close"].iloc[0])]

    alloc_map = {0: 0.0, 1: 0.5, 2: 1.0}

    for i in range(len(data) - 1):
        row = data.iloc[i]
        obs_list = [
            float(np.clip(row["daily_return"] * 10, -3, 3)),
            float(np.clip(row["rsi_14"] / 100.0, 0, 1)),
            float(np.clip((row["macd"] / row["Close"]) * 1000, -3, 3)),
            float(np.clip(row["bb_pct_b"], -0.5, 1.5)),
            float(np.clip(row["trend_score"], -1, 1)),
            float(allocations[-1] if allocations else 0.0),
            float(1.0 - i / len(data)),
            float(np.clip(row["atr_14"] / row["Close"] * 100, 0, 3)),
        ]
        if n_obs >= 9 and has_ema:
            obs_list.append(float(np.clip((row["ema_ratio"] - 1.0) * 20, -3, 3)))

        obs = np.array(obs_list, dtype=np.float32)
        action, _ = model.predict(obs, deterministic=True)
        allocation = alloc_map[int(action)]

        next_row = data.iloc[i + 1]
        daily_ret  = float(next_row["daily_return"])
        portfolio_value *= (1 + allocation * daily_ret)
        peak_value = max(peak_value, portfolio_value)

        bench_value = benchmark_values[-1] * (1 + daily_ret)

        portfolio_values.append(portfolio_value)
        benchmark_values.append(bench_value)
        allocations.append(allocation)
        dates.append(data.index[i + 1])
        close_prices.append(float(next_row["Close"]))

    port_arr  = np.array(portfolio_values)
    bench_arr = np.array(benchmark_values)
    perf = compute_all_metrics(port_arr, bench_arr)

    alloc_arr = np.array(allocations)
    perf["total_trades"] = int((np.abs(np.diff(alloc_arr)) > 0).sum()) if len(alloc_arr) > 1 else 0

    return {
        "portfolio_values": portfolio_values,
        "benchmark_values": benchmark_values,
        "allocations":      allocations,
        "daily_returns":    list(np.diff(port_arr) / port_arr[:-1]),
        "dates":            pd.DatetimeIndex(dates),
        "close_prices":     close_prices,
        "performance":      perf,
    }


def validate_agent(model: DQN, val_df: pd.DataFrame) -> dict:
    """Run model on validation data and return performance summary."""
    result = run_episode(model, val_df)
    perf = result["performance"]
    return {
        "validation_period":    f"{val_df.index.min().date()} to {val_df.index.max().date()}",
        "sharpe_ratio":         perf["sharpe_ratio"],
        "max_drawdown_pct":     perf["max_drawdown_pct"],
        "portfolio_cagr_pct":   perf["portfolio_cagr_pct"],
        "benchmark_cagr_pct":   perf["benchmark_cagr_pct"],
        "sharpe_constraint_met":   perf["sharpe_constraint_met"],
        "drawdown_constraint_met": perf["drawdown_constraint_met"],
        "constraints_met":         perf["constraints_met"],
    }


def load_agent(model_path: str) -> DQN:
    """Load a saved DDQN model from disk."""
    return DQN.load(model_path)


# ── Multi-seed training ───────────────────────────────────────────────────────

def train_best_of_n(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    output_dir: str,
    timesteps: int = 50_000,
    n_seeds: int = 5,
    learning_rate: float = 1e-4,
    buffer_size: int = 100_000,
    exploration_fraction: float = 0.5,
    model_name: str = "rita_ddqn_model",
    progress_fn=None,
) -> tuple[DQN, TrainingProgressCallback, dict]:
    """Train *n_seeds* models with different random seeds; return the winner.

    Each seed is trained independently.  The best model is selected by
    validation Sharpe ratio (computed via validate_agent) and re-saved as
    the canonical model at ``output_dir/{model_name}.zip``.

    Args:
        train_df:            Training OHLCV+indicators DataFrame.
        val_df:              Held-out validation DataFrame.
        output_dir:          Directory to save the best model.
        timesteps:           SB3 total_timesteps per seed.
        n_seeds:             Number of random seeds to try.
        learning_rate:       DQN learning rate.
        buffer_size:         DQN replay buffer size.
        exploration_fraction: Fraction of timesteps for epsilon decay.
        model_name:          Stem for the saved .zip file.

    Returns:
        best_model:      The trained DQN with the highest validation Sharpe.
        best_callback:   TrainingProgressCallback from the best seed's run.
        seed_results_dict: {
            "best_seed": int,
            "n_seeds_tried": int,
            "seed_results": list[{"seed": int, "val_sharpe": float}],
        }
    """
    best_sharpe: float = -float("inf")
    best_model: DQN | None = None
    best_callback: TrainingProgressCallback | None = None
    best_seed: int = -1
    seed_results: list[dict] = []

    for seed in range(n_seeds):
        log.info("train_best_of_n.seed_start", seed=seed, n_seeds=n_seeds)

        model, cb = train_agent(
            train_df=train_df,
            output_dir=output_dir,
            timesteps=timesteps,
            learning_rate=learning_rate,
            buffer_size=buffer_size,
            exploration_fraction=exploration_fraction,
            seed=seed,
            model_name=model_name,
            progress_fn=progress_fn,
        )

        val_result = validate_agent(model, val_df)
        val_sharpe = val_result["sharpe_ratio"]
        seed_results.append({"seed": seed, "val_sharpe": round(float(val_sharpe), 4)})

        log.info(
            "train_best_of_n.seed_done",
            seed=seed,
            val_sharpe=round(float(val_sharpe), 4),
        )

        if val_sharpe > best_sharpe:
            best_sharpe = val_sharpe
            best_model = model
            best_callback = cb
            best_seed = seed

    # Re-save the winner as the canonical model path
    best_model_path = os.path.join(output_dir, model_name)
    best_model.save(best_model_path)

    log.info(
        "train_best_of_n.complete",
        best_seed=best_seed,
        best_val_sharpe=round(float(best_sharpe), 4),
        seed_results=seed_results,
    )

    seed_results_dict: dict = {
        "best_seed": best_seed,
        "n_seeds_tried": n_seeds,
        "seed_results": seed_results,
    }
    return best_model, best_callback, seed_results_dict
