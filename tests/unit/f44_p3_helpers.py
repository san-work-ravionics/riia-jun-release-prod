"""Shared synthetic data, a deterministic stand-in DDQN policy and a fake artifact repository
for the F44 P3 unit tests (no model zips, no CSVs, no network)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rita.config import ModelLineage
from rita.core.goal_model_runs import LineageSplit, ModelRun
from rita.repositories.model_artifact import IndicatorFrame

SPLIT = LineageSplit(date(2022, 12, 31), date(2023, 1, 1), date(2024, 12, 31), date(2025, 1, 1))
LINEAGE = ModelLineage(name="f34p25", engine="ddqn_v2", pattern="rita_ddqn_v2_{inst}_f34p25.zip",
                       source="", train_end=SPLIT.train_end, val_start=SPLIT.val_start,
                       val_end=SPLIT.val_end, backtest_start=SPLIT.backtest_start)


def indicator_frame(seed: int = 0, start: str = "2021-01-01", end: str = "2026-06-30",
                    drift: float = 0.0004, vol: float = 0.01, with_ema: bool = True,
                    freq: str = "B") -> pd.DataFrame:
    """Indicator-complete frame with a seeded random walk (all features finite)."""
    idx = pd.date_range(start, end, freq=freq)
    rng = np.random.default_rng(seed)
    # calmer after train_end, so only an injected jump trips the data-integrity rule
    scale = np.where(idx <= pd.Timestamp(SPLIT.train_end), 1.0, 0.6)
    r = drift + rng.normal(0.0, vol, len(idx)) * scale
    close = 100.0 * np.cumprod(1.0 + r)
    n = len(idx)
    data = {
        "Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close,
        "Volume": np.full(n, 1000.0),
        "daily_return": r,
        "rsi_14": 50 + 20 * np.sin(np.arange(n) / 9.0),
        "macd": np.sin(np.arange(n) / 13.0),
        "macd_signal": np.cos(np.arange(n) / 13.0),
        "bb_pct_b": 0.5 + 0.4 * np.sin(np.arange(n) / 7.0),
        "trend_score": np.tanh(np.sin(np.arange(n) / 17.0)),
        "atr_14": close * 0.02,
    }
    if with_ema:
        data["ema_ratio"] = 1.0 + 0.02 * np.sin(np.arange(n) / 11.0)
    return pd.DataFrame(data, index=idx)


class _Space:
    def __init__(self, shape=None, n=None):
        self.shape = shape
        self.n = n


class PolicyModel:
    """Deterministic stand-in for a DDQN v2 policy: the action depends on yesterday's return,
    the allocation it holds and (optionally) the tolerance feature. Records every observation."""

    def __init__(self, n_obs: int = 14, tol_sensitive: bool = True, n_actions: int = 4):
        self.observation_space = _Space(shape=(n_obs,))
        self.action_space = _Space(n=n_actions)
        self.tol_sensitive = tol_sensitive
        self.calls: list[np.ndarray] = []

    def predict(self, obs, deterministic=True):
        obs = np.asarray(obs, dtype=np.float32)
        self.calls.append(obs.copy())
        score = float(obs[0]) + (float(obs[-1]) - 0.6 if self.tol_sensitive else 0.0) * 0.2
        if score > 0.05:
            a = 2
        elif score > 0.0:
            a = 3
        elif score > -0.08:
            a = 1
        else:
            a = 0
        return np.array(a), None


def fixed_run(instrument: str, returns: list[float] | np.ndarray, dates: list[date] | pd.DatetimeIndex,
              tolerance: str = "medium", tolerance_mdd: float = -0.15, rf_daily: float = 0.0,
              today_action: str = "full") -> ModelRun:
    """A ModelRun with given sleeve returns (selection tests)."""
    ds = [pd.Timestamp(d).date() for d in dates]
    return ModelRun(
        instrument=instrument, lineage="f34p25", model_sha12="abc123def456", tolerance=tolerance,
        tolerance_mdd=tolerance_mdd, episode_length=252, rf_daily=rf_daily, hard_mdd_limit=-0.10,
        window_start=ds[0], as_of=ds[-1], dates=ds, daily_returns=[float(x) for x in returns],
        allocations=[1.0] * len(ds), hedge_flags=[0.0] * len(ds), episode_starts=[ds[0]],
        oob_bars=0, today_action=today_action, episode_start=ds[0], episode_day=len(ds) % 252,
    )


@dataclass
class FakeArtifacts:
    """In-memory ``ModelArtifactRepository`` stand-in."""

    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    models: dict[str, Any] = field(default_factory=dict)       # inst → model (or Exception)
    markers: dict[str, dict] = field(default_factory=dict)
    loads: list[str] = field(default_factory=list)
    split: LineageSplit = SPLIT

    def find(self, instrument, lineage):
        return Path(f"/fake/{instrument}.zip") if instrument in self.models else None

    def sha256(self, path):
        return "f" * 52 + path.stem.lower().ljust(12, "0")[:12]

    def load(self, path):
        inst = path.stem
        self.loads.append(inst)
        m = self.models[inst]
        if isinstance(m, Exception):
            raise m
        return m

    def lineage_split(self, lineage):
        return self.split

    def load_indicator_frame(self, instrument):
        df = self.frames.get(instrument)
        if df is None:
            return None
        h = str(pd.util.hash_pandas_object(df, index=True).sum())
        return IndicatorFrame(df=df, data_hash=h, last_date=df.index[-1].date())

    def rewrite_marker(self, instrument):
        return self.markers.get(instrument)
