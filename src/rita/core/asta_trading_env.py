"""RITA Core — ASTA Trading Environment (Feature 37, Phase 2)

Gymnasium environment extending the V2 pattern with ASTA GEO PAN signals in
the observation space and ASTA-aligned reward shaping.

Observation (20 or 21 features):
    [V2 base 13/14] + [asta_signal_enc, asta_confidence, stoch_k_norm,
     adx_norm, tide_trend_enc, bb_squeeze, vol_ratio_norm]

Action: Discrete(4) — Cash / Half / Full / Hedged (same as V2).
Reward: DSR (primary) + ASTA signal alignment bonus (secondary).
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

from rita.core.instrument_config import DEFAULT_ENV_CONFIG, InstrumentEnvConfig
from rita.core.performance import compute_all_metrics
from rita.core.trading_env import TrainingProgressCallback
from rita.logging_config import log_event

log = structlog.get_logger(__name__)

_SIGNAL_MAP = {"BUY": 1.0, "HOLD": 0.0, "SELL": -1.0}
_ACTION_MAP = {0: (0.0, False), 1: (0.5, False), 2: (1.0, False), 3: (1.0, True)}
_TOLERANCE_LEVELS = ("low", "medium", "high")

ASTA_REWARD_SCALE = 0.1

_STRUCTURAL_BASE_COLS = [
    "daily_return", "rsi_14", "macd", "macd_signal",
    "bb_pct_b", "trend_score", "Close", "atr_14",
]
_ASTA_NUMERIC_COLS = ["asta_confidence", "stoch_k", "adx"]

DSR_EPS = 1e-12


def _tol_norm(mdd_tol: float) -> float:
    return float(np.clip(abs(mdd_tol) / 0.25, 0.0, 1.0))


def _ema_ratio_enabled(df: pd.DataFrame, cfg: InstrumentEnvConfig) -> bool:
    return (
        "ema_ratio" in df.columns
        and not df["ema_ratio"].isna().all()
        and "ema_ratio" in cfg.feature_columns
    )


def _safe_bool_col(df: pd.DataFrame, col: str) -> pd.Series:
    """Return a boolean Series, handling string 'True'/'False' from CSV."""
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    s = df[col]
    if s.dtype == object:
        return s.str.lower() == "true"
    return s.astype(bool)


def _prepare_asta_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Pre-encode ASTA signal and derived columns onto a DataFrame copy."""
    out = df.copy()
    out["asta_signal_enc"] = out["asta_signal"].map(_SIGNAL_MAP).fillna(0.0)

    uptick = _safe_bool_col(out, "tide_macd_hist_uptick")
    downtick = _safe_bool_col(out, "tide_macd_hist_downtick")
    out["tide_trend_enc"] = np.where(uptick, 1.0, np.where(downtick, -1.0, 0.0))

    for col, fill in [("bb_squeeze", False), ("vol_ratio", 1.0)]:
        if col in out.columns:
            if out[col].dtype == object:
                out[col] = _safe_bool_col(out, col).astype(float) if fill == 0 else pd.to_numeric(out[col], errors="coerce").fillna(fill)
            else:
                out[col] = out[col].fillna(fill if not isinstance(fill, bool) else 0.0)
        else:
            out[col] = fill

    return out


# ── Gymnasium trading environment — ASTA ────────────────────────────────────

class RIIATradingEnvASTA(gym.Env):
    """Gymnasium env with ASTA GEO PAN signal features in observation space.

    Extends V2's 13/14-feature observation with 7 ASTA features (total 20/21):
        asta_signal_enc   — BUY=+1, HOLD=0, SELL=−1
        asta_confidence   — labeler confidence score (0–1)
        stoch_k_norm      — Stochastic %K / 100
        adx_norm          — ADX / 100
        tide_trend_enc    — monthly trend direction (−1/0/+1)
        bb_squeeze        — Bollinger squeeze flag (0/1)
        vol_ratio_norm    — volume vs 20-SMA, clipped [0, 3]

    Reward = DSR + ASTA alignment bonus (scaled by asta_reward_scale).
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        df: pd.DataFrame,
        episode_length: int | None = None,
        fixed_tolerance: str | None = None,
        env_config: InstrumentEnvConfig | None = None,
        asta_reward_scale: float = ASTA_REWARD_SCALE,
    ):
        super().__init__()
        self._config = env_config or DEFAULT_ENV_CONFIG
        self._asta_reward_scale = asta_reward_scale

        has_ema_ratio = _ema_ratio_enabled(df, self._config)
        self._use_ema_ratio = has_ema_ratio
        # V2 base (8/9) + DSR/hedge (5) + ASTA (7)
        self._n_features = (9 if has_ema_ratio else 8) + 5 + 7

        prepared = _prepare_asta_columns(df)
        required = list(_STRUCTURAL_BASE_COLS) + list(_ASTA_NUMERIC_COLS)
        if has_ema_ratio:
            required.append("ema_ratio")
        self.df = prepared.dropna(subset=required).copy()

        effective_ep = episode_length if episode_length is not None else self._config.episode_length
        self.episode_length = min(effective_ep, len(self.df) - 2)
        self._fixed_tolerance = fixed_tolerance

        self.observation_space = spaces.Box(
            low=-3.0, high=3.0, shape=(self._n_features,), dtype=np.float32,
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
        self._mdd_tolerance = self._config.risk_tolerance_mdd["medium"]
        self._tolerance_level = "medium"
        self._portfolio_history: list[float] = []
        self._A = 0.0
        self._B = 0.0

    def _current_drawdown(self) -> float:
        return (self._portfolio_value - self._peak_value) / self._peak_value

    def _get_obs(self) -> np.ndarray:
        row = self.df.iloc[self._start_idx + self._step_idx]

        obs = [
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
            obs.append(float(np.clip((row["ema_ratio"] - 1.0) * 20, -3, 3)))

        obs.append(float(np.clip(self._A * 100, -3, 3)))
        obs.append(float(np.clip(self._B * 1000, 0, 3)))
        dd_vs_limit = self._current_drawdown() / self._config.hard_mdd_limit
        obs.append(float(np.clip(dd_vs_limit, 0, 3)))
        obs.append(float(self._is_hedged))
        obs.append(_tol_norm(self._mdd_tolerance))

        # ASTA features (7)
        obs.append(float(row.get("asta_signal_enc", 0.0)))
        obs.append(float(np.clip(row.get("asta_confidence", 0.0), 0, 1)))
        obs.append(float(np.clip(row.get("stoch_k", 50) / 100.0, 0, 1)))
        obs.append(float(np.clip(row.get("adx", 25) / 100.0, 0, 1)))
        obs.append(float(row.get("tide_trend_enc", 0.0)))
        obs.append(float(1.0 if row.get("bb_squeeze") else 0.0))
        obs.append(float(np.clip(row.get("vol_ratio", 1.0), 0, 3)))

        return np.array(obs, dtype=np.float32)

    def _asta_alignment_reward(self, action: int) -> float:
        row = self.df.iloc[self._start_idx + self._step_idx]
        sig = float(row.get("asta_signal_enc", 0.0))
        conf = float(row.get("asta_confidence", 0.0))
        if sig == 0.0 or conf == 0.0:
            return 0.0
        allocation, _ = _ACTION_MAP[action]
        alignment = (allocation - 0.5) * sig  # +0.5 max when aligned, −0.5 when opposed
        return alignment * conf * self._asta_reward_scale

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        max_start = max(0, len(self.df) - self.episode_length - 1)
        self._start_idx = int(self.np_random.integers(0, max_start + 1))
        self._step_idx = 0
        self._portfolio_value = 1.0
        self._peak_value = 1.0
        self._current_allocation = 0.0
        self._is_hedged = 0.0
        self._A = 0.0
        self._B = 0.0
        level = self._fixed_tolerance or _TOLERANCE_LEVELS[int(self.np_random.integers(0, 3))]
        self._tolerance_level = level
        self._mdd_tolerance = self._config.risk_tolerance_mdd[level]
        self._portfolio_history = [1.0]
        return self._get_obs(), {}

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, dict]:
        allocation, hedged = _ACTION_MAP[int(action)]
        self._current_allocation = allocation
        self._is_hedged = 1.0 if hedged else 0.0

        asta_bonus = self._asta_alignment_reward(int(action))

        next_row = self.df.iloc[self._start_idx + self._step_idx + 1]
        daily_ret = float(next_row["daily_return"])

        if hedged:
            effective_ret = max(daily_ret, self._config.hedge_daily_floor)
            portfolio_ret = allocation * effective_ret - self._config.hedge_cost_per_day
        else:
            portfolio_ret = allocation * daily_ret
        portfolio_ret = float(np.clip(portfolio_ret, -1.0, 1.0))

        self._portfolio_value *= (1 + portfolio_ret)
        self._portfolio_history.append(self._portfolio_value)
        self._peak_value = max(self._peak_value, self._portfolio_value)

        # DSR reward
        R_t = portfolio_ret - self._config.rf_daily
        delta_A = R_t - self._A
        var = self._B - self._A ** 2
        if var > DSR_EPS:
            dsr_reward = (self._B * delta_A - 0.5 * self._A * (R_t ** 2 - self._B)) / (var ** 1.5)
        else:
            dsr_reward = 0.0

        reward = dsr_reward + asta_bonus

        self._A += self._config.dsr_eta * (R_t - self._A)
        self._B += self._config.dsr_eta * (R_t ** 2 - self._B)

        current_dd = self._current_drawdown()
        terminated = False
        if current_dd <= self._config.hard_mdd_limit:
            terminated = True
            reward = self._config.mdd_terminal_penalty

        self._step_idx += 1
        if not terminated and self._step_idx >= self.episode_length:
            terminated = True
        truncated = False

        obs_out = self._get_obs() if not terminated else np.zeros(self._n_features, dtype=np.float32)
        row = self.df.iloc[self._start_idx + self._step_idx]
        price = float(row["Close"]) if "Close" in row.index else None
        info = {
            "portfolio_value": self._portfolio_value,
            "allocation": self._current_allocation,
            "is_hedged": self._is_hedged,
            "drawdown": current_dd,
            "mdd_tolerance": self._mdd_tolerance,
            "asta_bonus": asta_bonus,
        }
        log_event(
            log, "info", "trade.executed",
            symbol="NIFTY", action=int(action), qty=self._current_allocation,
            hedged=bool(hedged), price=price,
            portfolio_value=round(self._portfolio_value, 6),
        )
        return obs_out, reward, terminated, truncated, info


# ── Training ────────────────────────────────────────────────────────────────

def train_agent_asta(
    train_df: pd.DataFrame,
    output_dir: str,
    timesteps: int,
    learning_rate: float = 1e-4,
    buffer_size: int = 100_000,
    exploration_fraction: float = 0.5,
    seed: int = 42,
    model_name: str = "rita_ddqn_asta_model",
    progress_fn=None,
    env_config: InstrumentEnvConfig | None = None,
    asta_reward_scale: float = ASTA_REWARD_SCALE,
) -> Tuple[DQN, TrainingProgressCallback]:
    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(output_dir, model_name)

    env = Monitor(RIIATradingEnvASTA(
        train_df, env_config=env_config, asta_reward_scale=asta_reward_scale,
    ))

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


def train_best_of_n_asta(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    output_dir: str,
    timesteps: int = 50_000,
    n_seeds: int = 5,
    learning_rate: float = 1e-4,
    buffer_size: int = 100_000,
    exploration_fraction: float = 0.5,
    model_name: str = "rita_ddqn_asta_model",
    progress_fn=None,
    eval_tolerance: str = "medium",
    test_df: pd.DataFrame | None = None,
    env_config: InstrumentEnvConfig | None = None,
    asta_reward_scale: float = ASTA_REWARD_SCALE,
) -> "tuple[DQN, TrainingProgressCallback, dict]":
    best_sharpe = -float("inf")
    best_model = None
    best_cb = None
    best_seed = -1
    seed_results: list[dict] = []

    for seed in range(n_seeds):
        log.info("train_best_of_n_asta.seed_start", seed=seed, n_seeds=n_seeds)
        model, cb = train_agent_asta(
            train_df=train_df, output_dir=output_dir, timesteps=timesteps,
            learning_rate=learning_rate, buffer_size=buffer_size,
            exploration_fraction=exploration_fraction, seed=seed,
            model_name=model_name, progress_fn=progress_fn,
            env_config=env_config, asta_reward_scale=asta_reward_scale,
        )
        res = run_episode_asta(model, val_df, risk_tolerance=eval_tolerance, env_config=env_config)
        val_sharpe = float(res["performance"].get("sharpe_ratio", 0.0))
        seed_results.append({
            "seed": seed,
            "val_sharpe": round(val_sharpe, 4),
            "hedge_usage_pct": res["hedge_usage_pct"],
            "asta_win_rate_pct": res["asta_win_rate_pct"],
        })
        log.info("train_best_of_n_asta.seed_done", seed=seed, val_sharpe=round(val_sharpe, 4))
        if val_sharpe > best_sharpe:
            best_sharpe, best_model, best_cb, best_seed = val_sharpe, model, cb, seed

    best_model.save(os.path.join(output_dir, model_name))
    log.info("train_best_of_n_asta.complete", best_seed=best_seed,
             best_val_sharpe=round(best_sharpe, 4), seed_results=seed_results)

    result_dict: dict = {
        "best_seed": best_seed,
        "n_seeds_tried": n_seeds,
        "seed_results": seed_results,
    }

    if test_df is not None:
        test_res = run_episode_asta(best_model, test_df, risk_tolerance=eval_tolerance, env_config=env_config)
        test_perf = test_res["performance"]
        result_dict["test_sharpe"] = round(float(test_perf.get("sharpe_ratio", 0.0)), 4)
        result_dict["test_mdd"] = round(float(test_perf.get("max_drawdown_pct", 0.0)) / 100.0, 4)
        result_dict["test_return"] = round(float(test_perf.get("portfolio_total_return_pct", 0.0)) / 100.0, 4)
        result_dict["test_hedge_usage_pct"] = test_res["hedge_usage_pct"]
        result_dict["test_asta_win_rate_pct"] = test_res["asta_win_rate_pct"]
        log.info("train_best_of_n_asta.test_eval",
                 test_sharpe=result_dict["test_sharpe"], test_mdd=result_dict["test_mdd"])

    return best_model, best_cb, result_dict


# ── Inference / backtest ────────────────────────────────────────────────────

def run_episode_asta(
    model: DQN,
    df: pd.DataFrame,
    risk_tolerance: str = "medium",
    env_config: InstrumentEnvConfig | None = None,
) -> dict:
    """Run the ASTA model deterministically through the full DataFrame.

    Returns the same shape as V2's ``run_episode_v2`` plus ASTA-specific
    metrics: asta_signal_count, asta_alignment_count, asta_win_rate_pct.
    """
    cfg = env_config or DEFAULT_ENV_CONFIG
    n_obs = model.observation_space.shape[0]
    mdd_tol = cfg.risk_tolerance_mdd.get(risk_tolerance, cfg.risk_tolerance_mdd["medium"])

    data = _prepare_asta_columns(df)
    required = list(_STRUCTURAL_BASE_COLS) + list(_ASTA_NUMERIC_COLS)
    # 21 features = with ema_ratio; 20 = without
    has_ema = _ema_ratio_enabled(data, cfg) and n_obs >= 21
    if has_ema:
        required.append("ema_ratio")
    data = data.dropna(subset=required).copy()
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
    asta_alignment_count = 0
    asta_signal_count = 0

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
        if has_ema:
            obs_list.append(float(np.clip((row["ema_ratio"] - 1.0) * 20, -3, 3)))

        obs_list.append(float(np.clip(A * 100, -3, 3)))
        obs_list.append(float(np.clip(B * 1000, 0, 3)))
        obs_list.append(float(np.clip(current_dd / cfg.hard_mdd_limit, 0, 3)))
        obs_list.append(float(prev_hedged))
        obs_list.append(tol_feat)

        obs_list.append(float(row.get("asta_signal_enc", 0.0)))
        obs_list.append(float(np.clip(row.get("asta_confidence", 0.0), 0, 1)))
        obs_list.append(float(np.clip(row.get("stoch_k", 50) / 100.0, 0, 1)))
        obs_list.append(float(np.clip(row.get("adx", 25) / 100.0, 0, 1)))
        obs_list.append(float(row.get("tide_trend_enc", 0.0)))
        obs_list.append(float(1.0 if row.get("bb_squeeze") else 0.0))
        obs_list.append(float(np.clip(row.get("vol_ratio", 1.0), 0, 3)))

        obs = np.array(obs_list, dtype=np.float32)
        action, _ = model.predict(obs, deterministic=True)
        allocation, hedged = _ACTION_MAP[int(action)]

        asta_sig = float(row.get("asta_signal_enc", 0.0))
        if asta_sig != 0.0:
            asta_signal_count += 1
            if (asta_sig > 0 and allocation >= 0.5) or (asta_sig < 0 and allocation <= 0.5):
                asta_alignment_count += 1

        next_row = data.iloc[i + 1]
        daily_ret = float(next_row["daily_return"])
        if hedged:
            effective_ret = max(daily_ret, cfg.hedge_daily_floor)
            portfolio_ret = allocation * effective_ret - cfg.hedge_cost_per_day
        else:
            portfolio_ret = allocation * daily_ret
        portfolio_value *= (1 + portfolio_ret)
        peak_value = max(peak_value, portfolio_value)

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
    asta_win_rate = (
        round(100 * asta_alignment_count / max(1, asta_signal_count), 2)
        if asta_signal_count > 0 else 0.0
    )

    return {
        "portfolio_values": portfolio_values,
        "benchmark_values": benchmark_values,
        "allocations": allocations,
        "hedge_flags": hedge_flags,
        "hedged_steps": hedged_steps,
        "hedge_usage_pct": round(100 * hedged_steps / max(1, len(hedge_flags)), 2),
        "daily_returns": list(np.diff(port_arr) / port_arr[:-1]),
        "dates": pd.DatetimeIndex(dates),
        "close_prices": close_prices,
        "performance": perf,
        "asta_signal_count": asta_signal_count,
        "asta_alignment_count": asta_alignment_count,
        "asta_win_rate_pct": asta_win_rate,
    }
