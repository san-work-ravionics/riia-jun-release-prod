"""Experience Layer — Portfolio Hedge endpoint (Feature 28 Phase 3).

ADR-001 Tier 3: read-only composition, no writes, no side effects.
Computes per-holding hedge parameters using Black-Scholes on realized vol.

GET /api/v1/experience/fno/portfolio-hedge?coverage=50&duration=1y  (JWT required)
duration: '1m' | '3m' | '1y'  (default '1y')
"""
from __future__ import annotations

import math
import statistics
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.database import get_db
from rita.models.user import UserModel
from rita.repositories.market_data import MarketDataCacheRepository
from rita.repositories.user_portfolio import UserPortfolioRepo
from rita.repositories.user_portfolio_key import UserPortfolioKeyRepo
from rita.schemas.user_portfolio import HoldingItem

router = APIRouter(prefix="/api/v1/experience/fno", tags=["experience:portfolio-hedge"])

_FNO_ELIGIBLE: frozenset[str] = frozenset({
    "RELIANCE", "TATAMOTOR", "TCS", "INFY", "HDFCBANK", "WIPRO", "BAJFINANCE",
    "TATASTEEL", "SBIN", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SUNPHARMA",
    "HCLTECH", "LT", "ONGC", "NTPC", "POWERGRID", "BPCL",
})

_DURATION_MONTHS: dict[str, float] = {"1m": 1.0, "3m": 3.0, "1y": 12.0}

# ── Pydantic schemas ───────────────────────────────────────────────────────────
class HedgeHolding(BaseModel):
    instrument_id: str
    weight: float
    return_1y_pct: float | None
    risk_score: int | None
    hedge_type: str           # protective_put | put_spread | ndx_proxy | nifty_proxy
    eligible: bool
    strike_pct: float         # negative = OTM put distance (e.g. -7.5 → 7.5% OTM)
    strike_label: str
    cost_pct: float           # put-buy monthly premium as % of position
    protected_pct: int
    ann_vol_pct: float        # annualised realised volatility %
    call_sell_cost_pct: float # BS call premium at symmetric OTM level
    duration: str             # '1m' | '3m' | '1y'


class HedgeAggregate(BaseModel):
    max_dd_protected_pct: float
    max_dd_unhedged_pct: float
    monthly_cost_pct: float


class PortfolioHedgeResponse(BaseModel):
    holdings: list[HedgeHolding]
    aggregate: HedgeAggregate
    coverage: int
    duration: str


# ── Black-Scholes helpers ──────────────────────────────────────────────────────
def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2))) / 2.0


def _bs_put_pct(
    vol_annual_pct: float,
    strike_pct: float,
    r: float = 0.065,
    t_months: float = 12.0,
) -> float:
    """Put premium as % of spot (Black-Scholes).

    strike_pct negative = OTM put: -7.5 → K = spot * 0.925.
    """
    S = 1.0
    K = max(0.01, 1.0 + strike_pct / 100.0)
    T = t_months / 12.0
    sigma = max(0.001, vol_annual_pct / 100.0)
    try:
        d1 = (math.log(S / K) + (r + sigma ** 2 / 2.0) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        put = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
        return round(max(0.0, put * 100), 3)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _bs_call_pct(
    vol_annual_pct: float,
    strike_pct: float,
    r: float = 0.065,
    t_months: float = 12.0,
) -> float:
    """OTM call premium as % of spot (Black-Scholes).

    strike_pct positive = OTM call: +7.5 → K = spot * 1.075.
    Represents the income a call seller receives.
    """
    S = 1.0
    K = max(0.01, 1.0 + strike_pct / 100.0)
    T = t_months / 12.0
    sigma = max(0.001, vol_annual_pct / 100.0)
    try:
        d1 = (math.log(S / K) + (r + sigma ** 2 / 2.0) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        call = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
        return round(max(0.0, call * 100), 3)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _risk_score(ann_vol_pct: float) -> int:
    if ann_vol_pct < 15:
        return 1
    if ann_vol_pct < 25:
        return 2
    if ann_vol_pct < 35:
        return 3
    if ann_vol_pct < 50:
        return 4
    return 5


def _coverage_params(
    coverage: int,
    vol_annual_pct: float,
    hedge_type: str,
    allocation_pct: float,
    t_months: float = 12.0,
) -> tuple[float, str, float, int, float]:
    """Return (strike_pct, strike_label, cost_pct, protected_pct, call_sell_cost_pct)."""
    c = coverage / 100.0
    is_spread = hedge_type == "put_spread"
    corr = 0.72 if hedge_type == "nifty_proxy" else (0.65 if hedge_type == "ndx_proxy" else 1.0)

    # Strike: lerp −15% OTM (c=0) → −2% OTM (c=1)
    strike_pct = -15.0 + c * 13.0

    if is_spread:
        lo = round(strike_pct, 1)
        hi = round(strike_pct - 6.0, 1)
        strike_label = f"{lo:+.0f}/{hi:+.0f}%"
        cost_pct = max(
            0.0,
            _bs_put_pct(vol_annual_pct, lo, t_months=t_months)
            - _bs_put_pct(vol_annual_pct, hi, t_months=t_months),
        )
        call_sell_cost_pct = round(
            _bs_call_pct(vol_annual_pct, abs(lo), t_months=t_months) * corr, 3
        )
    else:
        strike_label = f"{strike_pct:+.1f}% OTM"
        raw_put = _bs_put_pct(vol_annual_pct, strike_pct, t_months=t_months)
        cost_pct = round(raw_put * corr, 3)
        raw_call = _bs_call_pct(vol_annual_pct, abs(strike_pct), t_months=t_months)
        call_sell_cost_pct = round(raw_call * corr, 3)

    base_protected = 35 + int(c * 45)
    spread_discount = 0.80 if is_spread else 1.0
    protected_pct = min(95, int(base_protected * corr * spread_discount))

    return strike_pct, strike_label, cost_pct, protected_pct, call_sell_cost_pct


# ── Endpoint ──────────────────────────────────────────────────────────────────
@router.get("/portfolio-hedge", response_model=PortfolioHedgeResponse)
def get_portfolio_hedge(
    coverage: int = Query(default=50, ge=0, le=100, description="Coverage level 0–100 %"),
    duration: str = Query(default="1y", pattern="^(1m|3m|1y)$", description="Option tenor: 1m | 3m | 1y"),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortfolioHedgeResponse:
    """Compute hedge parameters for the saved portfolio at given coverage and duration.

    Returns ann_vol_pct and call_sell_cost_pct per holding so the Selection and
    Allocation wizard tabs can show Put Buy vs Sell Call comparison with σ-anchored
    scenarios. Read-only — no db.commit().
    """
    t_months = _DURATION_MONTHS.get(duration, 12.0)

    key = UserPortfolioKeyRepo(db).find_by_user_id(current_user.id)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active portfolio found")
    portfolio = UserPortfolioRepo(db).find_active_by_key_id(key.key_id)
    if portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active portfolio found")

    holdings_raw: list[HoldingItem] = [
        HoldingItem(**h) if isinstance(h, dict) else h
        for h in (portfolio.holdings or [])
    ]
    if not holdings_raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio has no holdings")

    all_records = MarketDataCacheRepository(db).read_all()
    from collections import defaultdict
    by_inst: dict[str, list] = defaultdict(list)
    for rec in all_records:
        by_inst[rec.underlying.upper()].append(rec)

    def _vol_and_return(inst_id: str) -> tuple[float, Optional[float], int]:
        recs = sorted(by_inst.get(inst_id, []), key=lambda r: r.date)
        closes = [float(r.close) for r in recs[-253:] if r.close]
        if len(closes) < 20:
            return 25.0, None, 2
        daily_rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
        ann_vol = statistics.stdev(daily_rets) * (252 ** 0.5) * 100
        idx_1y = max(0, len(recs) - 253)
        close_1y = float(recs[idx_1y].close) if recs[idx_1y].close else None
        return_1y = (
            round((closes[-1] / close_1y - 1) * 100, 2)
            if close_1y and close_1y != 0
            else None
        )
        return round(ann_vol, 2), return_1y, _risk_score(ann_vol)

    result_holdings: list[HedgeHolding] = []
    for h in holdings_raw:
        inst_id = h.instrument_id.upper()
        alloc = float(h.allocation_pct)

        eligible = inst_id in _FNO_ELIGIBLE
        if eligible:
            hedge_type = "put_spread" if alloc >= 20 else "protective_put"
        elif h.instrument_id.endswith(".NS") or inst_id in {"NIFTY", "BANKNIFTY"}:
            hedge_type = "nifty_proxy"
        else:
            hedge_type = (
                "ndx_proxy"
                if len(inst_id) <= 5 and inst_id.isalpha() and inst_id not in _FNO_ELIGIBLE
                else "nifty_proxy"
            )

        vol, return_1y, rs = _vol_and_return(inst_id)
        strike_pct, strike_label, cost_pct, protected_pct, call_sell_cost_pct = _coverage_params(
            coverage, vol, hedge_type, alloc, t_months
        )

        result_holdings.append(HedgeHolding(
            instrument_id=inst_id,
            weight=alloc,
            return_1y_pct=return_1y,
            risk_score=rs,
            hedge_type=hedge_type,
            eligible=eligible,
            strike_pct=round(strike_pct, 2),
            strike_label=strike_label,
            cost_pct=cost_pct,
            protected_pct=protected_pct,
            ann_vol_pct=round(vol, 2),
            call_sell_cost_pct=call_sell_cost_pct,
            duration=duration,
        ))

    total_weight = sum(h.weight for h in result_holdings) or 1.0
    avg_strike = sum(h.strike_pct * h.weight / total_weight for h in result_holdings)
    monthly_cost = sum(h.cost_pct * h.weight / total_weight for h in result_holdings)
    max_dd_hedged = round(avg_strike - monthly_cost, 2)
    max_dd_unhedged = round(-15.0 - (1 - coverage / 100) * 7, 2)

    return PortfolioHedgeResponse(
        holdings=result_holdings,
        aggregate=HedgeAggregate(
            max_dd_protected_pct=max_dd_hedged,
            max_dd_unhedged_pct=max_dd_unhedged,
            monthly_cost_pct=round(monthly_cost, 3),
        ),
        coverage=coverage,
        duration=duration,
    )
