"""RITA Core — the model inputs behind an engine decision (F44 P4 rationale, rev 1 A3).

Recomputes, for one bar, the observation the policy saw — the same arithmetic as
``trading_env_v2.run_episode_v2`` (RITA DDQN v2) and ``asta_trading_env.run_episode_asta``
(ASTA DDQN), replayed from the actions the model took earlier in its episode.  Parity is pinned by
``tests/unit/test_f44_p4_rationale_parity.py`` (the recomputed observation equals the one passed
to ``predict`` on every bar of a replay).  Pure: no I/O, no model call.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from rita.core.instrument_config import InstrumentEnvConfig

ACTION_FROM_ALLOC = {(0.0, 0.0): "cash", (0.5, 0.0): "half", (1.0, 0.0): "full", (1.0, 1.0): "hedged"}

V2_FEATURES = ("daily_return", "rsi_14", "macd_over_close", "bb_pct_b", "trend_score",
               "prev_allocation", "days_remaining", "atr_over_close")


def _tol_norm(mdd_tol: float) -> float:
    return float(np.clip(abs(mdd_tol) / 0.25, 0.0, 1.0))


def action_name(allocation: float, hedged: float) -> str:
    return ACTION_FROM_ALLOC.get((float(allocation), float(hedged)), "full" if allocation > 0 else "cash")


@dataclass
class EpisodeState:
    """The running state at bar ``i`` of an episode (before the action at ``i``)."""

    step: int = 0
    prev_alloc: float = 0.0
    prev_hedged: float = 0.0
    value: float = 1.0
    peak: float = 1.0
    dsr_a: float = 0.0
    dsr_b: float = 0.0
    history: list[float] = field(default_factory=list)

    @property
    def drawdown(self) -> float:
        return (self.value - self.peak) / self.peak


def advance(state: EpisodeState, allocation: float, hedged: float, next_daily_return: float,
            cfg: InstrumentEnvConfig, clip_step_return: bool) -> None:
    """Apply one step exactly as the replay loops do."""
    if hedged:
        port_ret = allocation * max(next_daily_return, cfg.hedge_daily_floor) - cfg.hedge_cost_per_day
    else:
        port_ret = allocation * next_daily_return
    if clip_step_return:
        port_ret = float(np.clip(port_ret, -1.0, 1.0))
    state.value *= 1 + port_ret
    state.peak = max(state.peak, state.value)
    r_t = port_ret - cfg.rf_daily
    state.dsr_a += cfg.dsr_eta * (r_t - state.dsr_a)
    state.dsr_b += cfg.dsr_eta * (r_t ** 2 - state.dsr_b)
    state.prev_alloc = allocation
    state.prev_hedged = 1.0 if hedged else 0.0
    state.step += 1


def _base_obs(row: pd.Series, state: EpisodeState, denom: int, use_ema: bool) -> list[float]:
    obs = [
        float(np.clip(row["daily_return"] * 10, -3, 3)),
        float(np.clip(row["rsi_14"] / 100.0, 0, 1)),
        float(np.clip((row["macd"] / row["Close"]) * 1000, -3, 3)),
        float(np.clip(row["bb_pct_b"], -0.5, 1.5)),
        float(np.clip(row["trend_score"], -1, 1)),
        float(state.prev_alloc),
        float(1.0 - state.step / denom),
        float(np.clip(row["atr_14"] / row["Close"] * 100, 0, 3)),
    ]
    if use_ema:
        obs.append(float(np.clip((row["ema_ratio"] - 1.0) * 20, -3, 3)))
    return obs


def _state_obs(state: EpisodeState, cfg: InstrumentEnvConfig, tol_feat: float) -> list[float]:
    return [
        float(np.clip(state.dsr_a * 100, -3, 3)),
        float(np.clip(state.dsr_b * 1000, 0, 3)),
        float(np.clip(state.drawdown / cfg.hard_mdd_limit, 0, 3)),
        float(state.prev_hedged),
        tol_feat,
    ]


def v2_observation(row: pd.Series, state: EpisodeState, cfg: InstrumentEnvConfig, tolerance: str,
                   denom: int, use_ema: bool) -> np.ndarray:
    """The ``run_episode_v2`` observation at ``row`` for ``state``."""
    mdd_tol = cfg.risk_tolerance_mdd.get(tolerance, cfg.risk_tolerance_mdd["medium"])
    return np.array(_base_obs(row, state, denom, use_ema) + _state_obs(state, cfg, _tol_norm(mdd_tol)),
                    dtype=np.float32)


def v2_episode_observations(frame: pd.DataFrame, allocations: list[float], hedge_flags: list[float],
                            cfg: InstrumentEnvConfig, tolerance: str, denom: int, use_ema: bool,
                            clip_step_return: bool = True) -> list[np.ndarray]:
    """Observation at every bar of one episode ``frame`` (bar 0 … last), given the actions the
    model took (``allocations[k]`` / ``hedge_flags[k]`` = the action at bar k, held over bar k+1).
    The last observation is the ``predict_last`` one."""
    state = EpisodeState()
    out = []
    for i in range(len(frame)):
        out.append(v2_observation(frame.iloc[i], state, cfg, tolerance, denom, use_ema))
        if i < len(frame) - 1 and i < len(allocations):
            advance(state, allocations[i], hedge_flags[i], float(frame.iloc[i + 1]["daily_return"]),
                    cfg, clip_step_return)
    return out


def v2_rationale(row: pd.Series, obs: np.ndarray, tolerance: str, use_ema: bool) -> tuple[list[dict], list[dict]]:
    """``(inputs, state)`` rows for the page: market features with the raw value and the model
    input; the running state the policy also saw."""
    raw = [
        float(row["daily_return"]), float(row["rsi_14"]), float(row["macd"] / row["Close"]),
        float(row["bb_pct_b"]), float(row["trend_score"]),
    ]
    names = ["daily_return", "rsi_14", "macd_over_close", "bb_pct_b", "trend_score"]
    inputs = [{"name": n, "raw": r, "model_input": float(obs[k])} for k, (n, r) in enumerate(zip(names, raw))]
    inputs.append({"name": "atr_over_close", "raw": float(row["atr_14"] / row["Close"]),
                   "model_input": float(obs[7])})
    k = 8
    if use_ema:
        inputs.append({"name": "ema_ratio", "raw": float(row["ema_ratio"]), "model_input": float(obs[8])})
        k = 9
    state = [
        {"name": "prev_allocation", "value": float(obs[5])},
        {"name": "days_remaining", "value": float(obs[6])},
        {"name": "dsr_a", "value": float(obs[k])},
        {"name": "dsr_b", "value": float(obs[k + 1])},
        {"name": "drawdown_vs_limit", "value": float(obs[k + 2])},
        {"name": "hedged", "value": float(obs[k + 3])},
        {"name": "tolerance", "value": float(obs[k + 4])},
        {"name": "tolerance_level", "value": tolerance},
    ]
    return inputs, state


# ── ASTA (20 / 21 features) ────────────────────────────────────────────────────

ASTA_FEATURES = ("asta_signal_enc", "asta_confidence", "stoch_k", "adx", "tide_trend_enc",
                 "bb_squeeze", "vol_ratio")


def asta_observation_at(row: pd.Series, state: EpisodeState, cfg: InstrumentEnvConfig, tolerance: str,
                        denom: int, use_ema: bool) -> np.ndarray:
    """The ``run_episode_asta`` observation at ``row`` (prepared with ``_prepare_asta_columns``)."""
    mdd_tol = cfg.risk_tolerance_mdd.get(tolerance, cfg.risk_tolerance_mdd["medium"])
    obs = _base_obs(row, state, denom, use_ema) + _state_obs(state, cfg, _tol_norm(mdd_tol))
    obs += [
        float(row.get("asta_signal_enc", 0.0)),
        float(np.clip(row.get("asta_confidence", 0.0), 0, 1)),
        float(np.clip(row.get("stoch_k", 50) / 100.0, 0, 1)),
        float(np.clip(row.get("adx", 25) / 100.0, 0, 1)),
        float(row.get("tide_trend_enc", 0.0)),
        float(1.0 if row.get("bb_squeeze") else 0.0),
        float(np.clip(row.get("vol_ratio", 1.0), 0, 3)),
    ]
    return np.array(obs, dtype=np.float32)


def asta_observations(data: pd.DataFrame, allocations: list[float], hedge_flags: list[float],
                      cfg: InstrumentEnvConfig, tolerance: str, use_ema: bool) -> list[np.ndarray]:
    """Observation at every bar of an ASTA replay over ``data`` (already prepared and NaN-free,
    as inside ``run_episode_asta``: ``days_remaining = 1 − i/len(data)``, no step clip).  The last
    one is the observation for today's action (the replay itself does not predict it)."""
    state = EpisodeState()
    denom = len(data)
    out = []
    for i in range(len(data)):
        out.append(asta_observation_at(data.iloc[i], state, cfg, tolerance, denom, use_ema))
        if i < len(data) - 1 and i < len(allocations):
            advance(state, allocations[i], hedge_flags[i], float(data.iloc[i + 1]["daily_return"]),
                    cfg, clip_step_return=False)
    return out


def asta_rationale(row: pd.Series, obs: np.ndarray, use_ema: bool) -> tuple[list[dict], list[dict]]:
    """``(inputs, state)`` for an ASTA decision: market + ASTA features (raw / model input) and
    the labeller state of the bar (rule engine, not a model)."""
    inputs, state = v2_rationale(row, obs[:-7], "medium", use_ema)
    state = [s for s in state if s["name"] != "tolerance_level"]
    raw_vals = {
        "asta_signal_enc": float(row.get("asta_signal_enc", 0.0)),
        "asta_confidence": float(row.get("asta_confidence", 0.0)),
        "stoch_k": float(row.get("stoch_k", 50)),
        "adx": float(row.get("adx", 25)),
        "tide_trend_enc": float(row.get("tide_trend_enc", 0.0)),
        "bb_squeeze": 1.0 if row.get("bb_squeeze") else 0.0,
        "vol_ratio": float(row.get("vol_ratio", 1.0)),
    }
    for k, name in enumerate(ASTA_FEATURES):
        inputs.append({"name": name, "raw": raw_vals[name], "model_input": float(obs[len(obs) - 7 + k])})
    state.append({"name": "asta_signal", "value": str(row.get("asta_signal", "HOLD"))})
    state.append({"name": "asta_setup", "value": str(row.get("asta_setup", "none"))})
    return inputs, state
