"""PositionValueService — monthly position-value series + ±1σ bands (F40 Phase 3).

Read-only (no commit).  value_d = stored shares x close_d, in the instrument's own
currency (INSTRUMENT_CCY, no FX, no default currency).  Shares are never derived from
the EUR allocation.

σ notes (honesty of the ±1σ):
- With constant shares the daily returns of the value series equal the price returns, so
  the value σ is IDENTICAL to the price σ (and to the Monthly σ KPI tiles).  The bands
  are the price σ percentages scaled by shares (currency amounts only differ by shares).
- The σ window is fixed at the last 253 closes (252 returns, same as
  ``HedgePlanService._ann_vol_pct``), regardless of the ``months`` query param.
- An ``ann_vol_pct`` override (the dashboard passes the Monthly σ tile source) takes
  precedence over the computed value (``vol_source = "override"``).
"""
from __future__ import annotations

import math
import statistics
from datetime import date

import structlog
from sqlalchemy.orm import Session

from rita.core.portfolio_engine import CCY_SYMBOL, INSTRUMENT_CCY
from rita.models.user import UserModel
from rita.repositories.market_data import MarketDataCacheRepository
from rita.repositories.user_portfolio import UserPortfolioRepo
from rita.repositories.user_portfolio_key import UserPortfolioKeyRepo
from rita.schemas.position_value import (
    MSG_CASH,
    MSG_INSUFFICIENT,
    MSG_NO_CURRENCY,
    MSG_NO_HOLDING,
    MSG_NO_PRICE_DATA,
    MSG_NO_SHARES,
    PositionValueBands,
    PositionValueCandle,
    PositionValueDaily,
    PositionValueItem,
    PositionValueResponse,
)

log = structlog.get_logger(__name__)

VOL_WINDOW_CLOSES = 253  # 252 returns
VOL_MIN_CLOSES = 30
CASH_IDS = {"CASH"}


# ── pure helpers ────────────────────────────────────────────────────────────
def window_start(end: date, months: int) -> date:
    """First day of the month ``months-1`` before ``end``'s month."""
    idx = end.year * 12 + (end.month - 1) - (months - 1)
    return date(idx // 12, idx % 12 + 1, 1)


def value_series(closes: list[tuple[date, float]], shares: int) -> list[tuple[date, float]]:
    return [(d, shares * c) for d, c in closes]


def monthly_candles(daily: list[tuple[date, float]]) -> list[PositionValueCandle]:
    """open=first, close=last, high/low = max/min of the daily values (same as JS)."""
    by_month: dict[str, list[float]] = {}
    for d, v in daily:
        by_month.setdefault(d.strftime("%Y-%m"), []).append(v)
    out = []
    for k in sorted(by_month):
        vals = by_month[k]
        out.append(PositionValueCandle(
            month=k, open=round(vals[0], 2), high=round(max(vals), 2),
            low=round(min(vals), 2), close=round(vals[-1], 2),
        ))
    return out


def ann_vol_pct_from_closes(closes: list[float]) -> float | None:
    """Sample stdev of daily returns x sqrt(252) x 100 (4 dp); None if too short."""
    if len(closes) < VOL_MIN_CLOSES:
        return None
    rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1]]
    if len(rets) < 2:
        return None
    return round(statistics.stdev(rets) * math.sqrt(252) * 100, 4)


def monthly_sigma(ann_vol_pct: float) -> float:
    """Monthly σ as a fraction: ann_vol_pct / 100 / sqrt(12)."""
    return ann_vol_pct / 100.0 / math.sqrt(12)


def build_bands(anchor_value: float, anchor_date: date, ann_vol_pct: float) -> PositionValueBands:
    s = monthly_sigma(ann_vol_pct)
    return PositionValueBands(
        anchor_value=round(anchor_value, 2),
        anchor_date=anchor_date.isoformat(),
        plus_1sigma_value=round(anchor_value * (1 + s), 2),
        minus_1sigma_value=round(anchor_value * (1 - s), 2),
        plus_1sigma_pct=round(s * 100, 4),
        minus_1sigma_pct=round(-s * 100, 4),
    )


def _non_ok(iid: str, status: str, message: str, months: int,
            currency: str | None = None, shares: int | None = None) -> PositionValueItem:
    return PositionValueItem(
        instrument_id=iid, status=status, message=message, currency=currency,
        currency_symbol=(CCY_SYMBOL.get(currency) or "") if currency else "",
        shares=shares, months=months,
    )


# ── service ─────────────────────────────────────────────────────────────────
class PositionValueService:
    def __init__(self, db: Session) -> None:
        self._keys = UserPortfolioKeyRepo(db)
        self._portfolios = UserPortfolioRepo(db)
        self._market = MarketDataCacheRepository(db)

    def build(self, user: UserModel, instrument: str | None, months: int,
              ann_vol_pct: float | None) -> PositionValueResponse:
        holdings = self._holdings(user)
        if instrument:
            ids = [instrument.strip().upper()]
        else:
            ids = []
            for h in holdings:
                iid = str(h.get("instrument_id", "")).upper()
                if iid and iid not in ids:
                    ids.append(iid)
        items = [self._item(iid, holdings, months, ann_vol_pct) for iid in ids]
        as_of = self._as_of(items)
        return PositionValueResponse(as_of=as_of, items=items)

    @staticmethod
    def _as_of(items: list[PositionValueItem]) -> str | None:
        ends = [i.daily[-1].date for i in items if i.status == "ok" and i.daily]
        return max(ends) if ends else None

    def _holdings(self, user: UserModel) -> list[dict]:
        key = self._keys.find_by_user_id(user.id)
        if key is None:
            return []
        portfolio = self._portfolios.find_active_by_key_id(key.key_id)
        return list(portfolio.holdings or []) if portfolio is not None else []

    def _item(self, iid: str, holdings: list[dict], months: int,
              ann_vol_override: float | None) -> PositionValueItem:
        try:
            return self._compute(iid, holdings, months, ann_vol_override)
        except Exception as exc:  # one bad instrument must not fail the batch
            log.warning("position_value.item_failed", instrument_id=iid, error=str(exc))
            return _non_ok(iid, "no_price_data", MSG_NO_PRICE_DATA.format(id=iid), months,
                           currency=INSTRUMENT_CCY.get(iid))

    def _compute(self, iid: str, holdings: list[dict], months: int,
                 ann_vol_override: float | None) -> PositionValueItem:
        if iid in CASH_IDS:
            return _non_ok(iid, "cash", MSG_CASH, months)
        matches = [h for h in holdings if str(h.get("instrument_id", "")).upper() == iid]
        if not matches:
            return _non_ok(iid, "no_holding", MSG_NO_HOLDING.format(id=iid), months,
                           currency=INSTRUMENT_CCY.get(iid))
        if len(matches) > 1:
            log.warning("position_value.duplicate_holding", instrument_id=iid, n=len(matches))
        raw = matches[0].get("shares")
        shares = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0 else None
        currency = INSTRUMENT_CCY.get(iid)  # no default / no FX
        if shares is None:
            return _non_ok(iid, "no_shares", MSG_NO_SHARES.format(id=iid), months, currency=currency)
        if currency is None:
            return _non_ok(iid, "no_currency", MSG_NO_CURRENCY.format(id=iid), months, shares=shares)

        latest = self._market.find_latest(iid)
        if latest is None:
            return _non_ok(iid, "no_price_data", MSG_NO_PRICE_DATA.format(id=iid), months,
                           currency=currency, shares=shares)
        end = latest.date
        closes = self._market.find_closes(iid, window_start(end, months), end)
        if not closes:
            return _non_ok(iid, "no_price_data", MSG_NO_PRICE_DATA.format(id=iid), months,
                           currency=currency, shares=shares)
        daily = value_series(closes, shares)
        candles = monthly_candles(daily)
        if len(candles) < 2:
            return _non_ok(iid, "insufficient_data", MSG_INSUFFICIENT.format(id=iid), months,
                           currency=currency, shares=shares)

        # σ of the value series == σ of the price series (constant shares); fixed window.
        if ann_vol_override is not None and ann_vol_override > 0:
            vol, source = round(float(ann_vol_override), 4), "override"
        else:
            vol = ann_vol_pct_from_closes(self._market.find_recent_closes(iid, VOL_WINDOW_CLOSES))
            source = "computed" if vol is not None else None
        last_date, last_close = closes[-1]
        last_value = shares * last_close
        bands = build_bands(candles[-1].close, last_date, vol) if vol is not None else None
        return PositionValueItem(
            instrument_id=iid, status="ok", message="", currency=currency,
            currency_symbol=CCY_SYMBOL.get(currency) or "", shares=shares, months=months,
            last_close=round(last_close, 4), last_value=round(last_value, 2),
            ann_vol_pct=vol, vol_source=source,
            monthly_sigma_pct=round(vol / math.sqrt(12), 4) if vol is not None else None,
            bands=bands, candles=candles,
            daily=[PositionValueDaily(date=d.isoformat(), value=round(v, 2)) for d, v in daily],
        )
