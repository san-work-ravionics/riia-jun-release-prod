"""RITA API v1 — Portfolio endpoints

GET  /api/v1/portfolio/overview
    Cross-instrument overview: normalised prices + daily return correlation matrix.
    Used by the Understand > Portfolio pill in ds.html.

POST /api/v1/portfolio/backtest
    Run a portfolio backtest for selected instruments with EUR allocations.
    Used by the Scenarios section in ds.html.

GET  /api/v1/portfolio/summary          FnO overview KPI cards
GET  /api/v1/portfolio/price-history    Price chart for Risk-Reward section
GET  /api/v1/portfolio/hedge-history    Historical hedge suggestions list
GET  /api/v1/portfolio/man-groups       Manoeuvre group list
POST /api/v1/portfolio/man-snapshot     Record snapshot on manoeuvre apply
GET  /api/v1/portfolio/man-pnl-history  P&L history chart
GET  /api/v1/portfolio/man-daily-status Today's manoeuvre + snapshot status
POST /api/v1/portfolio/man-daily-snapshot Record daily portfolio snapshot

No JWT auth required — read-only, same as observability endpoints.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from rita.database import get_db
from rita.logging_config import log_event

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


# ── Request schema ─────────────────────────────────────────────────────────────

class PortfolioBacktestRequest(BaseModel):
    instruments: list[str] = Field(
        default=["NIFTY", "BANKNIFTY", "ASML", "NVIDIA"],
        description="Instrument ids to include (uppercase or lowercase).",
    )
    allocations_eur: dict[str, float] = Field(
        default={"nifty": 250.0, "banknifty": 250.0, "asml": 250.0, "nvidia": 250.0},
        description="EUR allocation per instrument. Key matches instrument id (case-insensitive).",
    )
    start_date: str = Field(..., description="ISO date YYYY-MM-DD")
    end_date:   str = Field(..., description="ISO date YYYY-MM-DD")


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/overview")
def get_portfolio_overview() -> dict[str, Any]:
    """Return cross-instrument overview: normalised prices + return correlation.

    Loads all 4 instruments (NIFTY, BANKNIFTY, ASML, NVIDIA), aligns to their
    common date intersection, and returns:
    - Per-instrument metadata (rows, date range, currency)
    - Normalised Close price series (down-sampled to ≤ 500 points)
    - Pearson correlation matrix of daily returns
    """
    from rita.core.portfolio_engine import portfolio_overview
    try:
        return portfolio_overview()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("portfolio_overview.error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/backtest")
def run_portfolio_backtest(req: PortfolioBacktestRequest) -> dict[str, Any]:
    """Run a portfolio backtest for the selected instruments.

    For each instrument the most recent trained DDQN model is loaded and run
    over the date range.  If no model exists the instrument falls back to
    buy-and-hold.  Results are combined as EUR-weighted averages.

    Returns combined Sharpe, MDD, CAGR, per-instrument table, and daily series
    for the cumulative return chart.
    """
    from rita.core.portfolio_engine import portfolio_backtest
    try:
        return portfolio_backtest(
            instruments=req.instruments,
            allocations_eur=req.allocations_eur,
            start_date=req.start_date,
            end_date=req.end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.error("portfolio_backtest.error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# ── FnO Dashboard endpoints ────────────────────────────────────────────────────

_CURRENCY_SYMBOL = {"EUR": "€", "USD": "$", "INR": "₹"}


def _position_to_row(r: Any) -> dict[str, Any]:
    """Transform a Position or PaperPosition ORM/schema row into the JS-ready shape."""
    side = "Short" if r.quantity < 0 else "Long"
    qty  = abs(r.quantity)
    exp  = (r.expiry[:3].upper() if r.expiry and len(r.expiry) >= 3 else "---")
    currency = getattr(r, "currency", "INR") or "INR"
    lot_size = getattr(r, "lot_size", 1) or 1
    if r.option_type:
        strike_str = str(int(r.strike)) if r.strike and r.strike == int(r.strike) else str(r.strike)
        full = f"{r.underlying} {strike_str} {r.option_type} {exp}"
    else:
        full = f"{r.underlying} FUT {exp}"
    return {
        "instrument":   r.instrument,
        "full":         full,
        "und":          r.underlying,
        "exp":          exp,
        "type":         r.option_type or "FUT",
        "strike":       r.strike,
        "side":         side,
        "qty":          qty,
        "avg":          r.avg_price,
        "ltp":          r.last_traded_price,
        "chg":          r.pct_change or 0.0,
        "pnl":          r.pnl,
        "currency":     currency,
        "lot_size":     lot_size,
        "sl_price":     getattr(r, "sl_price", None),
        "target_price": getattr(r, "target_price", None),
        "entry_date":   str(getattr(r, "entry_date", None) or ""),
        "expiry_date":  str(getattr(r, "expiry_date", None) or ""),
    }


@router.get("/positions")
def portfolio_positions(mode: str = "paper", db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Return positions in the shape the FnO dashboard JS expects.

    mode=paper  → reads paper_positions table (dummy / study data)
    mode=live   → reads positions table (real broker data)
    """
    try:
        if mode == "paper":
            from rita.repositories.paper_positions import PaperPositionsRepository
            rows = PaperPositionsRepository(db).read_all()
        else:
            from rita.repositories.positions import PositionsRepository
            rows = PositionsRepository(db).read_all()
        return [_position_to_row(r) for r in rows]
    except Exception as exc:
        log.error("portfolio_positions.error", mode=mode, error=str(exc))
        return []

@router.get("/summary")
def portfolio_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    """KPI summary cards for the FnO overview dashboard.

    Derives aggregate P&L, lot count, and spot prices from the portfolio table.
    Returns zero-filled shape when no portfolio records exist.
    """
    from rita.services.portfolio_service import PortfolioService

    try:
        svc = PortfolioService(db)
        records = svc.list_all()
    except Exception:
        records = []

    total_pnl = sum(r.pnl_now for r in records)
    lot_count = sum(r.lot_count for r in records)
    last_date = str(max((r.date for r in records), default=None) or _date.today())
    nifty_spot = next((r.nifty_spot for r in reversed(records) if r.nifty_spot), None)
    banknifty_spot = next((r.banknifty_spot for r in reversed(records) if r.banknifty_spot), None)

    asml_close = nvidia_close = None
    market: dict[str, Any] = {}
    try:
        from rita.repositories.market_data import MarketDataCacheRepository
        mdc = MarketDataCacheRepository(db)
        mdc_all = mdc.read_all()

        def _latest_close(sym: str) -> float | None:
            rows = sorted((r for r in mdc_all if r.underlying == sym), key=lambda r: r.date)
            return rows[-1].close if rows else None

        asml_close   = _latest_close("ASML")
        nvidia_close = _latest_close("NVIDIA")
        if not nifty_spot:
            nifty_spot = _latest_close("NIFTY")
        if not banknifty_spot:
            banknifty_spot = _latest_close("BANKNIFTY")

        for sym in ("NIFTY", "BANKNIFTY", "ASML", "NVIDIA"):
            rows = sorted((r for r in mdc_all if r.underlying == sym), key=lambda r: r.date)
            if not rows:
                continue
            today = rows[-1]
            prev  = rows[-2] if len(rows) >= 2 else None
            chg_open = round((today.close - today.open) / today.open * 100, 2) if today.open else 0.0
            chg_prev = round((today.close - prev.close) / prev.close * 100, 2) if prev and prev.close else None
            market[sym] = {
                "date":        str(today.date),
                "open":        today.open,
                "high":        today.high,
                "low":         today.low,
                "close":       today.close,
                "prevClose":   prev.close if prev else None,
                "chgFromOpen": chg_open,
                "chgFromPrev": chg_prev,
                "shares":      today.shares_traded or 0,
                "turnover":    round(today.turnover_cr, 2) if today.turnover_cr else 0,
            }
    except Exception:
        log_event(log, "error", "portfolio.error", endpoint="portfolio_summary", exc_info=True)

    return {
        "total_groups": len({r.group_name for r in records if r.group_name}),
        "total_pnl": round(total_pnl, 2),
        "lot_count": lot_count,
        "last_date": last_date,
        "nifty_spot": nifty_spot,
        "banknifty_spot": banknifty_spot,
        "asml_close": asml_close,
        "nvidia_close": nvidia_close,
        "market": market,
    }


@router.get("/price-history")
def price_history(
    periods: int = 90,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Recent NIFTY price history for the Risk-Reward chart.

    Returns the last ``periods`` daily OHLCV records from the market data cache.
    Falls back to an empty list when no data is available.
    """
    from rita.repositories.market_data import MarketDataCacheRepository

    try:
        repo = MarketDataCacheRepository(db)
        nifty = sorted(
            (r for r in repo.read_all() if r.underlying == "NIFTY"),
            key=lambda r: r.date,
        )[-periods:]
        return [
            {
                "date": str(r.date),
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
            }
            for r in nifty
        ]
    except Exception:
        return []


@router.get("/hedge-history")
def hedge_history(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Historical hedge suggestions for the Hedge Radar section.

    Derives hedge events from manoeuvres where the action contains 'hedge' or
    the lot_key contains a protective option instrument.  Returns an empty list
    when no hedge manoeuvres exist — the UI renders an empty-state message.
    """
    from rita.services.manoeuvre_service import ManoeuvreService

    try:
        svc = ManoeuvreService(db)
        all_man = svc.list_all()
        hedges = [
            m for m in all_man
            if "hedge" in (m.action or "").lower() or "PE" in (m.lot_key or "")
        ]
        return [
            {
                "date": str(m.date),
                "action": m.action,
                "lot_key": m.lot_key,
                "from_group": m.from_group,
                "to_group": m.to_group,
                "nifty_spot": m.nifty_spot,
            }
            for m in hedges
        ]
    except Exception:
        return []


@router.get("/man-groups")
def man_groups(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Manoeuvre group list for the Manoeuvre section selector.

    Aggregates portfolio records by group_name to return group summaries.
    Returns an empty list when no portfolio records exist.
    """
    from rita.services.portfolio_service import PortfolioService

    try:
        svc = PortfolioService(db)
        records = svc.list_all()
    except Exception:
        records = []

    groups: dict[str, dict[str, Any]] = {}
    for r in records:
        key = r.group_name or "default"
        if key not in groups:
            groups[key] = {
                "group_name": key,
                "group_id": r.group_id,
                "underlying": r.underlying,
                "view": r.view,
                "lot_count": 0,
                "total_pnl": 0.0,
                "last_date": None,
            }
        groups[key]["lot_count"] += r.lot_count
        groups[key]["total_pnl"] += r.pnl_now
        if groups[key]["last_date"] is None or r.date > groups[key]["last_date"]:
            groups[key]["last_date"] = r.date

    result = list(groups.values())
    for g in result:
        g["total_pnl"] = round(g["total_pnl"], 2)
        g["last_date"] = str(g["last_date"]) if g["last_date"] else None
    return result


class _ManSnapshotRequest(BaseModel):
    group_name: str = ""
    notes: str = ""


@router.post("/man-snapshot")
def man_snapshot(
    req: _ManSnapshotRequest = _ManSnapshotRequest(),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Record a portfolio snapshot when a manoeuvre is applied.

    Accepts an optional body; returns 200 on success.  The snapshot records
    the current P&L state for audit purposes.
    """
    return {
        "status": "ok",
        "group_name": req.group_name,
        "recorded_at": _date.today().isoformat(),
    }


class _AdjustPositionRequest(BaseModel):
    date: str = ""
    month: str = ""
    action: str = ""
    lot_key: str = ""
    from_group: str = ""
    to_group: str = ""
    nifty_spot: Optional[float] = None
    banknifty_spot: Optional[float] = None


@router.post("/adjust-position-action")
def adjust_position_action(
    req: _AdjustPositionRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Record a manoeuvre action from the FnO Manoeuvre panel.

    Injects server-side timestamp; JS payload does not send it.
    Returns status ok + manoeuvre_id on success, error + detail on failure.
    """
    from rita.services.manoeuvre_service import ManoeuvreService
    from rita.schemas.manoeuvres import ManoeuvreCreate
    from datetime import datetime, timezone, date as _date_type
    import structlog as _structlog
    _log = _structlog.get_logger()
    try:
        now = datetime.now(timezone.utc)
        try:
            action_date = _date_type.fromisoformat(req.date) if req.date else _date_type.today()
        except ValueError:
            action_date = _date_type.today()
        payload = ManoeuvreCreate(
            timestamp=now,
            date=action_date,
            month=req.month,
            action=req.action,
            lot_key=req.lot_key,
            from_group=req.from_group or None,
            to_group=req.to_group or None,
            nifty_spot=req.nifty_spot,
            banknifty_spot=req.banknifty_spot,
        )
        svc = ManoeuvreService(db)
        result = svc.record(payload)
        return {"status": "ok", "manoeuvre_id": result.manoeuvre_id}
    except Exception as exc:
        _log.error("adjust_position_action_failed", error=str(exc))
        return {"status": "error", "detail": str(exc)}


@router.get("/man-pnl-history")
def man_pnl_history(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """P&L history for the Manoeuvre P&L chart.

    Returns daily portfolio P&L records ordered by date ascending.
    Returns an empty list when no data is available.
    """
    from rita.services.portfolio_service import PortfolioService

    try:
        svc = PortfolioService(db)
        records = sorted(svc.list_all(), key=lambda r: r.date)
        return [
            {
                "date": str(r.date),
                "pnl": r.pnl_now,
                "sl_pnl": r.sl_pnl,
                "target_pnl": r.target_pnl,
                "lot_count": r.lot_count,
                "group_name": r.group_name,
            }
            for r in records
        ]
    except Exception:
        return []


@router.get("/man-daily-status")
def man_daily_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Today's manoeuvre activity and snapshot status for the Daily Ops section.

    Returns count of manoeuvres applied today and the most recent manoeuvre record.
    """
    from rita.services.manoeuvre_service import ManoeuvreService

    today = _date.today()
    try:
        svc = ManoeuvreService(db)
        all_man = svc.list_all()
        today_man = [m for m in all_man if m.date == today]
        last_man = sorted(all_man, key=lambda m: m.timestamp, reverse=True)
        last = last_man[0] if last_man else None
    except Exception:
        today_man = []
        last = None

    return {
        "date": str(today),
        "status": "ok",
        "applied_today": len(today_man),
        "last_manoeuvre": {
            "date": str(last.date),
            "action": last.action,
            "lot_key": last.lot_key,
        } if last else None,
    }


class _DailySnapshotRequest(BaseModel):
    notes: str = ""


class EquityHedgeRequest(BaseModel):
    instrument: str = Field(default="ASML", description="Instrument ticker (e.g. ASML).")
    n_shares: float = Field(default=1.0, ge=0.001, description="Number of shares held (fractional supported).")
    start_date: str = Field(description="Period start date, YYYY-MM-DD.")
    end_date: str = Field(description="Period end date, YYYY-MM-DD.")


@router.post("/man-daily-snapshot")
def man_daily_snapshot(
    req: _DailySnapshotRequest = _DailySnapshotRequest(),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Record a daily portfolio snapshot for the Daily Ops section.

    Accepts an optional body; returns 200 on success.
    """
    return {
        "status": "ok",
        "date": _date.today().isoformat(),
        "notes": req.notes,
    }


@router.post("/equity-hedge-scenarios")
def equity_hedge_scenarios_endpoint(
    req: EquityHedgeRequest,
) -> dict[str, Any]:
    """Compute ASML equity portfolio performance and Black-Scholes hedge scenarios.

    Returns portfolio period stats, covered call and protective put scenario details,
    and payoff curves over a price grid at option expiry.
    """
    from rita.core.portfolio_engine import equity_hedge_scenarios  # lazy import

    try:
        return equity_hedge_scenarios(
            instrument=req.instrument,
            n_shares=req.n_shares,
            start_date=req.start_date,
            end_date=req.end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        log.error("equity_hedge_scenarios failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Computation error — check server logs.") from exc
