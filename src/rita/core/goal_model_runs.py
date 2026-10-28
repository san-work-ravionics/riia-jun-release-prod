"""RITA Core — DDQN v2 model replay for goal-driven selection (F44 P3, design 2 rev 1–3).

Each location instrument's own lineage policy (e.g. ``rita_ddqn_v2_<inst>_f34p25.zip``) is run
over the bars after the lineage's ``train_end`` at every trained risk tolerance τ.  The output is
a model-managed daily return stream (the instrument "sleeve") plus the model's action today.

Train/eval alignment (Revision 1 A3, R2-2, N7):
- consecutive episodes of the instrument's training ``episode_length`` L, anchored at the first
  bar after ``train_end``; each episode resets value / peak / allocation / hedge / DSR moments as
  ``RIIATradingEnvV2.reset()`` does, and ``days_remaining = 1 − step/L`` as in training;
- each step's return is clipped to ±1 like ``RIIATradingEnvV2.step``;
- no termination at ``hard_mdd_limit`` (matches the lineage's own eval); the bars after a breach
  inside an episode are outside the training distribution and are counted as ``oob_bars``;
- today's action comes from ``run_episode_v2(..., predict_last=True)`` on the episode that
  contains today (a new 1-bar episode when today is an episode boundary).

``run_episode_v2`` is reused; no env logic is duplicated.  Pure: no file I/O (the repository
loads models and data).
"""
from __future__ import annotations

import ast
import hashlib
import json
import warnings
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from rita.core.instrument_config import InstrumentEnvConfig
from rita.core.trading_env_v2 import _STRUCTURAL_BASE_COLS, _ema_ratio_enabled, run_episode_v2

TOLERANCE_LEVELS: tuple[str, ...] = ("low", "medium", "high")
# Part of the replay cache key: bump when the replay/metrics code changes, so a deploy never
# serves runs computed by older code (the prod cache dir survives redeploys).
REPLAY_VERSION = "p3-2"
ACTION_NAMES = {0: "cash", 1: "half", 2: "full", 3: "hedged"}
ACTION_ALLOCATION = {"cash": 0.0, "half": 0.5, "full": 1.0, "hedged": 1.0}

# Names in the lineage training script that carry the split (AST-parsed, never imported).
_SPLIT_NAMES = ("TRAIN_END", "VAL_START", "VAL_END", "BACKTEST_START")


# ── lineage split ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LineageSplit:
    """The windows a lineage was trained / reported on (all dates inclusive)."""

    train_end: date
    val_start: date
    val_end: date
    backtest_start: date

    def split_hash(self) -> str:
        raw = "|".join(d.isoformat() for d in
                       (self.train_end, self.val_start, self.val_end, self.backtest_start))
        return hashlib.sha256(raw.encode()).hexdigest()


def parse_lineage_split(source: str) -> LineageSplit:
    """Parse ``TRAIN_END``, ``VAL_START``, ``VAL_END``, ``BACKTEST_START`` from a training
    script's source with ``ast`` (the script is never executed).  Handles plain assignments and
    tuple assignments (``VAL_START, VAL_END = "…", "…"``).  ``ValueError`` if one is missing."""
    found: dict[str, str] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                found[target.id] = node.value.value
            elif isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple):
                for t, v in zip(target.elts, node.value.elts):
                    if isinstance(t, ast.Name) and isinstance(v, ast.Constant):
                        found[t.id] = v.value
    missing = [n for n in _SPLIT_NAMES if not isinstance(found.get(n), str)]
    if missing:
        raise ValueError(f"lineage script is missing {missing}")
    d = {n: date.fromisoformat(found[n]) for n in _SPLIT_NAMES}
    return LineageSplit(train_end=d["TRAIN_END"], val_start=d["VAL_START"],
                        val_end=d["VAL_END"], backtest_start=d["BACKTEST_START"])


def env_config_hash(env_config: InstrumentEnvConfig) -> str:
    return hashlib.sha256(env_config.model_dump_json().encode()).hexdigest()


# ── model run ──────────────────────────────────────────────────────────────────

@dataclass
class ModelRun:
    """One instrument × one τ replay over the bars after ``train_end``.

    ``dates[k]`` is the bar whose return is ``daily_returns[k]``; ``allocations[k]`` /
    ``hedge_flags[k]`` are what the model held over that bar (chosen at the previous close).
    """

    instrument: str
    lineage: str
    model_sha12: str
    tolerance: str
    tolerance_mdd: float
    episode_length: int
    rf_daily: float
    hard_mdd_limit: float
    window_start: date                 # first bar after train_end (episode 1 anchor)
    as_of: date                        # last bar (today)
    dates: list[date] = field(default_factory=list)
    daily_returns: list[float] = field(default_factory=list)
    allocations: list[float] = field(default_factory=list)
    hedge_flags: list[float] = field(default_factory=list)
    episode_starts: list[date] = field(default_factory=list)
    oob_bars: int = 0
    today_action: str = "cash"
    episode_start: date | None = None  # anchor of the episode that contains today
    episode_day: int = 0               # today's step inside that episode (0 = first bar)

    @property
    def today_allocation(self) -> float:
        return ACTION_ALLOCATION[self.today_action]

    @property
    def today_hedged(self) -> bool:
        return self.today_action == "hedged"

    def returns_series(self) -> pd.Series:
        return pd.Series(self.daily_returns, index=pd.DatetimeIndex(self.dates), dtype=float)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("window_start", "as_of", "episode_start"):
            d[k] = d[k].isoformat() if d[k] is not None else None
        d["dates"] = [x.isoformat() for x in self.dates]
        d["episode_starts"] = [x.isoformat() for x in self.episode_starts]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ModelRun":
        d = dict(d)
        for k in ("window_start", "as_of", "episode_start"):
            d[k] = date.fromisoformat(d[k]) if d.get(k) else None
        d["dates"] = [date.fromisoformat(x) for x in d["dates"]]
        d["episode_starts"] = [date.fromisoformat(x) for x in d["episode_starts"]]
        return cls(**d)

    def fingerprint(self) -> str:
        """Content hash (determinism tests)."""
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()


def required_columns(df: pd.DataFrame, env_config: InstrumentEnvConfig, n_obs: int) -> list[str]:
    """Indicator columns the observation reads — the same rule as ``run_episode_v2``."""
    cols = list(_STRUCTURAL_BASE_COLS)
    if n_obs >= 14 and _ema_ratio_enabled(df, env_config):
        cols.append("ema_ratio")
    return cols


def check_compat(model: Any, df: pd.DataFrame, env_config: InstrumentEnvConfig) -> str | None:
    """``None`` when the model fits the env config + data, else ``"feature_mismatch"``.

    The model must have 4 actions and the observation width the env would build from this
    config and data (13 without ``ema_ratio``, 14 with it).
    """
    try:
        n_actions = int(model.action_space.n)
        n_obs = int(model.observation_space.shape[0])
    except (AttributeError, TypeError, IndexError):
        return "feature_mismatch"
    expected = 14 if _ema_ratio_enabled(df, env_config) else 13
    if n_actions != 4 or n_obs != expected:
        return "feature_mismatch"
    return None


def window_frame(df: pd.DataFrame, train_end: date) -> pd.DataFrame:
    """The model's own unseen bars: everything strictly after ``train_end``."""
    return df[df.index > pd.Timestamp(train_end)]


def check_bad_data(window: pd.DataFrame, columns: list[str]) -> str | None:
    """``None`` or a short detail when a window bar has a missing / non-finite indicator, or a
    non-positive close (rows that ``run_episode_v2`` would silently drop)."""
    if window.empty:
        return "empty window"
    sub = window[columns]
    arr = sub.to_numpy(dtype=float)
    bad_rows = ~np.isfinite(arr).all(axis=1)
    if bad_rows.any():
        first = window.index[bad_rows.argmax()].date().isoformat()
        return f"{int(bad_rows.sum())} bar(s) with missing / non-finite features (first {first})"
    if (window["Close"] <= 0).any():
        return "non-positive close"
    return None


def _episode_oob(values: list[float], hard_mdd_limit: float) -> int:
    """Bars after the first breach of ``hard_mdd_limit`` inside one episode (training would have
    terminated there)."""
    peak = values[0]
    for k in range(1, len(values)):
        peak = max(peak, values[k])
        if (values[k] - peak) / peak <= hard_mdd_limit:
            return len(values) - 1 - k
    return 0


def run_policy(
    model: Any,
    df_full: pd.DataFrame,
    env_config: InstrumentEnvConfig,
    split: LineageSplit,
    tolerance: str,
    *,
    instrument: str,
    lineage: str,
    model_sha12: str,
) -> ModelRun:
    """Replay ``model`` at ``tolerance`` over the bars after ``split.train_end`` in consecutive
    training-length episodes; the caller has already validated the window (``check_bad_data``,
    ``check_compat``, integrity)."""
    if tolerance not in TOLERANCE_LEVELS:
        raise ValueError(f"unknown tolerance {tolerance!r}")
    data = window_frame(df_full, split.train_end)
    n = len(data)
    if n < 2:
        raise ValueError("window has fewer than 2 bars")
    L = int(env_config.episode_length)
    run = ModelRun(
        instrument=instrument, lineage=lineage, model_sha12=model_sha12, tolerance=tolerance,
        tolerance_mdd=float(env_config.risk_tolerance_mdd[tolerance]), episode_length=L,
        rf_daily=float(env_config.rf_daily), hard_mdd_limit=float(env_config.hard_mdd_limit),
        window_start=data.index[0].date(), as_of=data.index[-1].date(),
    )
    a = 0
    while a < n - 1:
        end = min(a + L, n - 1)
        frame = data.iloc[a:end + 1]
        today_inside = end == n - 1 and (end - a) < L
        res = run_episode_v2(model, frame, risk_tolerance=tolerance, env_config=env_config,
                             days_denominator=L, predict_last=today_inside, clip_step_return=True)
        run.episode_starts.append(frame.index[0].date())
        run.dates.extend(ts.date() for ts in res["dates"][1:])
        run.daily_returns.extend(float(x) for x in res["daily_returns"])
        run.allocations.extend(float(x) for x in res["allocations"])
        run.hedge_flags.extend(float(x) for x in res["hedge_flags"])
        run.oob_bars += _episode_oob(res["portfolio_values"], env_config.hard_mdd_limit)
        if today_inside:
            run.today_action = ACTION_NAMES[int(res["last_action"])]
            run.episode_start = frame.index[0].date()
            run.episode_day = len(frame) - 1
        a = end
    if run.episode_start is None:
        # Today closes a full episode: it is the first bar of a new one (fresh state, step 0).
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # 1-bar metrics (std of nothing)
            res = run_episode_v2(model, data.iloc[n - 1:n], risk_tolerance=tolerance,
                                 env_config=env_config, days_denominator=L, predict_last=True,
                                 clip_step_return=True)
        run.today_action = ACTION_NAMES[int(res["last_action"])]
        run.episode_start = data.index[n - 1].date()
        run.episode_starts.append(run.episode_start)
        run.episode_day = 0
    return run
