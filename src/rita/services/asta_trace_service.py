"""AstaTraceService — the ASTA engine for the Jarvis portfolio page (F44 P4; rev 1 B5, rev 2 N3).

No typed window and no levels in config:
1. the training window is derived at runtime with ``temporal_split`` (70/15/15) on the
   git-tracked training dataset ``asta_labeled_dataset.csv``;
2. the warm-up replays ``run_episode_asta(model, test_df, env_config)`` and must reproduce the
   training record (``training_runs``: Sharpe / MDD / return to 3 dp, trades exact) — parity;
3. the live frame is recomputed (``compute_asta_indicators`` + ``label_asta_signals`` on
   ``load_instrument_data``; the stale dataset is never used after its last row) and must equal
   the dataset frame on the overlapping dates for every observation column (N3);
4. parity + frame ok → ``status ok``: a replay from ``test_start`` to today (entries / exits /
   today's action = ASTA DDQN model output), ``return_since`` and a performance row;
   otherwise ``status no_recorded_window``: labeller signals for the last ``display_months``
   only, no return, no performance.

SL / target are the labeller's setup levels (a rule engine, not a model).  Caveat kept: ASTA's
``days_remaining = 1 − i/len(window)``, so past actions can shift when a bar is added.

Requests read the cache only (``ModelRunCacheRepository``, lineage ``asta_<run>``, τ ``medium``);
a cold or stale cache → ``warming`` / the cached trace and a background rebuild (one at a time,
own ``SessionLocal``).  ADR-002: files via ``AstaArtifactRepository``; the training record via
``TrainingRunsRepository`` / ``BacktestRunsRepository``.
"""
from __future__ import annotations

import hashlib
import threading
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
import structlog
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.core.goal_model_runs import env_config_hash
from rita.core.jarvis_rationale import action_name, asta_observations, asta_rationale
from rita.repositories.asta_artifact import AstaArtifactRepository
from rita.repositories.backtest import BacktestRunsRepository
from rita.repositories.model_run_cache import ModelRunCacheRepository
from rita.repositories.training import TrainingRunsRepository
from rita.schemas.jarvis import AstaTraceOut

log = structlog.get_logger(__name__)

CACHE_TAU = "medium"
REPLAY_TOLERANCE = "medium"      # run_episode_asta's default — the tolerance the record used
FRAME_TOL = 1e-9
OBS_COLUMNS = ("Close", "daily_return", "rsi_14", "macd", "bb_pct_b", "trend_score", "atr_14",
               "ema_ratio", "stoch_k", "adx", "vol_ratio")
_LIVE_NOTE = ("Live actions are a fresh replay from the start of the verified test window on "
              "recomputed indicators, over a longer window than the one verified, so they can "
              "differ from the training replay (days_remaining rescales).")

_rebuild_lock = threading.Lock()
_rebuilding: set[str] = set()


def _model_version(inst: str) -> str:
    return f"rita_ddqn_asta_{inst.lower()}"


def _close3(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and round(float(a), 3) == round(float(b), 3)


def parity_ok(perf: dict, record: Any) -> bool:
    """The replay reproduces the training record: Sharpe / MDD / return to 3 dp, trades exact."""
    return (_close3(perf.get("sharpe_ratio"), record.backtest_sharpe)
            and _close3(float(perf.get("max_drawdown_pct", 0.0)) / 100.0, record.backtest_mdd)
            and _close3(float(perf.get("portfolio_total_return_pct", 0.0)) / 100.0, record.backtest_return)
            and record.backtest_trades is not None
            and int(perf.get("total_trades", -1)) == int(record.backtest_trades))


def derive_window(dataset: pd.DataFrame) -> tuple[date, date]:
    """The test window of the training split, from the dataset (no typed date)."""
    from rita.core.trading_env_v2 import temporal_split

    _tr, _va, te = temporal_split(dataset)
    return te.index[0].date(), te.index[-1].date()


def frame_matches(dataset: pd.DataFrame, fresh: pd.DataFrame, start: date) -> tuple[bool, int, int]:
    """N3: the recomputed frame equals the dataset frame on the overlapping dates ≥ ``start`` for
    every observation column; returns ``(match, overlap_rows, signal_mismatch_rows)``."""
    idx = dataset.index[dataset.index >= pd.Timestamp(start)].intersection(fresh.index)
    if len(idx) == 0:
        return False, 0, 0
    for col in OBS_COLUMNS:
        if col not in dataset.columns or col not in fresh.columns:
            continue
        a = pd.to_numeric(dataset.loc[idx, col], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(fresh.loc[idx, col], errors="coerce").to_numpy(dtype=float)
        both = np.isfinite(a) & np.isfinite(b)
        if (np.isfinite(a) != np.isfinite(b)).any() or (np.abs(a[both] - b[both]) > FRAME_TOL).any():
            return False, len(idx), 0
    mism = int((dataset.loc[idx, "asta_signal"].astype(str) != fresh.loc[idx, "asta_signal"].astype(str)).sum()) \
        if "asta_signal" in dataset.columns and "asta_signal" in fresh.columns else 0
    return True, len(idx), mism


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) and f != 0.0 else None


def _signal_rows(df: pd.DataFrame) -> list[dict]:
    rows = df[df["asta_signal"].isin(["BUY", "SELL"])]
    out = []
    for ts, r in rows.iterrows():
        out.append({
            "date": ts.date().isoformat(), "signal": r["asta_signal"], "setup": str(r.get("asta_setup", "none")),
            "confidence": float(r.get("asta_confidence", 0.0)),
            "mandatory_met": int(r.get("asta_mandatory_met", 0)),
            "mandatory_total": int(r.get("asta_mandatory_total", 0)),
            "optional_met": int(r.get("asta_optional_met", 0)),
            "optional_total": int(r.get("asta_optional_total", 0)),
            "stop_loss": _num(r.get("asta_stop_loss")),
            "target": _num(r.get("asta_target")),
        })
    return out


def _markers(dates: list[str], close: list[float], allocations: list[float], hedged: list[float],
             today: str | None, today_action: str | None) -> list[dict]:
    from rita.services.sleeve_trace_service import marker_kind

    out, prev = [], (0.0, 0.0)
    for k in range(len(allocations)):
        new = (float(allocations[k]), float(hedged[k]))
        kind = marker_kind(prev, new)
        if kind is not None:
            out.append({"date": dates[k], "kind": kind, "close": close[k],
                        "from_action": action_name(*prev), "to_action": action_name(*new)})
        prev = new
    if today_action is not None and today is not None:
        t = (1.0 if today_action in ("full", "hedged") else 0.5 if today_action == "half" else 0.0,
             1.0 if today_action == "hedged" else 0.0)
        kind = marker_kind(prev, t)
        if kind is not None:
            out.append({"date": today, "kind": kind, "close": close[-1],
                        "from_action": action_name(*prev), "to_action": today_action})
    return out


class AstaTraceService:
    def __init__(self, db: Session, artifacts: AstaArtifactRepository | None = None,
                 cache: ModelRunCacheRepository | None = None) -> None:
        self._db = db
        self._artifacts = artifacts or AstaArtifactRepository.from_settings()
        self._cache = cache or ModelRunCacheRepository.from_settings()

    # ── model + record ─────────────────────────────────────────────────────────

    def _pick(self, inst: str) -> tuple[Any, Any] | None:
        """``(model path, training record or None)``: the newest model file with a completed
        training run, else the newest file with no record."""
        files = self._artifacts.model_files(inst)
        if not files:
            return None
        prefix = f"rita_ddqn_asta_{inst.lower()}_"
        records = TrainingRunsRepository(self._db).find_complete_by_model_version(_model_version(inst))
        for rec in records:
            for f in files:
                suffix = f.stem[len(prefix):]
                if suffix and rec.run_id.startswith(suffix):
                    return f, rec
        return max(files, key=lambda p: p.stat().st_mtime), None

    @staticmethod
    def _lineage(path, rec) -> str:
        return f"asta_{rec.run_id[:8]}" if rec is not None else f"asta_{path.stem[-8:]}"

    # ── request path (cache only) ──────────────────────────────────────────────

    def trace(self, instrument: str, since: date | None = None, detail: bool = False) -> AstaTraceOut:
        inst = instrument.upper()
        picked = self._pick(inst)
        if picked is None:
            return AstaTraceOut(instrument_id=inst, status="no_model")
        path, rec = picked
        payload = self._cache.get(inst, self._lineage(path, rec), CACHE_TAU, "asta_latest")
        if payload is None:
            start_rebuild(inst)
            return AstaTraceOut(instrument_id=inst, status="warming")
        return self._out(inst, payload, since, detail)

    @staticmethod
    def _out(inst: str, p: dict, since: date | None, detail: bool) -> AstaTraceOut:
        fields: dict[str, Any] = {k: p.get(k) for k in (
            "model_sha12", "window_start", "window", "training_record", "pipeline_backtest", "as_of",
            "today_action", "last_signal", "model_note", "live_replay_note")}
        dates = [date.fromisoformat(d) for d in p.get("dates", [])]
        if p["status"] == "ok" and dates:
            base = max(since, dates[0]) if since is not None else dates[0]
            b = [d for d in dates if d <= base][-1]
            growth = 1.0
            for d, r in zip(dates[1:], p["daily_returns"]):
                if d > b:
                    growth *= 1.0 + r
            fields.update(since=b, return_since=growth - 1.0)
        if detail:
            fields["detail"] = {k: p.get(k) if k == "rationale" else p.get(k, []) for k in (
                "dates", "close", "allocation", "hedged", "markers", "signals", "rationale")}
        return AstaTraceOut(instrument_id=inst, status=p["status"], **fields)

    # ── warm-up (background) ───────────────────────────────────────────────────

    def build(self, instrument: str) -> dict | None:
        """Compute and cache one instrument's trace; returns the payload (None = no model)."""
        from rita.core.asta_indicators import compute_asta_indicators
        from rita.core.asta_labeler import label_asta_signals
        from rita.core.asta_trading_env import _ema_ratio_enabled, _prepare_asta_columns, run_episode_asta
        from rita.core.asta_trading_env import _ASTA_NUMERIC_COLS, _STRUCTURAL_BASE_COLS
        from rita.core.instrument_config import load_instrument_env_config

        inst = instrument.upper()
        picked = self._pick(inst)
        if picked is None:
            return None
        path, rec = picked
        lineage = self._lineage(path, rec)
        sha = self._artifacts.sha256(path)
        cfg = load_instrument_env_config(inst)
        months = get_settings().jarvis.asta.display_months

        raw = self._artifacts.load_ohlcv(inst)
        dataset = self._artifacts.load_dataset(inst)
        content_key = hashlib.sha256("|".join([
            sha, env_config_hash(cfg), raw[1] if raw else "-", dataset[1] if dataset else "-",
            rec.run_id if rec else "-"]).encode()).hexdigest()
        cached = self._cache.get(inst, lineage, CACHE_TAU, "asta_latest")
        if cached is not None and cached.get("content_key") == content_key:
            return cached

        payload: dict[str, Any] = {"content_key": content_key, "model_sha12": sha[:12],
                                   "status": "no_recorded_window"}
        if rec is not None:
            payload["training_record"] = {
                "run_id": rec.run_id, "test_sharpe": rec.backtest_sharpe, "test_mdd": rec.backtest_mdd,
                "test_return": rec.backtest_return, "test_trades": rec.backtest_trades}
            payload["model_note"] = f"training run {rec.run_id[:8]}"
            bt = BacktestRunsRepository(self._db).latest_for_model_version(_model_version(inst))
            if bt is not None:
                payload["pipeline_backtest"] = {"run_id": bt.run_id, "status": bt.status}
        if raw is None:
            payload["status"] = "no_data"
            self._cache.put(inst, lineage, CACHE_TAU, "asta_latest", payload)
            return payload

        model = self._artifacts.load_model(path)
        verified, basis = False, "no training record"
        test_start = test_end = None
        if dataset is not None and rec is not None:
            ds = dataset[0]
            test_start, test_end = derive_window(ds)
            perf = run_episode_asta(model, ds[ds.index >= pd.Timestamp(test_start)], env_config=cfg)["performance"]
            if parity_ok(perf, rec):
                verified, basis = True, (f"temporal_split 70/15/15 of {get_settings().jarvis.asta.dataset} "
                                         f"(sha256 {dataset[1][:12]}); replay matches training run "
                                         f"{rec.run_id[:8]}")
            else:
                basis = f"replay does not match training run {rec.run_id[:8]}"
        elif dataset is None:
            basis = "training dataset missing"

        fresh = label_asta_signals(compute_asta_indicators(raw[0]))
        if verified:
            match, overlap, mism = frame_matches(dataset[0], fresh, test_start)
            if not match:
                verified = False
                basis = "recomputed indicators differ from the training dataset"
            else:
                basis += f"; live frame equals the dataset on {overlap} bars ({mism} labeller signal(s) differ)"
        payload["window"] = {"test_start": test_start.isoformat() if test_start else None,
                             "test_end": test_end.isoformat() if test_end else None,
                             "verified": verified, "basis": basis}
        as_of = fresh.index[-1].date()
        payload["as_of"] = as_of.isoformat()
        disp_from = as_of - timedelta(days=int(months * 30.5))
        signals = _signal_rows(fresh[fresh.index >= pd.Timestamp(disp_from)])
        payload["signals"] = signals
        last = _signal_rows(fresh[fresh["asta_signal"].isin(["BUY", "SELL"])].tail(1))
        payload["last_signal"] = last[0] if last else None

        if verified:
            live = fresh[fresh.index >= pd.Timestamp(test_start)]
            res = run_episode_asta(model, live, env_config=cfg)
            prepared = _prepare_asta_columns(live)
            n_obs = int(model.observation_space.shape[0])
            use_ema = _ema_ratio_enabled(prepared, cfg) and n_obs >= 21
            required = list(_STRUCTURAL_BASE_COLS) + list(_ASTA_NUMERIC_COLS) + (["ema_ratio"] if use_ema else [])
            data = prepared.dropna(subset=required)
            obs = asta_observations(data, res["allocations"], res["hedge_flags"], cfg, REPLAY_TOLERANCE, use_ema)
            today_idx, _ = model.predict(obs[-1], deterministic=True)
            alloc, hedged = {0: (0.0, 0.0), 1: (0.5, 0.0), 2: (1.0, 0.0), 3: (1.0, 1.0)}[int(today_idx)]
            today_action = action_name(alloc, hedged)
            dates = [ts.date().isoformat() for ts in res["dates"]]
            close = [float(c) for c in res["close_prices"]]
            markers = _markers(dates, close, res["allocations"], res["hedge_flags"], dates[-1], today_action)
            when = markers[-1]["date"] if markers else dates[-1]
            p = dates.index(when)
            inputs, state = asta_rationale(data.iloc[p], obs[p], use_ema)
            sig = data.iloc[p]
            note = None
            if str(sig.get("asta_signal", "HOLD")) in ("BUY", "SELL"):
                note = f"setup:{sig.get('asta_setup', 'none')}"
            payload.update(
                status="ok", window_start=dates[0], dates=dates, close=close,
                allocation=[float(x) for x in [0.0] + list(res["allocations"])],
                hedged=[float(x) for x in [0.0] + list(res["hedge_flags"])],
                daily_returns=[float(x) for x in res["daily_returns"]], today_action=today_action,
                markers=markers, live_replay_note=_LIVE_NOTE,
                rationale={"date": when, "action": action_name(
                    *(res["allocations"][p], res["hedge_flags"][p])) if p < len(res["allocations"]) else today_action,
                           "prev_action": action_name(res["allocations"][p - 1], res["hedge_flags"][p - 1]) if p > 0 else "cash",
                           "inputs": inputs, "state": state, "note": note},
            )
        else:
            disp = fresh[fresh.index >= pd.Timestamp(disp_from)]
            payload.update(dates=[ts.date().isoformat() for ts in disp.index],
                           close=[float(c) for c in disp["Close"]], allocation=[], hedged=[], markers=[])
        self._cache.put(inst, lineage, CACHE_TAU, "asta_latest", payload)
        log.info("asta_trace.built", instrument=inst, status=payload["status"], verified=verified)
        return payload

    def warm(self) -> dict[str, str]:
        done: dict[str, str] = {}
        for inst in self._artifacts.instruments_with_models():
            try:
                p = self.build(inst)
                done[inst] = p["status"] if p else "no_model"
            except Exception as exc:  # noqa: BLE001 — warm-up never takes the app down
                log.warning("asta_trace.warm_failed", instrument=inst, error=type(exc).__name__)
                done[inst] = "failed"
        log.info("asta_trace.warmed", **done)
        return done


def warm_job(instrument: str | None = None) -> None:
    """Background warm-up: own ``SessionLocal``, closed in ``finally`` (project.md §8)."""
    from rita.database import SessionLocal

    db = SessionLocal()
    try:
        svc = AstaTraceService(db)
        if instrument is None:
            svc.warm()
        else:
            svc.build(instrument)
    except Exception as exc:  # noqa: BLE001
        log.warning("asta_trace.warm_thread_failed", error=type(exc).__name__)
    finally:
        db.close()
        if instrument is not None:
            with _rebuild_lock:
                _rebuilding.discard(instrument)


def start_rebuild(instrument: str) -> bool:
    """Start one background build for ``instrument`` unless one is running; never blocks."""
    if not get_settings().jarvis.asta.enabled:
        return False
    with _rebuild_lock:
        if instrument in _rebuilding:
            return False
        _rebuilding.add(instrument)
    threading.Thread(target=warm_job, args=(instrument,), name=f"asta-warm-{instrument}", daemon=True).start()
    return True
