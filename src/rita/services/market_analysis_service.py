"""Market analysis service — the indicators DataFrame loader (F44 P1, moved from the chat route).

``get_indicator_df(instrument)`` was ``rita.api.v1.workflow.chat._get_df``; moved unchanged so the
chat route, commentary and the MCP ``market.*`` tools share one loader without a tool importing a
route module (ADR-007 §2).  The chat module re-exports it as ``_get_df`` (no behaviour change).

Reads the instrument's price CSV via ``core.data_understanding.find_instrument_csv`` +
``core.data_loader.load_ohlcv_csv`` (the existing core loaders), appends the manual daily supplement
(``data/input/DAILY-DATA/{instrument}_manual.csv``) when present, and caches per instrument until a
source file's mtime changes.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import structlog

from rita.config import get_settings

log = structlog.get_logger(__name__)

# { "NIFTY": {"df": ..., "mtime_key": (p, m)}, "NVIDIA": {...}, ... }
_market_signals_cache: dict[str, dict[str, Any]] = {}

# Instrument ids are plain tickers — never a path (F44 P1 review: ``../`` must not reach the
# glob in core/data_understanding.find_instrument_csv).
INSTRUMENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def known_instruments() -> set[str]:
    """Instrument ids that have a price folder under the configured raw / input data dirs."""
    settings = get_settings()
    found: set[str] = set()
    for base in (settings.data.raw_dir, settings.data.input_dir):
        root = Path(base)
        if root.is_dir():
            found.update(p.name.upper() for p in root.iterdir() if p.is_dir())
    return found


def is_known_instrument(instrument: str) -> bool:
    """True for a well-formed id (``INSTRUMENT_ID_RE``) that is in ``known_instruments()``."""
    return bool(INSTRUMENT_ID_RE.match(instrument or "")) and instrument.upper() in known_instruments()


def get_indicator_df(instrument: str):
    """Load and cache the indicators DataFrame for the given instrument.

    Uses find_instrument_csv() for the primary file and appends the manual
    daily supplement (data/input/DAILY-DATA/{instrument}_manual.csv) when
    present (NIFTY and BANKNIFTY maintain one; others typically do not).
    Recomputes only when any source file's mtime changes.
    """
    import pandas as pd
    from rita.core.data_loader import load_ohlcv_csv
    from rita.core.data_understanding import find_instrument_csv
    from rita.core.technical_analyzer import calculate_indicators

    if not is_known_instrument(instrument):
        # Same failure type the chat route already maps to 503 for a missing CSV.
        raise FileNotFoundError(f"unknown instrument {instrument!r}")
    inst = instrument.upper()
    settings = get_settings()

    primary_path = str(find_instrument_csv(inst))
    manual_path  = Path(settings.data.input_dir) / "DAILY-DATA" / f"{inst.lower()}_manual.csv"

    mtime_primary = os.path.getmtime(primary_path)
    mtime_manual  = os.path.getmtime(str(manual_path)) if manual_path.exists() else 0.0
    mtime_key = (mtime_primary, mtime_manual)

    cached = _market_signals_cache.get(inst)
    if cached is not None and cached["mtime_key"] == mtime_key:
        return cached["df"]

    raw = load_ohlcv_csv(primary_path)
    if manual_path.exists():
        manual = load_ohlcv_csv(str(manual_path))
        raw = pd.concat([raw, manual])
        raw = raw[~raw.index.duplicated(keep="last")].sort_index()

    df = calculate_indicators(raw)
    _market_signals_cache[inst] = {"df": df, "mtime_key": mtime_key}
    log.info("chat.csv_reloaded", instrument=inst, primary=primary_path,
             rows=len(df), latest=str(df.index[-1].date()))
    return df
