"""RITA Core — Trading Environment V2 (Feature 32, Phase 3 + 3.5 + 3.6)

Scenario → Execution bridge. A SEPARATE, parallel environment to the golden
``RIIATradingEnv`` (``trading_env.py``) — which is the frozen June-release
model and MUST NOT change. Design: ``docs/design-RIIATradingEnvV2-phase3.md``.

Differences from golden (see design doc §3–§5):
  * Action space ``Discrete(4)`` — adds action 3 = "Hedged" (stay invested with
    a protective overlay) on top of the golden {Cash, Half, Full}.
  * Observation 13/14 features — golden 8/9 + running_sharpe_A + running_sharpe_B
    + dd_vs_hard_limit + is_hedged + tolerance_norm.
  * Per-episode tolerance sampling so one policy generalises across low/med/high.

Phase 3.5 reward realignment (2026-06-28):
  * Reward: **Differential Sharpe Ratio** (Moody & Saffell 1998) — dense,
    per-step, directly optimises Sharpe ratio (the graded project objective).
  * Hard MDD at -10%: episode terminates with ``MDD_TERMINAL_PENALTY`` when
    ``current_drawdown <= HARD_MDD_LIMIT`` regardless of tolerance level.
  * Causal alignment: ``step()`` reads the **next bar's** return, matching
    ``run_episode_v2`` — no train/serve skew.
  * Patch-stack removed: ``LAMBDA_BREACH/CASH_BY_TOL/OUTCOME/DOWNSIDE`` deleted.
  * Obs extended +2: running EMA moments (A, B) so the policy perceives the
    Sharpe state it is graded on (fixes POMDP F5).

Phase 3.6 per-instrument config (2026-07-08):
  * Trigger: Phase 3.5.7 retrain gate failed 0/4 instruments — a single set of
    shared hyperparameters cannot capture the different market microstructures
    across instruments (AEX mean-reverts, NIFTY trends, RELIANCE is high-vol
    INR, ASML has an earnings-shock regime).
  * ``__init__`` (and every V2 train/eval function) now accepts an optional
    ``env_config: InstrumentEnvConfig | None``. All hyperparameters that were
    module-level constants (hedge cost/floor, DSR eta, risk-free rate, hard MDD
    limit + penalty, risk-tolerance thresholds, episode length, feature
    columns) are read from ``self._config`` (or the equivalent local ``cfg``
    in the standalone eval functions) instead.
  * The module-level constants below are KEPT for backward compatibility —
    they are what ``rita.core.instrument_config.DEFAULT_ENV_CONFIG`` is built
    from, and ``env_config=None`` (the default everywhere) resolves to
    exactly that default, so all pre-3.6 call sites and the existing 33 V2
    tests behave identically.

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

from rita.core.instrument_config import DEFAULT_ENV_CONFIG, InstrumentEnvConfig
from rita.core.performance import compute_all_metrics
from rita.core.trading_env import TrainingProgressCallback  # shared, env-agnostic
from rita.logging_config import log_event

log = structlog.get_logger(__name__)


# ── Reward / hedge hyper-params (calibration defaults — tunable) ───────────────
# Phase 3.6: these are now DEFAULTS ONLY — ``instrument_config.DEFAULT_ENV_CONFIG``
# is built from them, and every function below reads its actual working values
# from an ``InstrumentEnvConfig`` (``self._config`` / local ``cfg``), never from
# these module names directly. Kept in place for backward compatibility (some
# tests import them directly) and as the single source of truth for the default.
#
# Map the Financial Goal categorical risk_tolerance → a max-drawdown threshold.
# Used ONLY for tolerance_norm conditioning — the BREACH point is HARD_MDD_LIMIT.
RISK_TOLERANCE_MDD = {"low": -0.08, "medium": -0.15, "high": -0.25}
_TOLERANCE_LEVELS = ("low", "medium", "high")

HEDGE_DAILY_FLOOR  = -0.015    # per-day downside truncation when hedged (put payoff approx)
HEDGE_COST_PER_DAY = 0.0036   # amortised protective-put carry while hedged (break-even)

# Phase 3.5 — hard MDD constraint at the graded project objective (-10%).
# Episode terminates with a large negative reward when breached, regardless of
# tolerance level. Tolerance modulates de-risking aggressiveness only.
HARD_MDD_LIMIT       = -0.10
MDD_TERMINAL_PENALTY = -5.0

# Differential Sharpe Ratio (Moody & Saffell 1998) hyper-params.
ETA      = 0.004    # EMA decay for running moments (A, B)
DSR_EPS  = 1e-12    # variance floor to avoid division by zero at episode start — not
                     # per-instrument configurable (numerical safety constant, not a
                     # calibration hyper-param).
RF_DAILY = 0.07 / 252  # daily risk-free rate (annualised 7%)

# Normalised tolerance feature for the observation so the policy can CONDITION on the
# risk level — dd_vs_tolerance alone can't disambiguate low vs high at the same ratio.
# low→0.32, medium→0.60, high→1.00.
def _tol_norm(mdd_tol: float) -> float:
    return float(np.clip(abs(mdd_tol) / 0.25, 0.0, 1.0))

def temporal_split(df, train_frac: float = 0.70, val_frac: float = 0.15):
    """Chronological train / val / test split — no shuffle (time series).

    ``val`` is used to SELECT the best-of-N policy; ``test`` is an untouched
    window for final, unbiased reporting. Reporting on test rather than val
    removes the selection-on-validation optimism that inflates best-of-N metrics.
    Returns (train_df, val_df, test_df).
    """
    n = len(df)
    i_tr = int(n * train_frac)
    i_va = int(n * (train_frac + val_frac))
    return df.iloc[:i_tr], df.iloc[i_tr:i_va], df.iloc[i_va:]


# Action → (allocation, hedged?)
_ACTION_MAP = {0: (0.0, False), 1: (0.5, False), 2: (1.0, False), 3: (1.0, True)}

# Action → (short label, advisory detail) for the execution_analyst recommendation.
_ACTION_LABEL = {
    0: ("move to cash", "de-risk fully — exit the position"),
    1: ("trim to ~50%", "reduce exposure by roughly half"),
    2: ("stay fully invested", "hold exposure — no hedge indicated"),
    3: ("apply a protective hedge", "stay invested but add downside protection"),
}

# Structural indicator columns the observation formula is hard-coded against.
# Always required (dropna) regardless of instrument feature_columns config —
# only the OPTIONAL ema_ratio 9th feature is gated by feature_columns (Phase 3.6).
_STRUCTURAL_BASE_COLS = [
    "daily_return", "rsi_14", "macd", "macd_signal",
    "bb_pct_b", "trend_score", "Close", "atr_14",
]


def _ema_ratio_enabled(df: pd.DataFrame, cfg: InstrumentEnvConfig) -> bool:
    """Whether the optional ema_ratio 9th feature is usable for this df + config.

    Phase 3.6: instruments where ema_ratio isn't predictive can drop it via
    ``feature_columns`` (design decision — see instrument_config.py docstring).
    """
    return (
        "ema_ratio" in df.columns
        and not df["ema_ratio"].isna().all()
        and "ema_ratio" in cfg.feature_columns
    )


# ── Gymnasium trading environment V2 ──────────────────────────────────────────

class RIIATradingEnvV2(gym.Env):
    """Custom gymnasium env with a hedge action and DSR reward (Phase 3.5).

    Observation (13 or 14 features):
        [daily_return_scaled, rsi_norm, macd_norm, bb_pct_b, trend_score,
         current_allocation, days_remaining_norm, atr_ratio,
         (ema_ratio_norm — if present),
         running_sharpe_A, running_sharpe_B,
         dd_vs_hard_limit, is_hedged, tolerance_norm]

    Action (Discrete 4):
        0 → Cash   (0%,   unhedged)
        1 → Half   (50%,  unhedged)
        2 → Full   (100%, unhedged)
        3 → Hedged (100% invested + protective overlay)

    Reward:
        Differential Sharpe Ratio (Moody & Saffell 1998) — dense per-step
        signal that directly optimises the Sharpe ratio. Hard episode
        termination with MDD_TERMINAL_PENALTY at HARD_MDD_LIMIT (-10%).

    Phase 3.6: all calibration hyper-params come from ``env_config``
    (an ``InstrumentEnvConfig``) instead of module-level constants.
    ``env_config=None`` (the default) resolves to
    ``instrument_config.DEFAULT_ENV_CONFIG`` — numerically identical to the
    pre-3.6 module constants, so existing callers are unaffected.
    """

    metadata = {"render_modes": []}

    def __init__(self, df: pd.DataFrame, episode_length: int | None = None,
                 fixed_tolerance: str | None = None,
                 env_config: InstrumentEnvConfig | None = None):
        super().__init__()

        self._config = env_config or DEFAULT_ENV_CONFIG

        self._base_cols = list(_STRUCTURAL_BASE_COLS)
        has_ema_ratio = _ema_ratio_enabled(df, self._config)
        self._use_ema_ratio = has_ema_ratio
        # golden 8 (or 9 w/ ema) + A + B + dd_vs_hard_limit + is_hedged + tolerance_norm
        self._n_features = (9 if has_ema_ratio else 8) + 5

        required_cols = self._base_cols + (["ema_ratio"] if has_ema_ratio else [])
        self.df = df.dropna(subset=required_cols).copy()
        effective_episode_length = (
            episode_length if episode_length is not None else self._config.episode_length
        )
        self.episode_length = min(effective_episode_length, len(self.df) - 2)

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
        self._mdd_tolerance = self._config.risk_tolerance_mdd["medium"]
        self._tolerance_level = "medium"
        self._portfolio_history: list[float] = []
        self._A = 0.0  # DSR running mean of excess returns
        self._B = 0.0  # DSR running mean of squared excess returns

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
        # Phase 3.5: running Sharpe moments so the policy perceives the objective.
        obs_list.append(float(np.clip(self._A * 100, -3, 3)))
        obs_list.append(float(np.clip(self._B * 1000, 0, 3)))
        # Drawdown relative to the hard MDD limit (both negative → positive ratio).
        dd_vs_limit = self._current_drawdown() / self._config.hard_mdd_limit
        obs_list.append(float(np.clip(dd_vs_limit, 0, 3)))
        obs_list.append(float(self._is_hedged))
        obs_list.append(_tol_norm(self._mdd_tolerance))
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
        self._A = 0.0
        self._B = 0.0
        # Sample tolerance per episode (unless pinned) so one policy serves all
        # risk levels and dd_vs_tolerance carries real signal.
        level = self._fixed_tolerance or _TOLERANCE_LEVELS[int(self.np_random.integers(0, 3))]
        self._tolerance_level = level
        self._mdd_tolerance = self._config.risk_tolerance_mdd[level]
        self._portfolio_history = [1.0]
        return self._get_obs(), {}

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, dict]:
        allocation, hedged = _ACTION_MAP[int(action)]
        self._current_allocation = allocation
        self._is_hedged = 1.0 if hedged else 0.0

        # Phase 3.5 (F2): causal alignment — read return from the NEXT bar.
        next_row = self.df.iloc[self._start_idx + self._step_idx + 1]
        daily_ret = float(next_row["daily_return"])

        # Hedged: truncate per-day downside (protective-put payoff approx) and pay
        # the amortised carry. Unhedged: raw exposure.
        if hedged:
            effective_ret = max(daily_ret, self._config.hedge_daily_floor)
            portfolio_ret = allocation * effective_ret - self._config.hedge_cost_per_day
        else:
            portfolio_ret = allocation * daily_ret

        # Safety clip for bad data.
        portfolio_ret = float(np.clip(portfolio_ret, -1.0, 1.0))

        self._portfolio_value *= (1 + portfolio_ret)
        self._portfolio_history.append(self._portfolio_value)
        self._peak_value = max(self._peak_value, self._portfolio_value)

        # Phase 3.5 (F1+F5): Differential Sharpe Ratio reward.
        R_t = portfolio_ret - self._config.rf_daily
        delta_A = R_t - self._A
        var = self._B - self._A ** 2
        if var > DSR_EPS:
            reward = (self._B * delta_A - 0.5 * self._A * (R_t ** 2 - self._B)) / (var ** 1.5)
        else:
            reward = 0.0

        # Update running moments.
        self._A += self._config.dsr_eta * (R_t - self._A)
        self._B += self._config.dsr_eta * (R_t ** 2 - self._B)

        # Phase 3.5 (F3): hard MDD constraint at -10% (per-instrument configurable).
        current_dd = self._current_drawdown()
        terminated = False
        if current_dd <= self._config.hard_mdd_limit:
            terminated = True
            reward = self._config.mdd_terminal_penalty

        self._step_idx += 1
        if not terminated and self._step_idx >= self.episode_length:
            terminated = True
        truncated = False

        obs = self._get_obs() if not terminated else np.zeros(self._n_features, dtype=np.float32)
        row = self.df.iloc[self._start_idx + self._step_idx]
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
    env_config: InstrumentEnvConfig | None = None,
) -> Tuple[DQN, TrainingProgressCallback]:
    """Train a Double-DQN agent on RIIATradingEnvV2 and save the model.

    Mirrors golden ``train_agent`` but binds ``RIIATradingEnvV2`` (4 actions).
    ``env_config`` (Phase 3.6) is forwarded to the env constructor; ``None``
    resolves to ``DEFAULT_ENV_CONFIG`` inside the env.
    """
    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(output_dir, model_name)

    env = Monitor(RIIATradingEnvV2(train_df, env_config=env_config))

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


def train_best_of_n_v2(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    output_dir: str,
    timesteps: int = 50_000,
    n_seeds: int = 5,
    learning_rate: float = 1e-4,
    buffer_size: int = 100_000,
    exploration_fraction: float = 0.5,
    model_name: str = "rita_ddqn_v2_model",
    progress_fn=None,
    eval_tolerance: str = "medium",
    test_df: pd.DataFrame | None = None,
    env_config: InstrumentEnvConfig | None = None,
) -> "tuple[DQN, TrainingProgressCallback, dict]":
    """Train ``n_seeds`` V2 policies; keep the one with the best validation Sharpe.

    Reduces the single-seed noise seen in Phase 3 tuning. Selection metric is the
    held-out Sharpe from ``run_episode_v2`` at ``eval_tolerance``. The winner is
    re-saved as the canonical ``output_dir/{model_name}.zip``.

    If ``test_df`` is provided, the winner is also evaluated on the held-out test
    set and test metrics are included in the return dict (honest evaluation, F4).

    ``env_config`` (Phase 3.6) is forwarded to every seed's training AND every
    evaluation call — training/eval consistency (same config both paths).
    """
    best_sharpe = -float("inf")
    best_model = None
    best_cb = None
    best_seed = -1
    seed_results: list[dict] = []

    for seed in range(n_seeds):
        log.info("train_best_of_n_v2.seed_start", seed=seed, n_seeds=n_seeds)
        model, cb = train_agent_v2(
            train_df=train_df,
            output_dir=output_dir,
            timesteps=timesteps,
            learning_rate=learning_rate,
            buffer_size=buffer_size,
            exploration_fraction=exploration_fraction,
            seed=seed,
            model_name=model_name,
            progress_fn=progress_fn,
            env_config=env_config,
        )
        res = run_episode_v2(model, val_df, risk_tolerance=eval_tolerance, env_config=env_config)
        val_sharpe = float(res["performance"].get("sharpe_ratio", 0.0))
        seed_results.append({
            "seed": seed,
            "val_sharpe": round(val_sharpe, 4),
            "hedge_usage_pct": res["hedge_usage_pct"],
        })
        log.info("train_best_of_n_v2.seed_done", seed=seed, val_sharpe=round(val_sharpe, 4))
        if val_sharpe > best_sharpe:
            best_sharpe, best_model, best_cb, best_seed = val_sharpe, model, cb, seed

    best_model.save(os.path.join(output_dir, model_name))
    log.info("train_best_of_n_v2.complete", best_seed=best_seed,
             best_val_sharpe=round(best_sharpe, 4), seed_results=seed_results)

    result_dict: dict = {
        "best_seed": best_seed,
        "n_seeds_tried": n_seeds,
        "seed_results": seed_results,
    }

    # Phase 3.5 (F4): honest held-out evaluation on test set.
    if test_df is not None:
        test_res = run_episode_v2(best_model, test_df, risk_tolerance=eval_tolerance, env_config=env_config)
        test_perf = test_res["performance"]
        result_dict["test_sharpe"] = round(float(test_perf.get("sharpe_ratio", 0.0)), 4)
        result_dict["test_mdd"] = round(float(test_perf.get("max_drawdown_pct", 0.0)) / 100.0, 4)
        result_dict["test_return"] = round(float(test_perf.get("portfolio_total_return_pct", 0.0)) / 100.0, 4)
        result_dict["test_hedge_usage_pct"] = test_res["hedge_usage_pct"]
        log.info("train_best_of_n_v2.test_eval", test_sharpe=result_dict["test_sharpe"],
                 test_mdd=result_dict["test_mdd"])

    return best_model, best_cb, result_dict


# ── Inference / backtest (V2-owned — handles the 4-action map) ─────────────────

def load_agent_v2(model_path: str) -> DQN:
    """Load a saved V2 DDQN model from disk (advisory use only in Phase 3)."""
    from rita.core.model_compat import load_dqn_compat

    return load_dqn_compat(model_path)


def run_episode_v2(
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


# ── Static-threshold baseline (Phase 3 acceptance gate) ───────────────────────

def run_static_baseline_v2(
    df: pd.DataFrame,
    risk_tolerance: str = "medium",
    env_config: InstrumentEnvConfig | None = None,
) -> dict:
    """Rule-based hedge baseline — the incumbent the RL policy must beat.

    The classic static rule: stay FULLY INVESTED and switch on a protective
    hedge once realised drawdown breaches the tolerance threshold
    (``current_dd <= mdd_tol``), switch it off once recovered above it. No
    learning — it only reacts after the breach, whereas the RL policy can hedge
    pre-emptively. Identical per-step return mechanics to ``run_episode_v2`` so
    the two are directly comparable on the same DataFrame; same result shape.

    ``env_config`` (Phase 3.6) supplies the same per-instrument hedge cost/floor
    and tolerance thresholds used by the RL policy, so F5 (baseline-relative
    performance) compares like-for-like.
    """
    cfg = env_config or DEFAULT_ENV_CONFIG
    mdd_tol = cfg.risk_tolerance_mdd.get(risk_tolerance, cfg.risk_tolerance_mdd["medium"])

    required = list(_STRUCTURAL_BASE_COLS)
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

    for i in range(len(data) - 1):
        current_dd = (portfolio_value - peak_value) / peak_value
        # Static rule: full allocation; hedge iff drawdown has breached tolerance.
        allocation = 1.0
        hedged = current_dd <= mdd_tol

        next_row = data.iloc[i + 1]
        daily_ret = float(next_row["daily_return"])
        if hedged:
            effective_ret = max(daily_ret, cfg.hedge_daily_floor)
            portfolio_ret = allocation * effective_ret - cfg.hedge_cost_per_day
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
    env_config: InstrumentEnvConfig | None = None,
) -> dict:
    """Single-shot hedge recommendation from a trained V2 policy.

    ADVISORY ONLY — builds the current observation, asks the policy, and returns
    a labelled recommendation. It NEVER places, routes, or simulates an order.

    Drawdown is proxied from the instrument's own recent ``lookback`` closes
    (peak-to-current) since live portfolio state isn't available in the chat
    path. Returns: action, label, detail, drawdown_pct, mdd_tolerance_pct, breach.

    ``env_config`` (Phase 3.6) should match the config the served ``model`` was
    trained with, so the tolerance/MDD-limit framing is consistent.
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
    if n_obs >= 14 and has_ema:
        obs_list.append(float(np.clip((row["ema_ratio"] - 1.0) * 20, -3, 3)))
    # No episode context for A/B — use zeros (point-in-time advisory).
    obs_list.append(0.0)                       # running_sharpe_A
    obs_list.append(0.0)                       # running_sharpe_B
    obs_list.append(float(np.clip(current_dd / cfg.hard_mdd_limit, 0, 3)))
    obs_list.append(0.0)                       # is_hedged
    obs_list.append(_tol_norm(mdd_tol))        # tolerance_norm

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
