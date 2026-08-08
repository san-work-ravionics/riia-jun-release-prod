"""Experience Layer — Equity Scenarios live-priced holdings.

ADR-001 Tier 3: read-only composition, no writes, no side effects.

GET /api/v1/experience/equity-scenarios/holdings

Reads static holdings (symbol, qty, avg_cost) from
dashboard/data/scenarios/portfolio.json, enriches with the latest
close price from market_data_cache, and computes ltp, day_chg_pct,
cur_val, pnl, and net_chg_pct at request time.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.models.market_data import MarketDataCacheModel

log = structlog.get_logger()

router = APIRouter(
    prefix="/api/v1/experience/equity-scenarios",
    tags=["experience:equity-scenarios"],
)

_PORTFOLIO_JSON = (
    Path(__file__).resolve().parent.parent.parent.parent.parent / "dashboard" / "data" / "scenarios" / "portfolio.json"
)


def _load_static_holdings() -> list[dict]:
    with open(_PORTFOLIO_JSON) as f:
        return json.load(f)["holdings"]


def _latest_two_closes(db: Session, symbols: list[str]) -> dict[str, tuple[float | None, float | None]]:
    """Return {SYMBOL: (latest_close, prev_close)} from market_data_cache."""
    rows = (
        db.query(MarketDataCacheModel)
        .filter(MarketDataCacheModel.underlying.in_([s.upper() for s in symbols]))
        .order_by(MarketDataCacheModel.underlying, MarketDataCacheModel.date.desc())
        .all()
    )
    by_inst: dict[str, list] = defaultdict(list)
    for r in rows:
        by_inst[r.underlying.upper()].append(r)

    result: dict[str, tuple[float | None, float | None]] = {}
    for sym in symbols:
        recs = by_inst.get(sym.upper(), [])
        latest = float(recs[0].close) if recs else None
        prev = float(recs[1].close) if len(recs) >= 2 else None
        latest_date = str(recs[0].date) if recs else None
        result[sym.upper()] = (latest, prev, latest_date)
    return result


@router.get("/holdings")
def get_live_holdings(db: Session = Depends(get_db)):
    holdings = _load_static_holdings()
    symbols = [h["symbol"] for h in holdings]
    prices = _latest_two_closes(db, symbols)

    enriched = []
    for h in holdings:
        sym = h["symbol"].upper()
        latest_close, prev_close, latest_date = prices.get(sym, (None, None, None))

        if latest_close is not None:
            ltp = round(latest_close, 2)
            day_chg_pct = (
                round((latest_close - prev_close) / prev_close * 100, 2)
                if prev_close
                else 0.0
            )
        else:
            ltp = h.get("ltp", 0)
            day_chg_pct = h.get("day_chg_pct", 0)

        qty = h["qty"]
        avg_cost = h["avg_cost"]
        invested = round(avg_cost * qty, 2)
        cur_val = round(ltp * qty, 2)
        pnl = round(cur_val - invested, 2)
        net_chg_pct = round((pnl / invested) * 100, 2) if invested else 0.0

        enriched.append({
            "symbol": h["symbol"],
            "qty": qty,
            "avg_cost": avg_cost,
            "ltp": ltp,
            "invested": invested,
            "cur_val": cur_val,
            "pnl": pnl,
            "net_chg_pct": net_chg_pct,
            "day_chg_pct": day_chg_pct,
        })

    return {
        "last_updated": latest_date or date.today().isoformat(),
        "holdings": enriched,
    }
