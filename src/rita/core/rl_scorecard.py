"""RITA Core — RL Diagnostic Scorecard (Feature 32, Phase 3.6)

Computes the 10-parameter RL diagnostic scorecard (5 Functional + 5 Technical,
see REQUIREMENTS.md Phase 3.6) after a training run and persists it as a JSON
artifact alongside the model files — NOT a DB row (training-artifact pattern,
ADR-002 layering: file I/O is acceptable in core for training artifacts, same
as model .zip files).

5 Functional Parameters (trading outcomes, computed on the TEST set):
    F1  Sharpe Ratio (Test)
    F2  Max Drawdown (Test)
    F3  Market Regime Performance — per-regime Sharpe
    F4  Win Rate — % of positive daily returns
    F5  Baseline Relative Performance — (RL - static) / |static|, overall + per regime

5 Technical Parameters (model tuning diagnostics):
    T1  Action Entropy — Shannon entropy of the action distribution
    T2  Train-Test Sharpe Gap — (train - test) / |train|
    T3  Reward Convergence Rate — % of episodes to reach 90% of final reward
    T4  Seed Consistency — coefficient of variation of Sharpe across seeds
    T5  Per-Regime Action Distribution — action frequency per regime + JSD

All functions are pure computation over already-loaded DataFrames / dicts
(no DB/file I/O except ``save_scorecard`` writing the final JSON artifact).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import structlog

from rita.core.instrument_config import DEFAULT_ENV_CONFIG, InstrumentEnvConfig
from rita.core.market_regime import REGIME_BEAR, REGIME_BULL, REGIME_SIDEWAYS, classify_regimes
from rita.core.performance import sharpe_ratio
from rita.core.trading_env_v2 import run_episode_v2, run_static_baseline_v2

log = structlog.get_logger(__name__)

_REGIMES = (REGIME_BULL, REGIME_BEAR, REGIME_SIDEWAYS)
_ACTION_NAMES = ("cash", "half", "full", "hedged")
# (allocation, hedged) -> action id — inverse of trading_env_v2._ACTION_MAP.
_ALLOC_TO_ACTION = {(0.0, 0.0): 0, (0.5, 0.0): 1, (1.0, 0.0): 2, (1.0, 1.0): 3}

_DIVZERO_FLOOR = 1e-6
_MIN_REGIME_SAMPLES = 5   # below this, a regime bucket is "no_data" (edge case 8)
_JSD_REGIME_BLIND_THRESHOLD = 0.05


# ── Small numeric helpers ──────────────────────────────────────────────────────

def _safe_ratio(numerator: float, denominator: float) -> float:
    """numerator / max(|denominator|, floor) — avoids divide-by-zero (edge cases 4/5)."""
    return float(numerator / max(abs(denominator), _DIVZERO_FLOOR))


def _shannon_entropy(counts: dict[int, int]) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    ent = 0.0
    for c in counts.values():
        if c == 0:
            continue
        p = c / total
        ent -= p * math.log2(p)
    return float(ent)


def _jensen_shannon_divergence(p: np.ndarray, q: np.ndarray) -> float:
    """JSD in bits (log2), bounded [0, 1]. Symmetric, well-behaved (design decision 6)."""
    p = np.asarray(p, dtype=float)
    q = np.asarray(q, dtype=float)
    if p.sum() == 0 or q.sum() == 0:
        return 0.0
    p = p / p.sum()
    q = q / q.sum()
    m = 0.5 * (p + q)

    def _kl(a: np.ndarray, b: np.ndarray) -> float:
        mask = a > 0
        return float(np.sum(a[mask] * np.log2(a[mask] / b[mask])))

    return float(0.5 * _kl(p, m) + 0.5 * _kl(q, m))


def _action_from_alloc(allocation: float, hedged: float) -> int:
    key = (round(float(allocation), 4), round(float(hedged), 4))
    return _ALLOC_TO_ACTION.get(key, 2)  # default to "full" if an unseen combo appears


def _regime_labels_for_episode(regime_df: pd.DataFrame, episode_result: dict) -> list[str]:
    """Map each step of an episode result to the market regime of the day the
    step's return was realized (i.e. the NEXT bar — matches env causal alignment)."""
    regime_map = regime_df["market_regime"].to_dict()
    dates = list(episode_result["dates"])
    # step i earns the return dated dates[i+1]; there are len(dates)-1 steps.
    return [regime_map.get(dates[i + 1], REGIME_SIDEWAYS) for i in range(len(dates) - 1)]


def _sharpe_or_insufficient(returns: list[float]) -> tuple[float | None, str | None]:
    if len(returns) < _MIN_REGIME_SAMPLES:
        return None, "insufficient_data"
    return round(sharpe_ratio(np.array(returns)), 3), None


# ── F1 / F2 — Sharpe + MDD on test ─────────────────────────────────────────────

def _compute_f1_f2(test_perf: dict) -> dict[str, Any]:
    sharpe = float(test_perf.get("sharpe_ratio", 0.0))
    mdd = float(test_perf.get("max_drawdown_pct", 0.0)) / 100.0
    return {
        "F1_sharpe_test": {
            "value": round(sharpe, 3),
            "healthy": sharpe > 1.0,
            "threshold": "> 1.0",
        },
        "F2_max_drawdown_test": {
            "value": round(mdd, 4),
            "healthy": mdd > -0.10,
            "threshold": "> -10%",
        },
    }


# ── F3 — Market Regime Performance (per-regime Sharpe) ─────────────────────────

def _compute_f3(daily_returns: list[float], regimes: list[str]) -> dict[str, Any]:
    per_regime: dict[str, Any] = {}
    for regime in _REGIMES:
        rets = [r for r, g in zip(daily_returns, regimes) if g == regime]
        sharpe, note = _sharpe_or_insufficient(rets)
        per_regime[regime] = {
            "sharpe": sharpe,
            "n_days": len(rets),
            "note": note,
        }
    return {"F3_market_regime_performance": per_regime}


# ── F4 — Win Rate ──────────────────────────────────────────────────────────────

def _compute_f4(daily_returns: list[float]) -> dict[str, Any]:
    arr = np.asarray(daily_returns, dtype=float)
    if len(arr) == 0:
        return {"F4_win_rate": {"value": None, "healthy": False, "note": "insufficient_data"}}
    win_rate = float(np.mean(arr > 0))
    return {
        "F4_win_rate": {
            "value": round(win_rate, 4),
            "healthy": win_rate >= 0.45,
            "threshold": ">= 45%",
        }
    }


# ── F5 — Baseline Relative Performance (overall + per regime) ─────────────────

def _compute_f5(
    rl_returns: list[float],
    rl_regimes: list[str],
    static_returns: list[float],
    static_regimes: list[str],
) -> dict[str, Any]:
    rl_sharpe_overall = sharpe_ratio(np.array(rl_returns)) if rl_returns else 0.0
    static_sharpe_overall = sharpe_ratio(np.array(static_returns)) if static_returns else 0.0
    overall_rel = _safe_ratio(rl_sharpe_overall - static_sharpe_overall, static_sharpe_overall)

    per_regime: dict[str, Any] = {}
    for regime in _REGIMES:
        rl_rets = [r for r, g in zip(rl_returns, rl_regimes) if g == regime]
        st_rets = [r for r, g in zip(static_returns, static_regimes) if g == regime]
        if len(rl_rets) < _MIN_REGIME_SAMPLES or len(st_rets) < _MIN_REGIME_SAMPLES:
            per_regime[regime] = {"relative": None, "note": "insufficient_data"}
            continue
        rl_sh = sharpe_ratio(np.array(rl_rets))
        st_sh = sharpe_ratio(np.array(st_rets))
        per_regime[regime] = {"relative": round(_safe_ratio(rl_sh - st_sh, st_sh), 4), "note": None}

    return {
        "F5_baseline_relative": {
            "overall": round(overall_rel, 4),
            "healthy": overall_rel > 0.0,
            "per_regime": per_regime,
        }
    }


# ── T1 — Action Entropy ────────────────────────────────────────────────────────

def _compute_t1(actions: list[int]) -> dict[str, Any]:
    counts = {a: actions.count(a) for a in range(4)}
    entropy = _shannon_entropy(counts)
    max_entropy = math.log2(4)  # 2.0
    return {
        "T1_action_entropy": {
            "value": round(entropy, 4),
            "max_possible": round(max_entropy, 4),
            "healthy": 0.5 <= entropy <= 1.8,
            "action_counts": {_ACTION_NAMES[a]: c for a, c in counts.items()},
        }
    }


# ── T2 — Train-Test Sharpe Gap ─────────────────────────────────────────────────

def _compute_t2(train_sharpe: float, test_sharpe: float) -> dict[str, Any]:
    gap = _safe_ratio(train_sharpe - test_sharpe, train_sharpe)
    return {
        "T2_train_test_sharpe_gap": {
            "value": round(gap, 4),
            "train_sharpe": round(train_sharpe, 3),
            "test_sharpe": round(test_sharpe, 3),
            "healthy": gap <= 0.3,
            "threshold": "<= 0.3",
        }
    }


# ── T3 — Reward Convergence Rate ───────────────────────────────────────────────

def _compute_t3(episode_metrics: list[dict] | None) -> dict[str, Any]:
    if not episode_metrics or len(episode_metrics) < 2:
        return {
            "T3_reward_convergence_pct": {
                "value": None, "healthy": None, "note": "insufficient_data",
            }
        }
    rewards = [float(e.get("reward", 0.0)) for e in episode_metrics]
    n = len(rewards)
    tail_n = max(1, n // 10)
    final_reward = float(np.mean(rewards[-tail_n:]))
    target_mag = abs(final_reward)
    threshold = 0.9 * target_mag if target_mag > 1e-9 else 1e-9

    convergence_episode = n  # default: never converged within budget
    for i, r in enumerate(rewards):
        reached = (r >= threshold) if final_reward >= 0 else (r <= -threshold)
        if reached:
            convergence_episode = i + 1
            break

    pct_of_total = round(convergence_episode / n * 100, 2)
    return {
        "T3_reward_convergence_pct": {
            "value": pct_of_total,
            "final_reward": round(final_reward, 6),
            "healthy": 20.0 <= pct_of_total <= 80.0,
            "threshold": "20%-80%",
        }
    }


# ── T4 — Seed Consistency (Sharpe CV) ──────────────────────────────────────────

def _compute_t4(seed_results: list[dict] | None) -> dict[str, Any]:
    if not seed_results:
        return {"T4_seed_consistency_cv": {"value": None, "healthy": None, "note": "insufficient_seeds"}}

    sharpes: list[float] = []
    for r in seed_results:
        for key in ("test_sharpe", "val_sharpe", "sharpe"):
            if key in r and r[key] is not None:
                sharpes.append(float(r[key]))
                break

    if len(sharpes) < 2:
        return {"T4_seed_consistency_cv": {"value": None, "healthy": None, "note": "insufficient_seeds"}}

    arr = np.array(sharpes)
    mean = float(arr.mean())
    std = float(arr.std())
    cv = _safe_ratio(std, mean)
    return {
        "T4_seed_consistency_cv": {
            "value": round(cv, 4),
            "n_seeds": len(sharpes),
            "healthy": cv <= 0.5,
            "threshold": "<= 0.5",
        }
    }


# ── T5 — Per-Regime Action Distribution ────────────────────────────────────────

def _compute_t5(actions: list[int], regimes: list[str]) -> dict[str, Any]:
    per_regime_counts: dict[str, dict[int, int] | None] = {}
    per_regime_dist: dict[str, list[float] | None] = {}
    for regime in _REGIMES:
        acts = [a for a, g in zip(actions, regimes) if g == regime]
        if len(acts) < _MIN_REGIME_SAMPLES:
            per_regime_counts[regime] = None
            per_regime_dist[regime] = None
            continue
        counts = {a: acts.count(a) for a in range(4)}
        per_regime_counts[regime] = counts
        total = sum(counts.values())
        per_regime_dist[regime] = [counts[a] / total for a in range(4)]

    # Pairwise JSD across regimes that HAVE data.
    available = [r for r in _REGIMES if per_regime_dist[r] is not None]
    jsd_pairs: dict[str, float] = {}
    for i in range(len(available)):
        for j in range(i + 1, len(available)):
            r1, r2 = available[i], available[j]
            jsd = _jensen_shannon_divergence(
                np.array(per_regime_dist[r1]), np.array(per_regime_dist[r2])
            )
            jsd_pairs[f"{r1}_vs_{r2}"] = round(jsd, 4)

    regime_blind = bool(jsd_pairs) and all(v < _JSD_REGIME_BLIND_THRESHOLD for v in jsd_pairs.values())

    return {
        "T5_per_regime_action_distribution": {
            "action_counts": {
                r: ({_ACTION_NAMES[a]: c for a, c in cnt.items()} if cnt is not None else None)
                for r, cnt in per_regime_counts.items()
            },
            "jsd_pairs": jsd_pairs,
            "regime_blind": regime_blind if jsd_pairs else None,
            "threshold": "JSD < 0.05 => regime-blind",
        }
    }


# ── Top-level: compute_scorecard ───────────────────────────────────────────────

def compute_scorecard(
    model: Any,
    test_df: pd.DataFrame,
    train_df: pd.DataFrame,
    episode_metrics: list[dict] | None = None,
    seed_results: list[dict] | None = None,
    env_config: InstrumentEnvConfig | None = None,
    instrument: str = "UNKNOWN",
    run_id: str = "run",
    risk_tolerance: str = "medium",
    window: int = 20,
) -> dict[str, Any]:
    """Compute all 10 RL diagnostic parameters (5 Functional + 5 Technical).

    Args:
        model: trained (or stub, for tests) policy exposing ``.predict()`` and
            ``.observation_space`` — same contract as ``run_episode_v2``.
        test_df: held-out test-set OHLCV+indicators DataFrame (F1-F5 basis).
        train_df: training-set OHLCV+indicators DataFrame (T2 basis).
        episode_metrics: per-episode training reward records (T3 basis);
            ``None``/empty -> T3 reported as insufficient_data.
        seed_results: per-seed result dicts from ``train_best_of_n_v2``
            (T4 basis); ``None``/single-seed -> T4 reported as insufficient_seeds.
        env_config: the SAME config used to train/eval ``model`` — train/eval
            consistency (skill rule #3). ``None`` -> DEFAULT_ENV_CONFIG.
        instrument, run_id: labels persisted into the scorecard (and used by
            ``save_scorecard`` for the output filename).
        risk_tolerance: tolerance level used for evaluation episodes.
        window: market-regime classification window (default 20, matches
            REQUIREMENTS.md Phase 3.6).

    Returns:
        A JSON-serialisable dict with ``functional`` (F1-F5) and ``technical``
        (T1-T5) sections plus metadata.
    """
    cfg = env_config or DEFAULT_ENV_CONFIG
    config_source = "default" if cfg is DEFAULT_ENV_CONFIG else "instrument"

    regime_df = classify_regimes(test_df, window=window)

    test_result = run_episode_v2(model, test_df, risk_tolerance=risk_tolerance, env_config=cfg)
    train_result = run_episode_v2(model, train_df, risk_tolerance=risk_tolerance, env_config=cfg)
    static_result = run_static_baseline_v2(test_df, risk_tolerance=risk_tolerance, env_config=cfg)

    test_regimes = _regime_labels_for_episode(regime_df, test_result)
    static_regimes = _regime_labels_for_episode(regime_df, static_result)

    test_daily_returns = list(test_result["daily_returns"])
    static_daily_returns = list(static_result["daily_returns"])

    actions = [
        _action_from_alloc(a, h)
        for a, h in zip(test_result["allocations"], test_result["hedge_flags"])
    ]

    test_sharpe = float(test_result["performance"].get("sharpe_ratio", 0.0))
    train_sharpe = float(train_result["performance"].get("sharpe_ratio", 0.0))

    functional: dict[str, Any] = {}
    functional.update(_compute_f1_f2(test_result["performance"]))
    functional.update(_compute_f3(test_daily_returns, test_regimes))
    functional.update(_compute_f4(test_daily_returns))
    functional.update(_compute_f5(test_daily_returns, test_regimes, static_daily_returns, static_regimes))

    technical: dict[str, Any] = {}
    technical.update(_compute_t1(actions))
    technical.update(_compute_t2(train_sharpe, test_sharpe))
    technical.update(_compute_t3(episode_metrics))
    technical.update(_compute_t4(seed_results))
    technical.update(_compute_t5(actions, test_regimes))

    scorecard = {
        "instrument": instrument,
        "run_id": run_id,
        "config_source": config_source,
        "regime_window": window,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "functional": functional,
        "technical": technical,
    }
    log.info(
        "rl_scorecard.computed", instrument=instrument, run_id=run_id,
        sharpe_test=round(test_sharpe, 3),
    )
    return scorecard


# ── JSON persistence ────────────────────────────────────────────────────────────

def _json_safe(obj: Any) -> Any:
    """Recursively replace NaN/Inf floats with None so json.dumps never emits
    invalid JSON tokens (edge case 3), and coerce numpy scalars to native types."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def save_scorecard(scorecard: dict[str, Any], output_dir: str, instrument: str, run_id: str) -> str:
    """Persist ``scorecard`` as JSON at
    ``{output_dir}/{instrument}/scorecard_{run_id}_{timestamp}.json``.

    Training-artifact pattern (like the model .zip) — file I/O here in core is
    the accepted exception to ADR-002 (routes/services never touch files/DB
    directly; this mirrors model persistence, not request-serving I/O).

    Returns the written file path (str).
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    instrument_dir = Path(output_dir) / instrument.upper()
    instrument_dir.mkdir(parents=True, exist_ok=True)
    file_path = instrument_dir / f"scorecard_{run_id}_{timestamp}.json"

    with file_path.open("w") as fh:
        json.dump(_json_safe(scorecard), fh, indent=2, sort_keys=True)

    log.info("rl_scorecard.saved", path=str(file_path), instrument=instrument, run_id=run_id)
    return str(file_path)
