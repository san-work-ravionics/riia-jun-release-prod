"""File-backed cache of DDQN model replays (F44 P3, A9; ADR-002).

One JSON file per (instrument, lineage, τ) under ``<data.output_dir>/goal_model_runs/<INST>/``:
``{"key": <cache key>, "run": <ModelRun.to_dict()>}``.  The key is a hash of
(instrument, lineage, model sha256, env-config hash, split hash, data content hash, τ), so a new
model, config, split or data bar invalidates it; a stale file is simply overwritten.

Exemption note: project.md §8 applies to SQLAlchemy repositories; this one is built from a
directory.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from rita.config import get_settings

CACHE_SUBDIR = "goal_model_runs"


def cache_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


class ModelRunCacheRepository:
    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)

    @classmethod
    def from_settings(cls) -> "ModelRunCacheRepository":
        return cls(Path(get_settings().data.output_dir) / CACHE_SUBDIR)

    def _path(self, instrument: str, lineage: str, tolerance: str) -> Path:
        return self._dir / instrument.upper() / f"{lineage}_{tolerance}.json"

    def get(self, instrument: str, lineage: str, tolerance: str, key: str) -> dict[str, Any] | None:
        path = self._path(instrument, lineage, tolerance)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if payload.get("key") != key:
            return None
        return payload.get("run")

    def put(self, instrument: str, lineage: str, tolerance: str, key: str,
            run: dict[str, Any]) -> None:
        path = self._path(instrument, lineage, tolerance)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"key": key, "run": run}), encoding="utf-8")
        os.replace(tmp, path)
