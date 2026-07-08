"""RITA Core — ML Dispatch

Entry point for Double-DQN training.  Called by WorkflowService in a
background thread; must be fully self-contained (opens its own DB session
if needed, manages its own file I/O).

Pipeline:
    1. Load instrument OHLCV CSV
    2. Compute technical indicators (ta library)
    3. Train/validation split (80 / 20 by date)
    4. Train Double-DQN via stable-baselines3
    5. Run deterministic validation episode → real performance metrics
    6. Save model to output_dir
    7. Return TrainingOutcome with real Sharpe, MDD, return, episode_metrics
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import structlog
import yaml

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Per-instrument fine-tuning defaults
# ---------------------------------------------------------------------------

_INSTRUMENTS_CONFIG_DIR = Path(__file__).parents[4] / "config" / "instruments"

_INSTRUMENT_DEFAULTS_CACHE: dict[str, dict] = {}


def load_instrument_defaults(instrument: str) -> dict:
    """Return the training sub-section from config/instruments/{instrument}.yaml.

    Keys: timesteps, learning_rate, buffer_size, exploration_pct, n_seeds,
          episode_length.

    Falls back to an empty dict if no file exists for the instrument, so
    callers can always do ``defaults.get("n_seeds", 1)`` safely.
    """
    key = instrument.upper()
    if key in _INSTRUMENT_DEFAULTS_CACHE:
        return _INSTRUMENT_DEFAULTS_CACHE[key]

    config_file = _INSTRUMENTS_CONFIG_DIR / f"{key.lower()}.yaml"
    if not config_file.exists():
        log.warning("instrument_defaults.not_found", instrument=key)
        _INSTRUMENT_DEFAULTS_CACHE[key] = {}
        return {}

    with config_file.open() as fh:
        raw = yaml.safe_load(fh)

    defaults = raw.get("training", {})
    _INSTRUMENT_DEFAULTS_CACHE[key] = defaults
    log.debug("instrument_defaults.loaded", instrument=key, keys=list(defaults.keys()))
    return defaults


# ---------------------------------------------------------------------------
# Configuration & result dataclasses (imported by WorkflowService)
# ---------------------------------------------------------------------------

@dataclass
class TrainingConfig:
    run_id:           str
    instrument:       str
    model_version:    str
    algorithm:        str
    timesteps:        int
    learning_rate:    float
    buffer_size:      int
    net_arch:         str
    exploration_pct:  float
    output_dir:       str
    n_seeds:          int = 1


@dataclass
class TrainingOutcome:
    model_path:      str
    sharpe:          float       # validation-phase Sharpe
    max_drawdown:    float       # validation-phase MDD (fraction)
    total_return:    float       # validation-phase total return (fraction)
    val_trades:      int = 0
    train_sharpe:    float = 0.0
    train_mdd:       float = 0.0
    train_return:    float = 0.0
    train_trades:    int = 0
    episode_metrics: list[dict] = field(default_factory=list)
    """Each dict: timestep, loss, ep_rew_mean."""
    seed_results:    dict = field(default_factory=dict)
    """Populated when n_seeds > 1: best_seed, n_seeds_tried, seed_results list."""


# ---------------------------------------------------------------------------
# Training entry point
# ---------------------------------------------------------------------------

def train(config: TrainingConfig, progress_fn=None) -> TrainingOutcome:
    """Load data, train Double-DQN, validate, save model, return real metrics.

    Args:
        progress_fn: optional callable(record) forwarded to TrainingProgressCallback.
                     Called every 1000 timesteps with {timestep, loss, ep_rew_mean}.
    """  # noqa: D401
    """Load data, train Double-DQN, validate, save model, return real metrics."""
    from rita.core.data_loader import load_ohlcv_csv
    from rita.core.data_understanding import find_instrument_csv
    from rita.core.technical_analyzer import calculate_indicators
    from rita.core.trading_env import train_agent, train_best_of_n, run_episode

    # Feature 32 Phase 3 — route to the V2 env trainer when model_version is a V2
    # stem. Golden trainers are left bound for all other versions (unchanged).
    _is_v2 = config.model_version.startswith("rita_ddqn_v2")
    env_config = None
    if _is_v2:
        from rita.core.trading_env_v2 import (
            train_agent_v2 as train_agent,
            train_best_of_n_v2 as train_best_of_n,
            run_episode_v2 as run_episode,
            temporal_split,
        )
        from rita.core.instrument_config import load_instrument_env_config
        from rita.core.rl_scorecard import compute_scorecard, save_scorecard
        env_config = load_instrument_env_config(config.instrument)
        log.info("ml_dispatch.env_config_loaded", instrument=config.instrument,
                 episode_length=env_config.episode_length, n_features=len(env_config.feature_columns))

    # ── 1. Load OHLCV data ────────────────────────────────────────────────────
    log.info("ml_dispatch.load_data", instrument=config.instrument)
    csv_path = find_instrument_csv(config.instrument)
    df = load_ohlcv_csv(str(csv_path))
    log.info("ml_dispatch.data_loaded", rows=len(df))

    # ── 2. Technical indicators ───────────────────────────────────────────────
    df = calculate_indicators(df)
    log.info("ml_dispatch.indicators_computed", rows=len(df))

    # ── 3. Train / validation (/ test) split ────────────────────────────────────
    test_df = None
    if _is_v2:
        train_df, val_df, test_df = temporal_split(df)
    else:
        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx]
        val_df   = df.iloc[split_idx:]

    # ── 4. Train ──────────────────────────────────────────────────────────────
    model_name = f"{config.model_version}_{config.run_id[:8]}"
    log.info("ml_dispatch.training_start", run_id=config.run_id, timesteps=config.timesteps, n_seeds=config.n_seeds)
    seed_results_dict: dict = {}

    v2_kwargs = {"env_config": env_config, "test_df": test_df} if _is_v2 else {}
    if config.n_seeds > 1 and train_best_of_n is not None:
        model, progress_cb, seed_results_dict = train_best_of_n(
            train_df=train_df,
            val_df=val_df,
            output_dir=config.output_dir,
            timesteps=config.timesteps,
            n_seeds=config.n_seeds,
            learning_rate=config.learning_rate,
            buffer_size=config.buffer_size,
            exploration_fraction=config.exploration_pct,
            model_name=model_name,
            progress_fn=progress_fn,
            **v2_kwargs,
        )
    else:
        single_kwargs = {"env_config": env_config} if _is_v2 else {}
        model, progress_cb = train_agent(
            train_df=train_df,
            output_dir=config.output_dir,
            timesteps=config.timesteps,
            learning_rate=config.learning_rate,
            buffer_size=config.buffer_size,
            exploration_fraction=config.exploration_pct,
            seed=42,
            model_name=model_name,
            progress_fn=progress_fn,
            **single_kwargs,
        )

    model_path = str(Path(config.output_dir) / (model_name + ".zip"))
    log.info("ml_dispatch.training_complete", run_id=config.run_id, model_path=model_path)

    # ── 5. Validation episode → real performance metrics ──────────────────────
    sharpe = 0.0
    mdd = 0.0
    total_return = 0.0
    val_trades = 0
    eval_df = test_df if _is_v2 else val_df
    eval_kwargs = {"env_config": env_config} if _is_v2 else {}
    try:
        val_result = run_episode(model, eval_df, **eval_kwargs)
        perf = val_result["performance"]
        sharpe       = perf["sharpe_ratio"]
        mdd          = perf["max_drawdown_pct"] / 100.0
        total_return = perf["portfolio_total_return_pct"] / 100.0
        val_trades   = int(perf.get("total_trades", 0))
    except Exception:
        pass
    log.info("ml_dispatch.validation_complete", run_id=config.run_id, sharpe=round(sharpe, 3), mdd=round(mdd, 4))

    # ── 5b. Training episode → train-phase metrics ────────────────────────────
    train_sharpe = 0.0
    train_mdd = 0.0
    train_return = 0.0
    train_trades = 0
    try:
        train_result = run_episode(model, train_df, **eval_kwargs)
        tp = train_result["performance"]
        train_sharpe = tp["sharpe_ratio"]
        train_mdd    = tp["max_drawdown_pct"] / 100.0
        train_return = tp["portfolio_total_return_pct"] / 100.0
        train_trades = int(tp.get("total_trades", 0))
    except Exception:
        pass
    log.info("ml_dispatch.train_episode_complete", run_id=config.run_id, train_sharpe=round(train_sharpe, 3))

    # ── 5c. RL diagnostic scorecard (V2 only) ────────────────────────────────
    scorecard_path = None
    if _is_v2 and test_df is not None:
        try:
            seed_list = seed_results_dict.get("seed_results") if seed_results_dict else None
            scorecard = compute_scorecard(
                model=model,
                test_df=test_df,
                train_df=train_df,
                episode_metrics=list(progress_cb.records),
                seed_results=seed_list,
                env_config=env_config,
                instrument=config.instrument,
                run_id=config.run_id,
            )
            scorecard_path = save_scorecard(
                scorecard, config.output_dir, config.instrument, config.run_id,
            )
            log.info("ml_dispatch.scorecard_saved", path=scorecard_path)
        except Exception:
            log.exception("ml_dispatch.scorecard_failed", run_id=config.run_id)

    # ── 6. Episode metrics from callback ─────────────────────────────────────
    episode_metrics = [
        {
            "episode":      i + 1,
            "timestep":     r["timestep"],
            "reward":       float(r["ep_rew_mean"]) if not math.isnan(r["ep_rew_mean"]) else 0.0,
            "loss":         float(r["loss"])        if not math.isnan(r["loss"])        else 0.0,
            "epsilon":      0.0,
            "portfolio_value": 1.0,
        }
        for i, r in enumerate(progress_cb.records)
    ]

    # Merge seed_results into episode_metrics metadata if multi-seed run
    training_metadata: dict = {}
    if seed_results_dict:
        training_metadata.update(seed_results_dict)

    return TrainingOutcome(
        model_path=model_path,
        sharpe=round(sharpe, 4),
        max_drawdown=round(mdd, 4),
        total_return=round(total_return, 4),
        val_trades=val_trades,
        train_sharpe=round(train_sharpe, 4),
        train_mdd=round(train_mdd, 4),
        train_return=round(train_return, 4),
        train_trades=train_trades,
        episode_metrics=episode_metrics,
        seed_results=training_metadata,
    )
