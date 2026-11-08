"""File-backed repository for model lineage artifacts (F44 P3, ADR-002).

The single owner of every file access the goal-driven selection needs:
- the lineage zip ``<model.path>/<INST>/<pattern>`` (find, sha256, load via ``load_dqn_compat``);
- the lineage split (AST-parsed from the lineage's training script when present, else the
  registry dates — the image has no ``scripts/``);
- the instrument's indicator frame: ``load_instrument_data`` (the training CSV the lineage used,
  plus the refresh path's companion / manual bars after it) → ``calculate_indicators`` on the full
  history — the same feature path as training;
- the step-0 rewrite marker ``<raw_dir>/<INST>/goal_data_rewrite.json`` (written by
  ``services/data_refresh.py`` when a history is rewritten).

Exemption note: project.md §8 ("constructors take ``db: Session``") applies to the SQLAlchemy
repositories; a file-backed repository is constructed from directories instead.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import structlog

from rita.config import ModelLineage, get_settings
from rita.core.goal_model_runs import LineageSplit, fraction_split, parse_lineage_split

log = structlog.get_logger(__name__)

REWRITE_MARKER = "goal_data_rewrite.json"
_APP_ROOT = Path(__file__).resolve().parents[3]   # repo root locally, /app in the image


@dataclass(frozen=True)
class IndicatorFrame:
    df: pd.DataFrame
    data_hash: str      # sha256 of the OHLCV content the frame was built from
    last_date: Any      # datetime.date of the last bar


class ModelArtifactRepository:
    _sha_memo: dict[tuple[str, int, int], str] = {}
    _frame_memo: dict[tuple[str, str], pd.DataFrame] = {}
    _memo_lock = threading.Lock()

    def __init__(self, model_dir: Path, raw_dir: Path, app_root: Path = _APP_ROOT) -> None:
        self._model_dir = Path(model_dir)
        self._raw_dir = Path(raw_dir)
        self._app_root = Path(app_root)

    @classmethod
    def from_settings(cls) -> "ModelArtifactRepository":
        s = get_settings()
        return cls(Path(s.model.path), Path(s.data.raw_dir))

    # ── model zip ──────────────────────────────────────────────────────────────

    def find(self, instrument: str, lineage: ModelLineage) -> Path | None:
        """The lineage's model zip.  An exact-name pattern is one file; a pattern with ``*`` takes the newest
        match, leaving out the exact files other lineages own (so ``..._f34p25.zip`` stays with F34)."""
        folder = self._model_dir / instrument.upper()
        pat = lineage.pattern.format(inst=instrument.lower())
        if not any(ch in pat for ch in "*?["):
            path = folder / pat
            return path if path.is_file() else None
        if not folder.is_dir():
            return None
        owned = {o.pattern.format(inst=instrument.lower()) for o in get_settings().goal_selection.model_lineages
                 if o.name != lineage.name and not any(ch in o.pattern for ch in "*?[")}
        files = [p for p in folder.iterdir()
                 if p.is_file() and fnmatch.fnmatch(p.name, pat) and p.name not in owned]
        return max(files, key=lambda p: p.stat().st_mtime) if files else None

    def trained_on(self, instrument: str, model_path: Path) -> date:
        """The day a pipeline model was trained: its first ``training_history.csv`` row (the run id in the
        file name, ``notes`` ``run_id=<8 hex>``), else the file's modification time.  A later date can only
        move the reconstructed training end later, which is the safe side."""
        run8 = model_path.stem.rsplit("_", 1)[-1]
        history = self._model_dir / instrument.upper() / "training_history.csv"
        if history.is_file():
            try:
                df = pd.read_csv(history)
                rows = df[df["notes"].astype(str).str.contains(f"run_id={run8}", regex=False)]
                stamps = pd.to_datetime(rows["timestamp"], errors="coerce").dropna()
                if len(stamps):
                    return stamps.min().date()
            except (KeyError, ValueError, OSError):
                pass
        return datetime.fromtimestamp(model_path.stat().st_mtime).date()

    def split_for(self, lineage: ModelLineage, instrument: str, model_path: Path, index) -> LineageSplit:
        """The windows this model was trained / reported on: the lineage's fixed dates, or the pipeline's
        fractional split reproduced on the bars that existed when the model was trained."""
        if lineage.split_rule == "dates":
            return self.lineage_split(lineage)
        return fraction_split(index, self.trained_on(instrument, model_path), lineage.train_frac,
                              lineage.val_frac, lineage.margin_bars)

    def sha256(self, path: Path) -> str:
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime_ns)
        with self._memo_lock:
            hit = self._sha_memo.get(key)
        if hit is not None:
            return hit
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        digest = h.hexdigest()
        with self._memo_lock:
            self._sha_memo[key] = digest
        return digest

    def load(self, path: Path) -> Any:
        """The DQN policy (cross-version safe loader; raises on failure)."""
        from rita.core.model_compat import load_dqn_compat

        return load_dqn_compat(str(path))

    # ── lineage split ──────────────────────────────────────────────────────────

    def lineage_split(self, lineage: ModelLineage) -> LineageSplit:
        """AST-parsed from the lineage script when the file exists, else the registry dates."""
        registry = LineageSplit(lineage.train_end, lineage.val_start, lineage.val_end,
                                lineage.backtest_start)
        script = self._app_root / lineage.source if lineage.source else None
        if script is None or not script.is_file():
            return registry
        parsed = parse_lineage_split(script.read_text(encoding="utf-8"))
        if parsed != registry:
            log.warning("goal_selection.lineage_split_mismatch", lineage=lineage.name,
                        script=str(lineage.source))
        return parsed

    # ── data ───────────────────────────────────────────────────────────────────

    def load_indicator_frame(self, instrument: str) -> IndicatorFrame | None:
        """Full-history indicator frame, or None when the instrument has no price data."""
        from rita.core.data_loader import load_instrument_data
        from rita.core.technical_analyzer import calculate_indicators

        try:
            raw = load_instrument_data(instrument.upper())
        except FileNotFoundError:
            return None
        if raw is None or raw.empty:
            return None
        data_hash = hashlib.sha256(
            pd.util.hash_pandas_object(raw, index=True).to_numpy().tobytes()
            + ",".join(map(str, raw.columns)).encode()
        ).hexdigest()
        key = (instrument.upper(), data_hash)
        with self._memo_lock:
            df = self._frame_memo.get(key)
        if df is None:
            df = calculate_indicators(raw)
            with self._memo_lock:
                # keep one frame per instrument (the latest data)
                for k in [k for k in self._frame_memo if k[0] == key[0]]:
                    del self._frame_memo[k]
                self._frame_memo[key] = df
        return IndicatorFrame(df=df, data_hash=data_hash, last_date=df.index[-1].date())

    # ── step-0 rewrite marker ──────────────────────────────────────────────────

    def rewrite_marker(self, instrument: str) -> dict[str, Any] | None:
        path = self._raw_dir / instrument.upper() / REWRITE_MARKER
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # An unreadable marker still means the history was rewritten.
            return {"lineages_invalidated": ["*"], "unreadable": True}

    def write_rewrite_marker(self, instrument: str, payload: dict[str, Any]) -> Path:
        path = self._raw_dir / instrument.upper() / REWRITE_MARKER
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        os.replace(tmp, path)
        return path
