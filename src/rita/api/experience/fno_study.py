"""Experience Layer — FnO Rolling Futures Study (BANKNIFTY + NIFTY).

Simulates rolling quarterly futures portfolios from 1 Jan 2025.
Always holds 3 months of futures. Monthly roll: sell expiring, buy new back-month.
Buy price = spot × (1 + basis premium). Basis premium is tiered by months-to-expiry:
same month 0.3%, 1 month out 0.7%, 2+ months out 1.1%. Sell price = spot (basis converges).
Computes quarterly VaR and breach probability at each quarter boundary to show
how risk metrics would have helped.

GET /api/v1/experience/fno/study  (no auth required — read-only study data)
"""
from __future__ import annotations

import csv as _csv
import statistics
from collections import defaultdict
from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rita.config import settings
from rita.database import get_db
from rita.repositories.market_data import MarketDataCacheRepository

router = APIRouter(prefix="/api/v1/experience/fno", tags=["experience:fno-study"])

_START_DATE = date(2025, 1, 1)
_SYMBOLS = ["BANKNIFTY", "NIFTY"]

_PREMIUM_BY_MONTHS_OUT = {0: 0.003, 1: 0.007}
_PREMIUM_DEFAULT = 0.011


def _basis_premium(buy_date: date, contract_year: int, contract_month: int) -> float:
    months_out = (contract_year - buy_date.year) * 12 + (contract_month - buy_date.month)
    pct = _PREMIUM_BY_MONTHS_OUT.get(months_out, _PREMIUM_DEFAULT)
    return 1.0 + pct


class FuturesContract(BaseModel):
    month_label: str
    buy_date: str
    buy_spot: float
    buy_price: float
    sell_date: str | None
    sell_spot: float | None
    sell_price: float | None
    pnl: float | None
    pnl_pct: float | None
    status: str
    hedged_pnl: float | None = None
    data_split: str | None = None


class QuarterSummary(BaseModel):
    quarter: str
    start_date: str
    end_date: str
    contracts_closed: int
    total_pnl: float
    quarterly_var_pct: float | None
    actual_return_pct: float | None
    var_breached: bool | None
    hist_breach_prob_pct: float | None
    hedged_return_pct: float | None = None
    data_split: str | None = None


class InstrumentStudy(BaseModel):
    instrument: str
    start_date: str
    basis_premium_pct: float
    contracts: list[FuturesContract]
    quarters: list[QuarterSummary]
    cumulative_pnl: list[dict]
    total_pnl: float
    total_contracts: int
    quarterly_var_pct: float | None = None
    hist_breach_prob_pct: float | None = None
    quarter_label: str | None = None
    rita_protected_pct: float | None = None
    split_dates: dict | None = None


class MultiStudyResponse(BaseModel):
    studies: list[InstrumentStudy]


def _last_trading_day_of_month(trading_dates: list[date], year: int, month: int) -> date | None:
    candidates = [d for d in trading_dates if d.year == year and d.month == month]
    return max(candidates) if candidates else None


def _first_trading_day_on_or_after(trading_dates: list[date], target: date) -> date | None:
    for d in trading_dates:
        if d >= target:
            return d
    return None


def _quarter_label(d: date) -> str:
    q = (d.month - 1) // 3 + 1
    return f"Q{q}'{str(d.year)[-2:]}"


def _compute_quarterly_var(closes: list[float]) -> tuple[float | None, float | None]:
    if len(closes) < 126:
        return None, None
    qtr_returns = [
        (closes[i] - closes[i - 63]) / closes[i - 63] * 100
        for i in range(63, len(closes))
    ]
    qtr_vol = statistics.stdev(qtr_returns)
    var_1sigma = round(qtr_vol, 2)
    breaches = sum(1 for r in qtr_returns if r < -var_1sigma)
    breach_pct = round(breaches / len(qtr_returns) * 100, 1)
    return var_1sigma, breach_pct


def _hedged_compound(closes: list[float]) -> float:
    """Compound return multiplier with RITA hedge floor applied.

    Floors each daily return at -1.5% and charges 0.36% cost on floored days.
    Returns the multiplier (e.g. 1.05 = +5% over the period).
    """
    if len(closes) < 2:
        return 1.0

    floor = -0.015
    cost = 0.0036
    compound = 1.0

    for i in range(1, len(closes)):
        ret = (closes[i] - closes[i - 1]) / closes[i - 1]
        if ret < floor:
            compound *= (1 + floor - cost)
        else:
            compound *= (1 + ret)

    return compound


def _compute_rita_protection(closes: list[float]) -> float | None:
    """Net downside protection from the RITA hedge overlay.

    Uses the RL model's Action-3 parameters (trading_env_v2):
      daily floor  = -1.5%  (HEDGE_DAILY_FLOOR)
      daily cost   = 0.36%  (HEDGE_COST_PER_DAY)

    Returns the net percentage of total historical downside that the
    protective-put floor would have absorbed, after subtracting hedge carry.
    """
    if len(closes) < 63:
        return None

    floor = -0.015
    cost = 0.0036

    total_downside = 0.0
    tail_saved = 0.0
    hedge_days = 0

    for i in range(1, len(closes)):
        ret = (closes[i] - closes[i - 1]) / closes[i - 1]
        if ret < 0:
            total_downside += abs(ret)
        if ret < floor:
            tail_saved += abs(ret - floor)
            hedge_days += 1

    if total_downside == 0:
        return 0.0

    net = tail_saved - hedge_days * cost
    return round(max(0.0, net / total_downside * 100), 1)


_CSV_NAME = {"BANKNIFTY": "banknifty_daily.csv", "NIFTY": "nifty_daily.csv"}


@lru_cache(maxsize=4)
def _model_split_dates(symbol: str) -> tuple[date | None, date | None]:
    """Return (train_end, val_end) from the full training CSV (70/15/15 split)."""
    csv_path = Path(settings.data.input_dir) / symbol.upper() / _CSV_NAME.get(symbol, "")
    if not csv_path.exists():
        return None, None
    with open(csv_path) as f:
        dates = sorted(row["Date"][:10] for row in _csv.DictReader(f) if row.get("Date"))
    n = len(dates)
    if n < 10:
        return None, None
    i_tr = int(n * 0.70)
    i_va = int(n * 0.85)
    return date.fromisoformat(dates[i_tr - 1]), date.fromisoformat(dates[i_va - 1])


def _build_study(symbol: str, recs: list) -> InstrumentStudy | None:
    """Build a rolling futures study for a single instrument."""
    if not recs:
        return None

    trading_dates = [r.date for r in recs]
    close_by_date: dict[date, float] = {r.date: float(r.close) for r in recs if r.close}
    all_closes = [float(r.close) for r in recs if r.close]

    contracts: list[FuturesContract] = []
    today = date.today()

    first_day = _first_trading_day_on_or_after(trading_dates, _START_DATE)
    if not first_day:
        return None

    buy_spot = close_by_date.get(first_day, 0)

    start_year = first_day.year
    start_month = first_day.month
    for i in range(3):
        m = start_month + i
        y = start_year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        month_label = date(y, m, 1).strftime("%b'%y")
        premium = _basis_premium(first_day, y, m)
        contracts.append(FuturesContract(
            month_label=month_label,
            buy_date=str(first_day),
            buy_spot=round(buy_spot, 2),
            buy_price=round(buy_spot * premium, 2),
            sell_date=None, sell_spot=None, sell_price=None,
            pnl=None, pnl_pct=None, status="open",
        ))

    current_month = start_month
    current_year = start_year
    while True:
        last_day = _last_trading_day_of_month(trading_dates, current_year, current_month)
        if not last_day or last_day > today:
            break

        sell_spot_val = close_by_date.get(last_day)
        if sell_spot_val is None:
            break

        target_label = date(current_year, current_month, 1).strftime("%b'%y")
        for c in contracts:
            if c.month_label == target_label and c.status == "open":
                c.sell_date = str(last_day)
                c.sell_spot = round(sell_spot_val, 2)
                c.sell_price = round(sell_spot_val, 2)
                c.pnl = round(c.sell_price - c.buy_price, 2)
                c.pnl_pct = round((c.sell_price / c.buy_price - 1) * 100, 2) if c.buy_price else 0
                c.status = "closed"
                break

        later_dates = [d for d in trading_dates if d > last_day]
        next_day = later_dates[0] if later_dates else None

        if next_day and next_day <= today:
            new_m = current_month + 3
            new_y = current_year + (new_m - 1) // 12
            new_m = ((new_m - 1) % 12) + 1
            new_label = date(new_y, new_m, 1).strftime("%b'%y")

            new_spot = close_by_date.get(next_day, 0)
            premium = _basis_premium(next_day, new_y, new_m)
            contracts.append(FuturesContract(
                month_label=new_label,
                buy_date=str(next_day),
                buy_spot=round(new_spot, 2),
                buy_price=round(new_spot * premium, 2),
                sell_date=None, sell_spot=None, sell_price=None,
                pnl=None, pnl_pct=None, status="open",
            ))

        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1

    latest_spot = all_closes[-1] if all_closes else 0
    for c in contracts:
        if c.status == "open":
            c.sell_spot = round(latest_spot, 2)
            c.sell_price = round(latest_spot, 2)
            c.pnl = round(c.sell_price - c.buy_price, 2)
            c.pnl_pct = round((c.sell_price / c.buy_price - 1) * 100, 2) if c.buy_price else 0

    train_end, val_end = _model_split_dates(symbol)

    for c in contracts:
        buy_d = date.fromisoformat(c.buy_date)
        sell_d = date.fromisoformat(c.sell_date) if c.sell_date else today
        segment = [close_by_date[d] for d in trading_dates if buy_d <= d <= sell_d and d in close_by_date]
        if len(segment) >= 2:
            hedged_sell = c.buy_spot * _hedged_compound(segment)
            c.hedged_pnl = round(hedged_sell - c.buy_price, 2)
        else:
            c.hedged_pnl = c.pnl

        if train_end:
            ref_d = date.fromisoformat(c.sell_date) if c.sell_date else buy_d
            if ref_d <= train_end:
                c.data_split = "train"
            elif val_end and ref_d <= val_end:
                c.data_split = "val"
            else:
                c.data_split = "test"

    quarter_contracts: dict[str, list[FuturesContract]] = defaultdict(list)
    for c in contracts:
        if c.sell_date and c.status == "closed":
            sell_d = date.fromisoformat(c.sell_date)
            ql = _quarter_label(sell_d)
            quarter_contracts[ql].append(c)

    quarters: list[QuarterSummary] = []
    quarter_order = sorted(quarter_contracts.keys(), key=lambda q: q[-2:] + q[1])

    for ql in quarter_order:
        qc = quarter_contracts[ql]
        total_pnl = sum(c.pnl or 0 for c in qc)
        dates_in_q = [date.fromisoformat(c.sell_date) for c in qc if c.sell_date]
        start_d = min(date.fromisoformat(c.buy_date) for c in qc)
        end_d = max(dates_in_q) if dates_in_q else start_d

        start_spot = close_by_date.get(
            _first_trading_day_on_or_after(trading_dates, start_d), 0
        )
        end_spot = close_by_date.get(end_d, 0)
        actual_ret = round((end_spot / start_spot - 1) * 100, 2) if start_spot else None

        closes_up_to = [float(r.close) for r in recs if r.date < start_d and r.close]
        q_var, q_breach = _compute_quarterly_var(closes_up_to)

        var_breached = None
        if q_var is not None and actual_ret is not None:
            var_breached = actual_ret < -q_var

        q_closes = [close_by_date[d] for d in trading_dates
                     if start_d <= d <= end_d and d in close_by_date]
        hedged_ret = None
        if len(q_closes) >= 2:
            hedged_ret = round((_hedged_compound(q_closes) - 1) * 100, 2)

        q_split = None
        if train_end:
            if end_d <= train_end:
                q_split = "train"
            elif val_end and end_d <= val_end:
                q_split = "val"
            else:
                q_split = "test"

        quarters.append(QuarterSummary(
            quarter=ql,
            start_date=str(start_d),
            end_date=str(end_d),
            contracts_closed=len(qc),
            total_pnl=round(total_pnl, 2),
            quarterly_var_pct=q_var,
            actual_return_pct=actual_ret,
            var_breached=var_breached,
            hist_breach_prob_pct=q_breach,
            hedged_return_pct=hedged_ret,
            data_split=q_split,
        ))

    cum_pnl = 0.0
    cum_hedged = 0.0
    cumulative: list[dict] = []
    closed_sorted = sorted(
        [c for c in contracts if c.status == "closed" and c.sell_date],
        key=lambda c: c.sell_date,
    )
    for c in closed_sorted:
        cum_pnl += c.pnl or 0
        cum_hedged += c.hedged_pnl if c.hedged_pnl is not None else (c.pnl or 0)
        cumulative.append({
            "date": c.sell_date,
            "pnl": round(cum_pnl, 2),
            "hedged_pnl": round(cum_hedged, 2),
            "contract": c.month_label,
        })

    total_pnl = sum(c.pnl or 0 for c in contracts)

    q_var, q_breach = _compute_quarterly_var(all_closes)
    q_label = _quarter_label(today)
    rita_prot = _compute_rita_protection(all_closes)

    return InstrumentStudy(
        instrument=symbol,
        start_date=str(_START_DATE),
        basis_premium_pct=1.1,
        contracts=contracts,
        quarters=quarters,
        cumulative_pnl=cumulative,
        total_pnl=round(total_pnl, 2),
        total_contracts=len(contracts),
        quarterly_var_pct=q_var,
        hist_breach_prob_pct=q_breach,
        quarter_label=q_label,
        rita_protected_pct=rita_prot,
        split_dates={
            "train_end": str(train_end) if train_end else None,
            "val_end": str(val_end) if val_end else None,
        },
    )


@router.get("/study", response_model=MultiStudyResponse)
def get_fno_study(db: Session = Depends(get_db)) -> MultiStudyResponse:
    all_records = MarketDataCacheRepository(db).read_all()

    studies: list[InstrumentStudy] = []
    for symbol in _SYMBOLS:
        recs = sorted(
            [r for r in all_records if r.underlying.upper() == symbol],
            key=lambda r: r.date,
        )
        study = _build_study(symbol, recs)
        if study:
            studies.append(study)

    return MultiStudyResponse(studies=studies)
