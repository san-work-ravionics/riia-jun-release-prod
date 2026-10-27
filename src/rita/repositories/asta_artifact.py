"""File-backed repository for the ASTA engine artifacts (F44 P4 rev 1 B5; ADR-002).

The single owner of every file access the Jarvis ASTA trace needs:
- the ASTA model zips ``<model.path>/<INST>/rita_ddqn_asta_<inst>_*.zip`` (find, sha256, load);
- the git-tracked training dataset ``<data.input_dir>/<INST>/asta_labeled_dataset.csv`` (read
  once to derive the training window with ``temporal_split``, and sha256);
- the instrument's live OHLCV history (``load_instrument_data``) — the live trace recomputes
  ``compute_asta_indicators`` + ``label_asta_signals`` on it; the stale dataset CSV is never used
  for bars after its last row.

Exemption note: project.md §8 applies to SQLAlchemy repositories; this one is built from
directories (like ``ModelArtifactRepository``).
"""
from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

from rita.config import get_settings


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class AstaArtifactRepository:
    def __init__(self, model_dir: Path, input_dir: Path, model_pattern: str, dataset: str) -> None:
        self._model_dir = Path(model_dir)
        self._input_dir = Path(input_dir)
        self._pattern = model_pattern
        self._dataset = dataset

    @classmethod
    def from_settings(cls) -> "AstaArtifactRepository":
        s = get_settings()
        return cls(Path(s.model.path), Path(s.data.input_dir), s.jarvis.asta.model_pattern,
                   s.jarvis.asta.dataset)

    # ── models ─────────────────────────────────────────────────────────────────

    def instruments_with_models(self) -> list[str]:
        """Instruments that have at least one ASTA model zip ("models present")."""
        if not self._model_dir.is_dir():
            return []
        out = []
        for d in sorted(p for p in self._model_dir.iterdir() if p.is_dir()):
            if self.model_files(d.name):
                out.append(d.name.upper())
        return out

    def model_files(self, instrument: str) -> list[Path]:
        folder = self._model_dir / instrument.upper()
        if not folder.is_dir():
            return []
        pat = self._pattern.format(inst=instrument.lower())
        return sorted(p for p in folder.iterdir() if p.is_file() and fnmatch.fnmatch(p.name, pat))

    @staticmethod
    def sha256(path: Path) -> str:
        return _sha256_file(path)

    @staticmethod
    def load_model(path: Path) -> Any:
        from rita.core.model_compat import load_dqn_compat

        return load_dqn_compat(str(path))

    # ── data ───────────────────────────────────────────────────────────────────

    def dataset_path(self, instrument: str) -> Path:
        return self._input_dir / instrument.upper() / self._dataset

    def load_dataset(self, instrument: str) -> tuple[pd.DataFrame, str] | None:
        """``(training dataset, sha256)`` or None when the file is missing."""
        path = self.dataset_path(instrument)
        if not path.is_file():
            return None
        df = pd.read_csv(str(path), index_col="Date", parse_dates=True)
        return df, _sha256_file(path)

    @staticmethod
    def load_ohlcv(instrument: str) -> tuple[pd.DataFrame, str] | None:
        """``(live OHLCV history, content hash)`` or None when there is no price data."""
        from rita.core.data_loader import load_instrument_data

        try:
            raw = load_instrument_data(instrument.upper())
        except FileNotFoundError:
            return None
        if raw is None or raw.empty:
            return None
        h = hashlib.sha256(pd.util.hash_pandas_object(raw, index=True).to_numpy().tobytes()).hexdigest()
        return raw, h
