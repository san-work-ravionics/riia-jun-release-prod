"""F44 P4 — the ASTA engine (AstaTraceService; rev 1 B5, rev 2 N3).

- the window is derived at runtime with ``temporal_split`` (no date in config);
- parity with the training record → ``ok`` (live replay from test_start, return_since);
- a mismatch / no record → ``no_recorded_window`` (signals only, no return);
- requests read the cache only: cold → ``warming`` + one background rebuild;
- slow: the real NIFTY model + dataset reproduce the recorded run (training_history.csv).
"""
# ruff: noqa: F811 — pytest fixtures imported from a sibling module are redefined as test params
from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

import rita.core.asta_indicators as ind_mod
import rita.core.asta_labeler as lab_mod
import rita.services.asta_trace_service as svc_mod
from rita.core.asta_trading_env import run_episode_asta
from rita.core.instrument_config import DEFAULT_ENV_CONFIG
from rita.core.trading_env_v2 import temporal_split
from rita.models.training import TrainingRunModel
from rita.repositories.asta_artifact import AstaArtifactRepository
from rita.repositories.model_run_cache import ModelRunCacheRepository
from rita.services.asta_trace_service import AstaTraceService, derive_window, parity_ok

from .f44_p4_helpers import journey_db  # noqa: F401 — fixture
from .test_f44_p4_rationale_parity import _asta_frame, _AstaPolicy

ROOT = Path(__file__).resolve().parents[2]
RUN = "abcd1234-0000-0000-0000-000000000000"


def test_asta_window_derived_from_dataset():
    text = (ROOT / "config" / "base.yaml").read_text(encoding="utf-8")
    block = text.split("\njarvis:", 1)[1]
    block = block.split("\n\n", 1)[0] if "\n\n" in block else block
    assert not re.search(r"\d{4}-\d{2}-\d{2}", block), "no typed ASTA date in config"
    from rita.config import get_settings
    a = get_settings().jarvis.asta
    assert a.model_pattern == "rita_ddqn_asta_{inst}_*.zip" and a.dataset == "asta_labeled_dataset.csv"
    assert not hasattr(a, "window_start") and not hasattr(a, "lineage")
    df = _asta_frame()
    _tr, _va, te = temporal_split(df)
    assert derive_window(df) == (te.index[0].date(), te.index[-1].date())


class FakeAsta:
    def __init__(self, tmp: Path, dataset: pd.DataFrame | None, raw: pd.DataFrame, model):
        (tmp / "m").mkdir()
        self.path = tmp / "m" / "rita_ddqn_asta_nifty_abcd1234.zip"
        self.path.write_bytes(b"zip")
        self.dataset, self.raw, self.model = dataset, raw, model

    def instruments_with_models(self):
        return ["NIFTY"]

    def model_files(self, inst):
        return [self.path] if inst == "NIFTY" else []

    @staticmethod
    def sha256(path):
        return "a" * 64

    def load_model(self, path):
        return self.model

    def load_dataset(self, inst):
        return None if self.dataset is None else (self.dataset, "d" * 64)

    def load_ohlcv(self, inst):
        return self.raw, "r" * 64


@pytest.fixture
def asta_env(journey_db, tmp_path, monkeypatch):
    frame = _asta_frame(seed=4)
    monkeypatch.setattr(ind_mod, "compute_asta_indicators", lambda raw: raw)   # the frame is already labelled
    monkeypatch.setattr(lab_mod, "label_asta_signals", lambda df: df)
    monkeypatch.setattr("rita.core.instrument_config.load_instrument_env_config", lambda inst: DEFAULT_ENV_CONFIG)
    cache = ModelRunCacheRepository(tmp_path / "cache")
    return journey_db, frame, cache, tmp_path


def _record(db, perf: dict | None, **over):
    p = perf or {}
    db.add(TrainingRunModel(
        run_id=RUN, instrument="NIFTY", model_version="rita_ddqn_asta_nifty", timesteps=1, learning_rate=1e-4,
        buffer_size=1, net_arch="[]", exploration_pct=0.1, status="complete", recorded_at=datetime(2026, 8, 30),
        backtest_sharpe=over.get("sharpe", p.get("sharpe_ratio")),
        backtest_mdd=over.get("mdd", p.get("max_drawdown_pct", 0) / 100.0),
        backtest_return=over.get("ret", p.get("portfolio_total_return_pct", 0) / 100.0),
        backtest_trades=over.get("trades", p.get("total_trades"))))
    db.commit()


def _test_perf(frame, model):
    start, _end = derive_window(frame)
    return run_episode_asta(model, frame[frame.index >= pd.Timestamp(start)], env_config=DEFAULT_ENV_CONFIG)["performance"]


def test_asta_parity_ok_gives_a_live_trace(asta_env):
    db, frame, cache, tmp = asta_env
    model = _AstaPolicy(21)
    _record(db, _test_perf(frame, _AstaPolicy(21)))
    svc = AstaTraceService(db, artifacts=FakeAsta(tmp, frame, frame, model), cache=cache)
    p = svc.build("NIFTY")
    assert p["status"] == "ok" and p["window"]["verified"] is True
    assert p["window"]["test_start"] == derive_window(frame)[0].isoformat()
    assert "replay matches training run abcd1234" in p["window"]["basis"]
    out = svc.trace("NIFTY", since=date(2026, 3, 2), detail=True)
    assert out.status == "ok" and out.return_since is not None and out.since <= date(2026, 3, 2)
    assert out.today_action in ("cash", "half", "full", "hedged") and out.live_replay_note
    assert out.training_record.run_id == RUN and out.detail.markers and out.detail.rationale is not None
    assert out.method.sl_target.endswith("(rule engine, not a model)")
    # the cached build is reused (same content key) — no second replay
    model.calls.clear()
    svc.build("NIFTY")
    assert model.calls == []


def test_asta_no_recorded_window_on_mismatch(asta_env):
    db, frame, cache, tmp = asta_env
    perf = _test_perf(frame, _AstaPolicy(21))
    _record(db, perf, trades=int(perf["total_trades"]) + 1)          # one trade off → no parity
    svc = AstaTraceService(db, artifacts=FakeAsta(tmp, frame, frame, _AstaPolicy(21)), cache=cache)
    p = svc.build("NIFTY")
    assert p["status"] == "no_recorded_window" and p["window"]["verified"] is False
    assert "does not match" in p["window"]["basis"]
    out = svc.trace("NIFTY", detail=True)
    assert out.status == "no_recorded_window" and out.return_since is None and out.today_action is None
    last = pd.Timestamp(frame.index[-1])
    assert all(pd.Timestamp(s.date) >= last - pd.Timedelta(days=12 * 31) for s in out.detail.signals)
    assert out.detail.markers == []


def test_asta_without_record_or_dataset_is_not_verified(asta_env):
    db, frame, cache, tmp = asta_env
    p = AstaTraceService(db, artifacts=FakeAsta(tmp, None, frame, _AstaPolicy(21)), cache=cache).build("NIFTY")
    assert p["status"] == "no_recorded_window" and p["window"]["basis"] == "training dataset missing"


def test_parity_rule_to_3dp_and_exact_trades():
    class R:
        backtest_sharpe, backtest_mdd, backtest_return, backtest_trades = -0.156, -0.0996, 0.2294, 340
    perf = {"sharpe_ratio": -0.156, "max_drawdown_pct": -9.96, "portfolio_total_return_pct": 22.94, "total_trades": 340}
    assert parity_ok(perf, R())
    assert not parity_ok({**perf, "total_trades": 339}, R())
    assert not parity_ok({**perf, "sharpe_ratio": -0.158}, R())


def test_cold_cache_is_warming_and_starts_one_rebuild(asta_env, monkeypatch):
    db, frame, cache, tmp = asta_env
    started = []
    monkeypatch.setattr(svc_mod, "start_rebuild", lambda inst: started.append(inst) or True)
    out = AstaTraceService(db, artifacts=FakeAsta(tmp, frame, frame, _AstaPolicy(21)), cache=cache).trace("NIFTY")
    assert out.status == "warming" and started == ["NIFTY"]


def test_no_model_for_other_instruments(asta_env):
    db, frame, cache, tmp = asta_env
    out = AstaTraceService(db, artifacts=FakeAsta(tmp, frame, frame, _AstaPolicy(21)), cache=cache).trace("ASML")
    assert out.status == "no_model"


# ── slow: the real model reproduces the recorded run ───────────────────────────

def _recorded_row() -> dict | None:
    path = ROOT / "models" / "NIFTY" / "training_history.csv"
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("notes", "").endswith("run_id=3fc543eb"):
                return row
    return None


@pytest.mark.slow
def test_asta_parity_with_training_record(journey_db, tmp_path):
    repo = AstaArtifactRepository.from_settings()
    row = _recorded_row()
    if not repo.model_files("NIFTY") or repo.load_dataset("NIFTY") is None or row is None:
        pytest.skip("ASTA model / dataset / training history not available")
    journey_db.add(TrainingRunModel(
        run_id="3fc543eb-46e0-4ec3-b223-b3eec911e48c", instrument="NIFTY", model_version="rita_ddqn_asta_nifty",
        timesteps=100000, learning_rate=1e-4, buffer_size=1, net_arch="[]", exploration_pct=0.1, status="complete",
        recorded_at=datetime(2026, 8, 30, 17, 45), backtest_sharpe=float(row["backtest_sharpe"]),
        backtest_mdd=float(row["backtest_mdd_pct"]) / 100.0, backtest_return=float(row["backtest_return_pct"]) / 100.0,
        backtest_trades=int(row["backtest_trade_count"])))
    journey_db.commit()
    svc = AstaTraceService(journey_db, artifacts=repo, cache=ModelRunCacheRepository(tmp_path / "cache"))
    p = svc.build("NIFTY")
    assert p["window"]["verified"] is True, p["window"]
    assert p["status"] == "ok" and p["window"]["test_start"] == "2022-07-25"
    assert p["window"]["test_end"] == "2026-08-28"
