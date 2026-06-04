"""Experience Layer — Unified FnO Portfolio Analytics endpoint (F30 Phase 1).

ADR-001 Tier 3: read-only composition, no writes, no side effects.

GET /api/v1/experience/fno/portfolio-analytics?mode=real|mock

- mode=mock  → returns MOCK_PORTFOLIO constant (no auth, no DB calls)
- mode=real  → JWT required; loads portfolio + hedge plan from DB;
               computes greeks, scenarios, payoff, stress, HQS live.

Edge cases handled:
  E1  mode=mock, no JWT → 200 MOCK_PORTFOLIO, zero DB calls
  E2  mode=real, no JWT → 401
  E3  mode=real, valid JWT, no portfolio key → 404
  E4  mode=real, valid JWT, no active portfolio → 404
  E5  mode=real, portfolio exists, no hedge plan → delta=1.0, theta/vega/gamma=0
  E6  instrument absent from market_data_cache → fallback vol 25 %, ltp=0
  E7  portfolio with empty holdings list → 200 with empty arrays/dicts
  E8  total_value_eur is None → default 0
  E9  invalid mode value → 422 (FastAPI Literal validation)
  E10 math domain error (sigma≈0, S/K) → try/except, return 0.0
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from scipy.stats import norm
from sqlalchemy.orm import Session

from rita.auth import get_optional_user
from rita.database import get_db
from rita.models.user import UserModel
from rita.repositories.market_data import MarketDataCacheRepository
from rita.repositories.user_hedge_plan import UserHedgePlanRepo
from rita.repositories.user_portfolio import UserPortfolioRepo
from rita.repositories.user_portfolio_key import UserPortfolioKeyRepo
from rita.schemas.portfolio_analytics import (
    GreekItemSchema,
    HedgeQualityPositionSchema,
    HedgeQualitySchema,
    MarketEntrySchema,
    NetGreeksSchema,
    PayoffCurveSchema,
    PayoffSchema,
    PortfolioAnalyticsResponse,
    PortfolioMetaSchema,
    PositionItemSchema,
    ScenarioLevelSchema,
    StressEventSchema,
)
from rita.schemas.user_portfolio import HoldingItem

log = structlog.get_logger()

router = APIRouter(
    prefix="/api/v1/experience/fno",
    tags=["experience:portfolio-analytics"],
)

# ---------------------------------------------------------------------------
# Static reference data
# ---------------------------------------------------------------------------

_INSTRUMENT_META: dict[str, dict] = {
    "NIFTY":     {"full": "Nifty 50 Index",              "currency": "INR", "region": "India"},
    "BANKNIFTY": {"full": "Bank Nifty Index",             "currency": "INR", "region": "India"},
    "ASML":      {"full": "ASML Holding N.V.",            "currency": "EUR", "region": "EU"},
    "NVIDIA":    {"full": "NVIDIA Corporation",           "currency": "USD", "region": "US"},
    "RELIANCE":  {"full": "Reliance Industries",          "currency": "INR", "region": "India"},
    "HDFCBANK":  {"full": "HDFC Bank",                    "currency": "INR", "region": "India"},
    "TCS":       {"full": "Tata Consultancy Services",    "currency": "INR", "region": "India"},
    "INFY":      {"full": "Infosys Limited",              "currency": "INR", "region": "India"},
}

_DEFAULT_REGION = "Other"
_DEFAULT_CURRENCY = "INR"
_FALLBACK_VOL_PCT = 25.0
_RISK_FREE_RATE = 0.05
_TENOR_YEARS = 1.0

STRESS_EVENTS = [
    {"label": "2008 Crisis",    "move_pct": -50},
    {"label": "COVID-2020",     "move_pct": -35},
    {"label": "Rate Hike 2022", "move_pct": -20},
    {"label": "Tech Rally",     "move_pct": +25},
    {"label": "India Slowdown", "move_pct": -15},
]

# ---------------------------------------------------------------------------
# Mock data constant (zero DB calls — must remain a plain Python dict)
# ---------------------------------------------------------------------------

MOCK_PORTFOLIO: dict = {
    "mode": "mock",
    "portfolio_meta": {
        "name": "Demo Portfolio",
        "total_value_eur": 50000,
        "updated_at": "2026-01-01T00:00:00",
    },
    "market": {
        "NIFTY": {
            "close": 24200.0, "open": 24000.0, "high": 24300.0, "low": 23900.0,
            "prevClose": 23800.0, "chgFromOpen": 0.8, "chgFromPrev": 1.7,
            "date": "2026-01-01", "shares": "—", "turnover": 0.0, "currency": None,
        },
        "BANKNIFTY": {
            "close": 52100.0, "open": 52260.0, "high": 52500.0, "low": 51800.0,
            "prevClose": 51900.0, "chgFromOpen": -0.3, "chgFromPrev": 0.4,
            "date": "2026-01-01", "shares": "—", "turnover": 0.0, "currency": None,
        },
        "ASML": {
            "close": 890.5, "open": 880.0, "high": 895.0, "low": 875.0,
            "prevClose": 870.0, "chgFromOpen": 1.2, "chgFromPrev": 2.4,
            "date": "2026-01-01", "shares": "—", "turnover": 0.0, "currency": "EUR",
        },
        "NVIDIA": {
            "close": 132.4, "open": 129.5, "high": 133.0, "low": 128.0,
            "prevClose": 128.0, "chgFromOpen": 2.1, "chgFromPrev": 3.4,
            "date": "2026-01-01", "shares": "—", "turnover": 0.0, "currency": "USD",
        },
    },
    "positions": [
        {
            "und": "NIFTY", "full": "Nifty 50 Index", "exp": "EQUITY",
            "type": "EQ", "side": "Long", "qty": 1,
            "allocation_pct": 30.0, "position_eur": 15000.0,
            "avg": 24200.0, "ltp": 24200.0, "chg": 1.7, "pnl": 0.0,
            "currency": "INR", "ann_vol_pct": 18.4, "region": "India",
        },
        {
            "und": "BANKNIFTY", "full": "Bank Nifty Index", "exp": "EQUITY",
            "type": "EQ", "side": "Long", "qty": 1,
            "allocation_pct": 20.0, "position_eur": 10000.0,
            "avg": 52100.0, "ltp": 52100.0, "chg": 0.4, "pnl": 0.0,
            "currency": "INR", "ann_vol_pct": 22.1, "region": "India",
        },
        {
            "und": "ASML", "full": "ASML Holding N.V.", "exp": "EQUITY",
            "type": "EQ", "side": "Long", "qty": 1,
            "allocation_pct": 20.0, "position_eur": 10000.0,
            "avg": 890.5, "ltp": 890.5, "chg": 2.4, "pnl": 0.0,
            "currency": "EUR", "ann_vol_pct": 31.0, "region": "EU",
        },
        {
            "und": "NVIDIA", "full": "NVIDIA Corporation", "exp": "EQUITY",
            "type": "EQ", "side": "Long", "qty": 1,
            "allocation_pct": 25.0, "position_eur": 12500.0,
            "avg": 132.4, "ltp": 132.4, "chg": 3.4, "pnl": 0.0,
            "currency": "USD", "ann_vol_pct": 44.5, "region": "US",
        },
        {
            "und": "TRU", "full": "Tata Resources Unlisted", "exp": "EQUITY",
            "type": "EQ", "side": "Long", "qty": 1,
            "allocation_pct": 5.0, "position_eur": 2500.0,
            "avg": 410.0, "ltp": 410.0, "chg": 0.8, "pnl": 0.0,
            "currency": "INR", "ann_vol_pct": 28.0, "region": "India",
        },
    ],
    "greeks": [
        {
            "und": "NIFTY", "exp": "EQUITY", "hedge_type": "protective_put",
            "delta": 0.52, "gamma": 0.0002, "theta": -12.3, "vega": 8.1,
            "allocation_pct": 30.0, "ann_vol_pct": 18.4,
            "sigma_eur": 2760.0, "net_theta_eur_day": -12.3,
            "put_cost_eur": 450.0, "call_income_eur": 320.0,
        },
        {
            "und": "BANKNIFTY", "exp": "EQUITY", "hedge_type": "protective_put",
            "delta": 0.55, "gamma": 0.0001, "theta": -9.8, "vega": 6.2,
            "allocation_pct": 20.0, "ann_vol_pct": 22.1,
            "sigma_eur": 2210.0, "net_theta_eur_day": -9.8,
            "put_cost_eur": 310.0, "call_income_eur": 220.0,
        },
        {
            "und": "ASML", "exp": "EQUITY", "hedge_type": "ndx_proxy",
            "delta": 1.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0,
            "allocation_pct": 20.0, "ann_vol_pct": 31.0,
            "sigma_eur": 3100.0, "net_theta_eur_day": 0.0,
            "put_cost_eur": None, "call_income_eur": None,
        },
        {
            "und": "NVIDIA", "exp": "EQUITY", "hedge_type": "ndx_proxy",
            "delta": 1.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0,
            "allocation_pct": 25.0, "ann_vol_pct": 44.5,
            "sigma_eur": 5562.5, "net_theta_eur_day": 0.0,
            "put_cost_eur": None, "call_income_eur": None,
        },
    ],
    "net_greeks": {"delta": 0.81, "theta": -22.1, "vega": 14.3},
    "net_delta": {
        "NIFTY": 0.52, "BANKNIFTY": 0.55, "ASML": 1.0, "NVIDIA": 1.0,
    },
    "scenario_levels": {
        "NIFTY":     {"target": 26649.0, "sl": 15503.0},
        "BANKNIFTY": {"target": 57632.0, "sl": 33344.0},
        "ASML":      {"target": 1167.0,  "sl": 508.0},
        "NVIDIA":    {"target": 191.3,   "sl": 47.6},
    },
    "payoff": {
        "portfolio": {
            "labels": [-30.0, -27.0, -24.0, -21.0, -18.0, -15.0, -12.0, -9.0, -6.0,
                       -3.0, 0.0, 3.0, 6.0, 9.0, 12.0, 15.0, 18.0, 21.0, 24.0, 27.0, 30.0],
            "data": [-15000, -13500, -12000, -10500, -9000, -7500, -6000, -4500, -3000,
                     -1500, 0, 1500, 3000, 4500, 6000, 7500, 9000, 10500, 12000, 13500, 15000],
        },
        "hedged": {
            "labels": [-30.0, -27.0, -24.0, -21.0, -18.0, -15.0, -12.0, -9.0, -6.0,
                       -3.0, 0.0, 3.0, 6.0, 9.0, 12.0, 15.0, 18.0, 21.0, 24.0, 27.0, 30.0],
            "data": [-11250, -10125, -9000, -7875, -6750, -5625, -4500, -4500, -3000,
                     -1500, 0, 1500, 3000, 4500, 6000, 7500, 9000, 10500, 12000, 13500, 15000],
        },
    },
    "stress": [
        {"label": "2008 Crisis",    "move_pct": -50, "portfolio_pnl_eur": -25000, "hedged_pnl_eur": -18750},
        {"label": "COVID-2020",     "move_pct": -35, "portfolio_pnl_eur": -17500, "hedged_pnl_eur": -13125},
        {"label": "Rate Hike 2022", "move_pct": -20, "portfolio_pnl_eur": -10000, "hedged_pnl_eur": -7500},
        {"label": "Tech Rally",     "move_pct":  25, "portfolio_pnl_eur":  12500, "hedged_pnl_eur":  12500},
        {"label": "India Slowdown", "move_pct": -15, "portfolio_pnl_eur":  -7500, "hedged_pnl_eur":  -5625},
    ],
    "hedge_quality": {
        "positions": [
            {"instrument": "NIFTY",     "hqs": 75, "hqs_tier": "green",  "hedged": True,  "strategy": "protective_put", "coverage_pct": 50, "note": None},
            {"instrument": "BANKNIFTY", "hqs": 75, "hqs_tier": "green",  "hedged": True,  "strategy": "protective_put", "coverage_pct": 50, "note": None},
            {"instrument": "ASML",      "hqs": 5,  "hqs_tier": "red",    "hedged": False, "strategy": None,             "coverage_pct": None, "note": "No hedge assigned"},
            {"instrument": "NVIDIA",    "hqs": 5,  "hqs_tier": "red",    "hedged": False, "strategy": None,             "coverage_pct": None, "note": "No hedge assigned"},
        ],
    },
    "closed_positions": [],
    "realized_pnl": 0.0,
    "margin": {},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vol_from_cache(inst_id: str, by_inst: dict) -> float:
    """Compute annualised realised vol (%) from market_data_cache records.

    Mirrors _vol_and_return() logic in portfolio_hedge.py.
    Falls back to _FALLBACK_VOL_PCT when fewer than 20 data points exist.
    """
    recs = sorted(by_inst.get(inst_id.upper(), []), key=lambda r: r.date)
    closes = [float(r.close) for r in recs[-253:] if r.close]
    if len(closes) < 20:
        return _FALLBACK_VOL_PCT
    daily_rets = [
        (closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))
    ]
    ann_vol = statistics.stdev(daily_rets) * (252 ** 0.5) * 100
    return round(ann_vol, 2)


def _latest_close(inst_id: str, by_inst: dict) -> Optional[float]:
    """Return the most-recent close price for an instrument, or None."""
    recs = sorted(by_inst.get(inst_id.upper(), []), key=lambda r: r.date)
    if not recs:
        return None
    rec = recs[-1]
    return float(rec.close) if rec.close else None


def _build_market_entry(inst_id: str, by_inst: dict) -> MarketEntrySchema:
    """Build a MarketEntrySchema from the two most-recent cache rows."""
    meta = _INSTRUMENT_META.get(inst_id.upper(), {})
    recs = sorted(by_inst.get(inst_id.upper(), []), key=lambda r: r.date)
    if not recs:
        return MarketEntrySchema(
            close=0.0, open=0.0, high=0.0, low=0.0, prevClose=None,
            chgFromOpen=None, chgFromPrev=None,
            date="", shares="—", turnover=None,
            currency=meta.get("currency"),
        )
    latest = recs[-1]
    prev = recs[-2] if len(recs) >= 2 else None
    close = float(latest.close) if latest.close else 0.0
    open_ = float(latest.open) if latest.open else 0.0
    prev_close = float(prev.close) if (prev and prev.close) else None
    chg_from_open = round((close - open_) / open_ * 100, 2) if open_ else None
    chg_from_prev = (
        round((close - prev_close) / prev_close * 100, 2)
        if prev_close
        else None
    )
    return MarketEntrySchema(
        close=close,
        open=open_,
        high=float(latest.high) if latest.high else None,
        low=float(latest.low) if latest.low else None,
        prevClose=prev_close,
        chgFromOpen=chg_from_open,
        chgFromPrev=chg_from_prev,
        date=str(latest.date),
        shares=str(latest.shares_traded) if latest.shares_traded else "—",
        turnover=float(latest.turnover_cr) if latest.turnover_cr else None,
        currency=meta.get("currency"),
    )


def _compute_greeks_for_holding(
    instrument_id: str,
    allocation_pct: float,
    position_eur: float,
    ann_vol: float,
    hedged: bool,
    coverage_pct: int,
    hedge_type: str,
    ltp: float,
) -> GreekItemSchema:
    """Compute per-holding Greeks using Black-Scholes.

    Implements eng-context C2 formulas. Returns equity delta=1.0 with zero
    Greeks when the instrument is not hedged or on math domain errors.
    """
    sigma = max(0.001, ann_vol / 100.0)
    sigma_eur = round(position_eur * sigma * math.sqrt(_TENOR_YEARS), 2)

    if not hedged or ltp <= 0:
        return GreekItemSchema(
            und=instrument_id, exp="EQUITY", hedge_type=hedge_type,
            delta=1.0, gamma=0.0, theta=0.0, vega=0.0,
            allocation_pct=allocation_pct, ann_vol_pct=ann_vol,
            sigma_eur=sigma_eur, net_theta_eur_day=0.0,
            put_cost_eur=None, call_income_eur=None,
        )

    S = ltp
    K = S * (1.0 - coverage_pct / 100.0)
    K = max(0.01, K)
    T = _TENOR_YEARS
    r = _RISK_FREE_RATE

    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        # Net delta: equity + put hedge
        put_delta = norm.cdf(d1) - 1.0
        net_delta = 1.0 + put_delta

        # Theta (EUR/day) — negative cost for long put
        put_theta = -(
            S * norm.pdf(d1) * sigma / (2.0 * math.sqrt(T))
            + r * K * math.exp(-r * T) * norm.cdf(-d2)
        ) / 365.0
        theta_eur_day = put_theta * position_eur / S

        # Vega (EUR per 1 % IV move)
        vega_per_pct = S * norm.pdf(d1) * math.sqrt(T) * 0.01
        vega_eur = vega_per_pct * position_eur / S

        # Gamma
        gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))

        # Put cost EUR (ATM put, 1y, full position)
        atm_put_prem_pct = max(
            0.0,
            K * math.exp(-r * T) * norm.cdf(-(d2)) - S * norm.cdf(-d1),
        )
        put_cost_eur = round(position_eur * atm_put_prem_pct / S, 2)

        # Symmetric OTM call income (call at same distance above spot)
        K_call = S * (1.0 + coverage_pct / 100.0)
        try:
            d1c = (math.log(S / K_call) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
            d2c = d1c - sigma * math.sqrt(T)
            call_prem = max(0.0, S * norm.cdf(d1c) - K_call * math.exp(-r * T) * norm.cdf(d2c))
            call_income_eur = round(position_eur * call_prem / S, 2)
        except (ValueError, ZeroDivisionError):
            call_income_eur = None

        return GreekItemSchema(
            und=instrument_id,
            exp="EQUITY",
            hedge_type=hedge_type,
            delta=round(float(net_delta), 4),
            gamma=round(float(gamma), 6),
            theta=round(float(put_theta), 4),
            vega=round(float(vega_eur), 2),
            allocation_pct=allocation_pct,
            ann_vol_pct=ann_vol,
            sigma_eur=sigma_eur,
            net_theta_eur_day=round(float(theta_eur_day), 4),
            put_cost_eur=put_cost_eur,
            call_income_eur=call_income_eur,
        )

    except (ValueError, ZeroDivisionError, OverflowError):
        log.warning("portfolio_analytics.greeks_error", instrument=instrument_id)
        return GreekItemSchema(
            und=instrument_id, exp="EQUITY", hedge_type=hedge_type,
            delta=1.0, gamma=0.0, theta=0.0, vega=0.0,
            allocation_pct=allocation_pct, ann_vol_pct=ann_vol,
            sigma_eur=sigma_eur, net_theta_eur_day=0.0,
            put_cost_eur=None, call_income_eur=None,
        )


def _build_scenarios(
    holdings: list[HoldingItem],
    vol_map: dict[str, float],
    spot_map: dict[str, float],
    total_value_eur: float,
) -> dict[str, ScenarioLevelSchema]:
    """Compute σ-anchored scenario levels per instrument.

    target = spot × (1 + 1σ),  sl = spot × (1 − 2σ).
    Only instruments present in spot_map are included.
    """
    result: dict[str, ScenarioLevelSchema] = {}
    for h in holdings:
        inst = h.instrument_id.upper()
        spot = spot_map.get(inst)
        if spot is None or spot <= 0:
            continue
        ann_vol = vol_map.get(inst, _FALLBACK_VOL_PCT) / 100.0
        result[inst] = ScenarioLevelSchema(
            target=round(spot * (1.0 + ann_vol), 2),
            sl=round(spot * (1.0 - 2.0 * ann_vol), 2),
        )
    return result


def _build_payoff(
    total_value_eur: float,
    hedged_alloc_eur: float,
    coverage_pct: int,
) -> PayoffSchema:
    """Build a 21-point payoff grid (±30 % range) for portfolio and hedged curves.

    Implements eng-context C4.
    """
    spot_ref = 1.0
    grid = [spot_ref * (0.70 + i * 0.03) for i in range(21)]
    unhedged = [total_value_eur * g for g in grid]
    hedged_values = []
    for g in grid:
        drop = max(0.0, spot_ref - g)
        hedge_gain = (coverage_pct / 100.0) * hedged_alloc_eur * drop if drop > 0 else 0.0
        hedged_values.append(total_value_eur * g + hedge_gain)

    labels = [round(g * 100.0 - 100.0, 1) for g in grid]
    return PayoffSchema(
        portfolio=PayoffCurveSchema(
            labels=labels,
            data=[round(v - total_value_eur) for v in unhedged],
        ),
        hedged=PayoffCurveSchema(
            labels=labels,
            data=[round(v - total_value_eur) for v in hedged_values],
        ),
    )


def _build_stress(
    total_value_eur: float,
    hedged_alloc_eur: float,
    coverage_pct: int,
) -> list[StressEventSchema]:
    """Apply five hardcoded stress events to the portfolio.

    Implements eng-context C5.
    """
    output: list[StressEventSchema] = []
    for ev in STRESS_EVENTS:
        move = ev["move_pct"] / 100.0
        unh_pnl = total_value_eur * move
        hedge_gain = 0.0
        if move < 0 and hedged_alloc_eur > 0:
            hedge_gain = hedged_alloc_eur * abs(move) * (coverage_pct / 100.0) * 0.5
        output.append(
            StressEventSchema(
                label=ev["label"],
                move_pct=ev["move_pct"],
                portfolio_pnl_eur=round(unh_pnl),
                hedged_pnl_eur=round(unh_pnl + hedge_gain),
            )
        )
    return output


def _compute_hqs(
    instrument_id: str,
    hedged: bool,
    ann_vol_pct: float,
    put_cost_pct: float,
    coverage_pct: int,
) -> tuple[int, str]:
    """Compute Hedge Quality Score (0–100) and tier label.

    Implements eng-context C6.
    Returns (hqs, tier) where tier is 'green' | 'yellow' | 'red'.
    """
    score = 0

    # Component 1: Is hedged (40 pts)
    score += 40 if hedged else 0

    # Component 2: Cost vs risk (30 pts)
    if put_cost_pct < ann_vol_pct * 0.5:
        score += 30
    elif put_cost_pct < ann_vol_pct * 1.0:
        score += 15
    else:
        score += 5

    # Component 3: Coverage match (30 pts)
    if 40 <= coverage_pct <= 70:
        score += 30
    elif (20 <= coverage_pct < 40) or (70 < coverage_pct <= 90):
        score += 15
    else:
        score += 5

    tier = "green" if score >= 70 else ("yellow" if score >= 40 else "red")
    return score, tier


# ---------------------------------------------------------------------------
# Hedge-type classifier (mirrors portfolio_hedge.py logic)
# ---------------------------------------------------------------------------

_FNO_ELIGIBLE: frozenset[str] = frozenset({
    "RELIANCE", "TATAMOTOR", "TCS", "INFY", "HDFCBANK", "WIPRO", "BAJFINANCE",
    "TATASTEEL", "SBIN", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SUNPHARMA",
    "HCLTECH", "LT", "ONGC", "NTPC", "POWERGRID", "BPCL",
})
_US_INTL_TICKERS: frozenset[str] = frozenset({"NVIDIA", "TRU", "DJI", "IXIC"})


def _hedge_type_for(inst_id: str, alloc: float) -> str:
    if inst_id in _FNO_ELIGIBLE:
        return "put_spread" if alloc >= 20 else "protective_put"
    if inst_id.endswith(".NS") or inst_id in {"NIFTY", "BANKNIFTY"}:
        return "protective_put"
    if inst_id in _US_INTL_TICKERS or (
        len(inst_id) <= 5 and inst_id.isalpha() and inst_id not in _FNO_ELIGIBLE
    ):
        return "ndx_proxy"
    return "nifty_proxy"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/portfolio-analytics", response_model=PortfolioAnalyticsResponse)
def get_portfolio_analytics(
    mode: Literal["real", "mock"] = Query(default="real"),
    current_user: UserModel | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> PortfolioAnalyticsResponse:
    """Unified FnO dashboard analytics payload.

    mode=mock → returns MOCK_PORTFOLIO constant (no auth required, no DB calls used).
    mode=real → JWT required; loads live portfolio and hedge plan from DB.
    """
    # ── E1: mock mode — return constant, ignore DB/auth ──────────────────────
    if mode == "mock":
        return PortfolioAnalyticsResponse(**MOCK_PORTFOLIO)

    # ── E2: real mode without auth ────────────────────────────────────────────
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required for mode=real",
        )

    # ── C1: load portfolio ────────────────────────────────────────────────────
    key = UserPortfolioKeyRepo(db).find_by_user_id(current_user.id)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No portfolio key found",
        )
    portfolio = UserPortfolioRepo(db).find_active_by_key_id(key.key_id)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active portfolio found",
        )

    holdings: list[HoldingItem] = [
        HoldingItem(**h) if isinstance(h, dict) else h
        for h in (portfolio.holdings or [])
    ]
    total_value_eur: float = float(portfolio.total_value_eur or 0.0)

    # E7: empty holdings
    if not holdings:
        empty_payoff = _build_payoff(total_value_eur, 0.0, 50)
        return PortfolioAnalyticsResponse(
            mode="real",
            portfolio_meta=PortfolioMetaSchema(
                name=portfolio.name or "My Portfolio",
                total_value_eur=total_value_eur,
                updated_at=str(portfolio.updated_at),
            ),
            market={},
            positions=[],
            greeks=[],
            net_greeks=NetGreeksSchema(delta=0.0, theta=0.0, vega=0.0),
            net_delta={},
            scenario_levels={},
            payoff=empty_payoff,
            stress=_build_stress(total_value_eur, 0.0, 50),
            hedge_quality=HedgeQualitySchema(positions=[]),
            closed_positions=[],
            realized_pnl=0.0,
            margin={},
        )

    # ── C1 continued: load hedge plan (optional) ─────────────────────────────
    try:
        hedge_plan = UserHedgePlanRepo(db).find_by_key_id(key.key_id)
    except Exception:
        hedge_plan = None

    hedged_ids: set[str] = set(hedge_plan.hedged_ids or []) if hedge_plan else set()
    coverage_pct: int = int(hedge_plan.coverage) if hedge_plan else 50

    # ── E6: load market data ──────────────────────────────────────────────────
    all_records = MarketDataCacheRepository(db).read_all()
    by_inst: dict[str, list] = defaultdict(list)
    for rec in all_records:
        by_inst[rec.underlying.upper()].append(rec)

    # ── Build vol map, spot map, market dict ──────────────────────────────────
    vol_map: dict[str, float] = {}
    spot_map: dict[str, float] = {}
    market: dict[str, MarketEntrySchema] = {}

    for h in holdings:
        inst = h.instrument_id.upper()
        vol_map[inst] = _vol_from_cache(inst, by_inst)
        close = _latest_close(inst, by_inst)
        spot_map[inst] = close if close is not None else 0.0
        market[inst] = _build_market_entry(inst, by_inst)

    # ── Positions ─────────────────────────────────────────────────────────────
    positions: list[PositionItemSchema] = []
    for h in holdings:
        inst = h.instrument_id.upper()
        alloc = float(h.allocation_pct)
        pos_eur = round(alloc / 100.0 * total_value_eur, 2)
        ltp = spot_map.get(inst, 0.0)
        meta = _INSTRUMENT_META.get(inst, {})
        chg_pct = 0.0
        mkt = market.get(inst)
        if mkt and mkt.chgFromPrev is not None:
            chg_pct = mkt.chgFromPrev
        positions.append(
            PositionItemSchema(
                und=inst,
                full=meta.get("full", inst),
                exp="EQUITY",
                type="EQ",
                side="Long",
                qty=1,
                allocation_pct=alloc,
                position_eur=pos_eur,
                avg=ltp,
                ltp=ltp,
                chg=chg_pct,
                pnl=0.0,
                currency=meta.get("currency", _DEFAULT_CURRENCY),
                ann_vol_pct=vol_map.get(inst, _FALLBACK_VOL_PCT),
                region=meta.get("region", _DEFAULT_REGION),
            )
        )

    # ── Greeks ────────────────────────────────────────────────────────────────
    greeks: list[GreekItemSchema] = []
    for h in holdings:
        inst = h.instrument_id.upper()
        alloc = float(h.allocation_pct)
        pos_eur = round(alloc / 100.0 * total_value_eur, 2)
        ann_vol = vol_map.get(inst, _FALLBACK_VOL_PCT)
        ltp = spot_map.get(inst, 0.0)
        hedged = inst in hedged_ids
        hedge_type = _hedge_type_for(inst, alloc)

        greek_item = _compute_greeks_for_holding(
            instrument_id=inst,
            allocation_pct=alloc,
            position_eur=pos_eur,
            ann_vol=ann_vol,
            hedged=hedged,
            coverage_pct=coverage_pct,
            hedge_type=hedge_type,
            ltp=ltp,
        )
        greeks.append(greek_item)

    # ── Net Greeks ────────────────────────────────────────────────────────────
    net_delta_map: dict[str, float] = {}
    sum_delta = sum_theta = sum_vega = 0.0
    for g in greeks:
        w = g.allocation_pct / 100.0
        net_delta_map[g.und] = round(g.delta, 4)
        sum_delta += g.delta * w
        sum_theta += g.net_theta_eur_day
        sum_vega += g.vega

    net_greeks = NetGreeksSchema(
        delta=round(sum_delta, 4),
        theta=round(sum_theta, 4),
        vega=round(sum_vega, 2),
    )

    # ── Scenario levels ───────────────────────────────────────────────────────
    scenario_levels = _build_scenarios(holdings, vol_map, spot_map, total_value_eur)

    # ── Payoff + stress ───────────────────────────────────────────────────────
    hedged_alloc_eur = sum(
        float(h.allocation_pct) / 100.0 * total_value_eur
        for h in holdings
        if h.instrument_id.upper() in hedged_ids
    )
    payoff = _build_payoff(total_value_eur, hedged_alloc_eur, coverage_pct)
    stress = _build_stress(total_value_eur, hedged_alloc_eur, coverage_pct)

    # ── Hedge Quality ─────────────────────────────────────────────────────────
    hq_positions: list[HedgeQualityPositionSchema] = []
    for h in holdings:
        inst = h.instrument_id.upper()
        alloc = float(h.allocation_pct)
        hedged = inst in hedged_ids
        ann_vol = vol_map.get(inst, _FALLBACK_VOL_PCT)
        ltp = spot_map.get(inst, 0.0)

        # Approximate put_cost_pct for HQS cost-vs-risk component
        put_cost_pct = 0.0
        if ltp > 0:
            sigma = max(0.001, ann_vol / 100.0)
            S, K = ltp, ltp * (1.0 - coverage_pct / 100.0)
            T, r = _TENOR_YEARS, _RISK_FREE_RATE
            try:
                d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
                d2 = d1 - sigma * math.sqrt(T)
                put_prem = max(0.0, K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))
                put_cost_pct = put_prem / S * 100.0
            except (ValueError, ZeroDivisionError):
                put_cost_pct = 0.0

        hqs, tier = _compute_hqs(inst, hedged, ann_vol, put_cost_pct, coverage_pct)
        hedge_type = _hedge_type_for(inst, alloc) if hedged else None
        note = None if hedged else "No hedge assigned"

        hq_positions.append(
            HedgeQualityPositionSchema(
                instrument=inst,
                hqs=hqs,
                hqs_tier=tier,
                hedged=hedged,
                strategy=hedge_type,
                coverage_pct=coverage_pct if hedged else None,
                note=note,
            )
        )

    log.info(
        "portfolio_analytics.real",
        user=current_user.id,
        holdings=len(holdings),
        hedged=len(hedged_ids),
        total_eur=total_value_eur,
    )

    return PortfolioAnalyticsResponse(
        mode="real",
        portfolio_meta=PortfolioMetaSchema(
            name=portfolio.name or "My Portfolio",
            total_value_eur=total_value_eur,
            updated_at=str(portfolio.updated_at),
        ),
        market=market,
        positions=positions,
        greeks=greeks,
        net_greeks=net_greeks,
        net_delta=net_delta_map,
        scenario_levels=scenario_levels,
        payoff=payoff,
        stress=stress,
        hedge_quality=HedgeQualitySchema(positions=hq_positions),
        closed_positions=[],
        realized_pnl=0.0,
        margin={},
    )
