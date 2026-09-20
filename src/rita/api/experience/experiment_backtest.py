"""Experience Layer — FnO Experiment Backtest.

ADR-001: Tier 3 (Experience Layer). Read-only, no side effects.
Reads nifty_experiment_daily.csv, queries nse_option_bhav table for real prices,
runs strangle backtest with real NSE prices (fallback BSM), returns JSON.
"""
from __future__ import annotations

import csv as _csv
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from rita.config import Settings, get_settings
from rita.core.experiment_backtest import get_valid_contracts_from_repo, run_backtest
from rita.database import get_db
from rita.repositories.nse_option_bhav import NseOptionBhavRepository
from rita.schemas.experiment_backtest import ExperimentBacktestPayload

router = APIRouter(
    prefix="/api/experience/fno",
    tags=["experience:fno-experiment"],
)


def _csv_path(settings: Settings) -> Path:
    return Path(settings.data.input_dir) / "NIFTY" / "nifty_experiment_daily.csv"


@router.get("/experiment-backtest", response_model=ExperimentBacktestPayload)
def get_experiment_backtest(
    target_pct: float = Query(default=15.0, ge=1.0, le=100.0),
    sl_pct: float = Query(default=5.0, ge=0.5, le=50.0),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> ExperimentBacktestPayload:
    csv_path = _csv_path(settings)
    lot_size = settings.instruments.nifty.lot_size

    repo = NseOptionBhavRepository(db)
    option_prices = repo.get_option_prices()

    result = run_backtest(
        csv_path=csv_path,
        lot_size=lot_size,
        target_pct=target_pct,
        sl_pct=sl_pct,
        option_prices=option_prices,
    )

    return ExperimentBacktestPayload(
        summary=result["summary"],
        entries=result["entries"],
    )


@router.get("/experiment-valid-contracts")
def get_valid_contracts_info(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> dict:
    lot_size = settings.instruments.nifty.lot_size
    repo = NseOptionBhavRepository(db)
    return get_valid_contracts_from_repo(repo, lot_size)


@router.post("/import-bhav-csv")
def import_bhav_csv(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> dict:
    """One-time import: load nifty_option_bhav.csv into nse_option_bhav table."""
    bhav_path = Path(settings.data.input_dir) / "NIFTY" / "nifty_option_bhav.csv"
    if not bhav_path.exists():
        return {"error": f"CSV not found: {bhav_path}"}

    repo = NseOptionBhavRepository(db)
    existing = repo.count()
    if existing > 0:
        return {
            "error": f"Table already has {existing} rows. "
            "DELETE first via /experiment-clear-bhav if you want to re-import.",
        }

    from datetime import date as _date

    records: list[dict] = []
    with open(bhav_path) as f:
        for r in _csv.DictReader(f):
            records.append({
                "date": _date.fromisoformat(r["date"]),
                "strike": int(float(r["strike"])),
                "option_type": r["option_type"],
                "expiry": _date.fromisoformat(r["expiry"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "settle_price": float(r.get("settle_price", 0)),
                "oi": int(float(r.get("oi", 0))),
            })

    inserted = repo.bulk_insert(records)
    return {"imported": inserted, "source": str(bhav_path)}


@router.delete("/experiment-clear-bhav")
def clear_bhav_data(
    db: Session = Depends(get_db),
) -> dict:
    """Delete all rows from nse_option_bhav table (for re-import)."""
    repo = NseOptionBhavRepository(db)
    deleted = repo.delete_all()
    return {"deleted": deleted}
