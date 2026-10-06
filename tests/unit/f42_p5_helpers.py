"""F42 P5 helpers: load the committed sample CSVs through the REAL import service and read every
panel through the REAL analytics services.  Synthetic data only; never touches live-data/."""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[2]
SAMPLE_DIR = REPO / "data" / "input" / "sample" / "fno"
FIXTURE = REPO / "scripts" / "fixtures" / "fno_sample_closes.csv"
NAMES = {"tradebook": "SAMPLE_tradebook.csv", "pnl": "SAMPLE_pnl.csv", "ledger": "SAMPLE_ledger.csv"}
WINDOW = (date(2026, 7, 1), date(2026, 9, 18))
TODAY = date(2026, 9, 18)          # pinned "now": every band is evaluated at the window end


def closes() -> list[tuple[str, float, float]]:
    with FIXTURE.open(newline="") as f:
        return [(r["date"], float(r["nifty_close"]), float(r["banknifty_close"]))
                for r in csv.DictReader(f)]


def seed_spot(db) -> None:
    from rita.models.market_data import MarketDataCacheModel

    for d, n, b in closes():
        for u, c in (("NIFTY", n), ("BANKNIFTY", b)):
            db.add(MarketDataCacheModel(cache_id=f"{u}-{d}", date=date.fromisoformat(d), underlying=u,
                                        open=c, high=c, low=c, close=c, recorded_at=datetime(2026, 10, 1)))
    db.commit()


def load_files(db, user_id: str, directory: Optional[Path] = None, order=("tradebook", "ledger", "pnl")):
    """Import the three committed files exactly as the sample endpoint does (reserved names allowed)."""
    from rita.services.fno_import_service import FnoImportService, UploadInput

    d = directory or SAMPLE_DIR
    ups = [UploadInput(name=NAMES[k], data=(d / NAMES[k]).read_bytes()) for k in order]
    return FnoImportService(db).import_files(user_id, ups, allow_reserved=True)


def new_db():
    """A fresh in-memory SQLite session with every table (caller closes it)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from rita.database import Base

    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def ctx_for(db, user_id: str, include_est: Optional[bool] = False):
    """The analytics context (closed trades, events) the panels are built from."""
    from rita.services.fno_trade_analytics_service import AnalyticsParams, FnoTradeAnalyticsService

    svc = FnoTradeAnalyticsService(db, today=TODAY)
    return svc._prepare(user_id, AnalyticsParams(date_to=TODAY, include_expiry_estimate=include_est),
                        "overtrading")


def panels(db, user_id: str, include_est: Optional[bool] = False):
    from rita.services.fno_trade_analytics_service import AnalyticsParams, FnoTradeAnalyticsService

    svc = FnoTradeAnalyticsService(db, today=TODAY)
    p = AnalyticsParams(date_to=TODAY, include_expiry_estimate=include_est)
    return {
        "foundation": svc.foundation(user_id, p), "overtrading": svc.overtrading(user_id, p),
        "buildup": svc.buildup(user_id, p), "market-turn": svc.market_turn(user_id, p),
        "margin-trap": svc.margin_trap(user_id, p), "suggestions": svc.suggestions(user_id, p),
        "spot-vs-pnl": svc.spot_vs_pnl(user_id, p),
    }
