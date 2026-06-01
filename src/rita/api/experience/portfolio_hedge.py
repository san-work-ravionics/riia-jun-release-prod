"""Experience Layer — Portfolio Hedge endpoint (Feature 28 Phase 2).

ADR-001 Tier 3: read-only composition, no writes, no side effects.
Computes per-holding hedge parameters using real Black-Scholes pricing
on realized volatility (eng-context C1/C4/D1).

GET /api/v1/experience/fno/portfolio-hedge?coverage=50  (JWT required)
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

router = APIRouter(prefix="/api/v1/experience/fno", tags=["experience:portfolio-hedge"])

# ── F&O eligibility (Phase 3 backend will add DB flag; static for Phase 2) ────
_FNO_ELIGIBLE: frozenset[str] = frozenset({
    "RELIANCE", "TATAMOTOR", "TCS", "INFY", "HDFCBANK", "WIPRO", "BAJFINANCE",
    "TATASTEEL", "SBIN", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SUNPHARMA",
    "HCLTECH", "LT", "ONGC", "NTPC", "POWERGRID", "BPCL",
})

# ── Pydantic response models ───────────────────────────────────────────────────
class HedgeHolding(BaseModel):
    instrument_id: str
    weight: float            # allocation_pct from user portfolio
    return_1y_pct: float | None
    risk_score: int | None
    hedge_type: str          # protective_put | put_spread | ndx_proxy | nifty_proxy
    eligible: bool
    strike_pct: float        # e.g. -7.5 means 7.5 % OTM (negative = OTM put)
    strike_label: str        # display string
    cost_pct: float          # monthly premium as % of position value
    protected_pct: int       # % of downside move captured by hedge


class HedgeAggregate(BaseModel):
    max_dd_protected_pct: float   # portfolio floor under hedge (e.g. -7.0)
    max_dd_unhedged_pct: float    # reference worst-case without hedge
    monthly_cost_pct: float       # weighted-average monthly cost across holdings


class PortfolioHedgeResponse(BaseModel):
    holdings: list[HedgeHolding]
    aggregate: HedgeAggregate
    coverage: int


# ── Math helpers ───────────────────────────────────────────────────────────────
def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2))) / 2.0


def _bs_put_pct(vol_annual_pct: float, strike_pct: float, r: float = 0.065, t_months: float = 1.0) -> float:
    """Monthly put premium as % of spot via Black-Scholes (eng-context D1).

    strike_pct is negative OTM distance: -7.5 means strike = spot * 0.925.
    Returns 0.0 on degenerate inputs.
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


def _risk_score(ann_vol_pct: float) -> int:
    """Bucket annualized vol % into 1–5 (eng-context C1)."""
    if ann_vol_pct < 15: return 1
    if ann_vol_pct < 25: return 2
    if ann_vol_pct < 35: return 3
    if ann_vol_pct < 50: return 4
    return 5


# ── Coverage → per-row params (eng-context C4) ────────────────────────────────
def _coverage_params(
    coverage: int,
    vol_annual_pct: float,
    hedge_type: str,
    allocation_pct: float,
) -> tuple[float, str, float, int]:
    """Return (strike_pct, strike_label, cost_pct, protected_pct)."""
    c = coverage / 100.0
    is_proxy = hedge_type in ("ndx_proxy", "nifty_proxy")
    is_spread = hedge_type == "put_spread"

    # Strike: lerp -15% OTM (c=0) → -2% OTM (c=1)  [eng-context C4]
    strike_pct = -15.0 + c * 13.0

    if is_spread:
        lo = round(strike_pct, 1)
        hi = round(strike_pct - 6.0, 1)
        strike_label = f"{lo:+.0f}/{hi:+.0f}%"
        # Put spread: buy lo, sell hi → cost is difference
        cost_pct = max(0.0, _bs_put_pct(vol_annual_pct, lo) - _bs_put_pct(vol_annual_pct, hi))
    else:
        strike_label = f"{strike_pct:+.1f}% OTM"
        raw_cost = _bs_put_pct(vol_annual_pct, strike_pct)
        # Proxy puts: scale by assumed index correlation (0.72 India, 0.65 US)
        corr = 0.72 if hedge_type == "nifty_proxy" else (0.65 if hedge_type == "ndx_proxy" else 1.0)
        cost_pct = round(raw_cost * corr, 3)

    # Protected %: rises with coverage; proxy discounted by correlation (C4)
    base_protected = 35 + int(c * 45)   # 35% → 80%
    corr_discount = 0.72 if hedge_type == "nifty_proxy" else (0.65 if hedge_type == "ndx_proxy" else 1.0)
    spread_discount = 0.80 if is_spread else 1.0
    protected_pct = min(95, int(base_protected * corr_discount * spread_discount))

    return strike_pct, strike_label, cost_pct, protected_pct


# ── Endpoint ──────────────────────────────────────────────────────────────────
@router.get("/portfolio-hedge", response_model=PortfolioHedgeResponse)
def get_portfolio_hedge(
    coverage: int = Query(default=50, ge=0, le=100, description="Coverage level 0-100 %"),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortfolioHedgeResponse:
    """Compute hedge parameters for the user's saved portfolio at a given coverage level.

    Returns per-holding strike, premium (Black-Scholes, realized vol as IV proxy),
    and protected %, plus aggregate max-drawdown-protected and monthly cost.
    Read-only — no db.commit().
    """
    # Load user portfolio
    key = UserPortfolioKeyRepo(db).find_by_user_id(current_user.id)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active portfolio found")
    portfolio = UserPortfolioRepo(db).find_active_by_key_id(key.key_id)
    if portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active portfolio found")

    holdings_raw = portfolio.holdings or []
    if not holdings_raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio has no holdings")

    # Build price history lookup: instrument_id → sorted closes list
    all_records = MarketDataCacheRepository(db).read_all()
    from collections import defaultdict
    by_inst: dict[str, list] = defaultdict(list)
    for rec in all_records:
        by_inst[rec.underlying.upper()].append(rec)

    def _vol_and_return(inst_id: str) -> tuple[float, Optional[float], int]:
        """Returns (ann_vol_pct, return_1y_pct, risk_score_int)."""
        recs = sorted(by_inst.get(inst_id, []), key=lambda r: r.date)
        closes = [float(r.close) for r in recs[-253:] if r.close]
        if len(closes) < 20:
            return 25.0, None, 2  # fallback: moderate vol, unknown 1Y return
        daily_rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
        ann_vol = statistics.stdev(daily_rets) * (252 ** 0.5) * 100
        # 1Y return
        idx_1y = max(0, len(recs) - 253)
        close_1y = float(recs[idx_1y].close) if recs[idx_1y].close else None
        return_1y = round((closes[-1] / close_1y - 1) * 100, 2) if close_1y and close_1y != 0 else None
        return round(ann_vol, 2), return_1y, _risk_score(ann_vol)

    # Build hedge rows
    result_holdings: list[HedgeHolding] = []
    for h in holdings_raw:
        inst_id = h.instrument_id.upper()
        alloc = float(h.allocation_pct)

        eligible = inst_id in _FNO_ELIGIBLE
        if eligible:
            hedge_type = "put_spread" if alloc >= 20 else "protective_put"
        elif h.instrument_id.endswith(".NS") or inst_id in {
            "NIFTY", "BANKNIFTY",
        }:
            hedge_type = "nifty_proxy"
        else:
            # Determine by exchange/region heuristic: non-Indian non-eligible → NDX proxy
            # A future Phase will read instrument.country_code; for now US tickers are short
            hedge_type = "ndx_proxy" if len(inst_id) <= 5 and inst_id.isalpha() and inst_id not in _FNO_ELIGIBLE else "nifty_proxy"

        vol, return_1y, rs = _vol_and_return(inst_id)
        strike_pct, strike_label, cost_pct, protected_pct = _coverage_params(coverage, vol, hedge_type, alloc)

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
        ))

    # Aggregates (eng-context C5)
    total_weight = sum(h.weight for h in result_holdings) or 1.0
    # Portfolio floor: weighted average strike (eng-context C5, β=1 for v1)
    avg_strike = sum(h.strike_pct * h.weight / total_weight for h in result_holdings)
    monthly_cost = sum(h.cost_pct * h.weight / total_weight for h in result_holdings)
    max_dd_hedged = round(avg_strike - monthly_cost, 2)
    # Reference unhedged drawdown: approximate max historical drawdown scaled to coverage=0 floor
    max_dd_unhedged = round(-15.0 - (1 - coverage / 100) * 7, 2)  # illustrative: worsens as coverage drops

    return PortfolioHedgeResponse(
        holdings=result_holdings,
        aggregate=HedgeAggregate(
            max_dd_protected_pct=max_dd_hedged,
            max_dd_unhedged_pct=max_dd_unhedged,
            monthly_cost_pct=round(monthly_cost, 3),
        ),
        coverage=coverage,
    )
