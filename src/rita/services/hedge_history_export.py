"""Flatten hedge-plan history rows to one row per save x instrument (CSV export, F40).

Pure functions — no DB access.  Used by the system export router and the
``project-office/scripts/export_hedge_history.py`` CLI.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Iterable

HEADER_COLUMNS = [
    "history_id", "saved_at", "user_id", "key_id", "trigger", "source", "last_step",
    "scenario_tab", "coverage", "duration", "schema_version", "app_version",
    "total_value_eur", "cash_eur", "n_holdings",
    "instrument_id", "hedged", "strategy", "shares", "allocation_pct", "currency",
    "spot", "spot_date", "position_value", "ann_vol_pct",
    "strike_pct", "strike_label", "premium_pct", "cost_source", "hedge_type",
    "risk_score", "protected_pct",
]

_INSTRUMENT_COLUMNS = HEADER_COLUMNS[15:]


def flatten_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
    """One dict per save x instrument; a save with no instruments yields one blank-instrument row."""
    out: list[dict[str, Any]] = []
    for r in rows:
        saved_at = r.saved_at.isoformat() if getattr(r, "saved_at", None) else None
        pf = r.portfolio or {}
        base = {
            "history_id": r.history_id, "saved_at": saved_at, "user_id": r.user_id,
            "key_id": r.key_id, "trigger": r.trigger, "source": r.source,
            "last_step": r.last_step, "scenario_tab": r.scenario_tab,
            "coverage": r.coverage, "duration": r.duration,
            "schema_version": r.schema_version, "app_version": r.app_version,
            "total_value_eur": pf.get("total_value_eur"), "cash_eur": pf.get("cash_eur"),
            "n_holdings": pf.get("n_holdings"),
        }
        insts = r.instruments or []
        if not insts:
            out.append({**base, **{c: None for c in _INSTRUMENT_COLUMNS}})
            continue
        for inst in insts:
            out.append({**base, **{c: inst.get(c) for c in _INSTRUMENT_COLUMNS}})
    return out


def to_csv(rows: Iterable[Any]) -> str:
    """Header + flattened rows as CSV text (None -> blank)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADER_COLUMNS, lineterminator="\n")
    w.writeheader()
    for d in flatten_rows(rows):
        w.writerow({k: ("" if v is None else v) for k, v in d.items()})
    return buf.getvalue()
