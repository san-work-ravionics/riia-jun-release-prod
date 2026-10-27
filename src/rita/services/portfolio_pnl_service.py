"""PortfolioPnlService — the ``portfolio.pnl`` tool (F44 P4; rev 1 B2/B4, rev 2 N1, rev 3).

One rule (rev 3): the year's return covers exactly **[s, as_of]** (s = the journey's
``plan_year_start``, else max(Jan 1, the saved row's entry)), built as a day-by-day chained path.
On each day the source is the user's **saved location portfolio if one was active that day, else
the open journey segment's model sleeves**; sub-periods are joined with
``core.goal_targets.chain_returns``.

- saved — value V_t = Σ shares × close_t + cash (``market_data_cache``); re-saves are chained at
  the re-save date (old row up to the new row's ``created_at``, then the new row).  Legacy
  (location NULL) rows count with their holdings filtered to the location's instruments.
- model sleeves — per segment, buy-and-drift of the segment's DDQN v2 sleeves (P3 replay cache)
  from ``from`` to ``to`` / as_of; each segment in turn (a later mix is never replayed over an
  earlier part of the year).  Instruments with no model are left out and reported in ``coverage``.
- preview (rev 3 P3-2b) — a selection not tracked yet: its sleeves bought on Jan 1; never used by
  the guard.
- ``target_to_date`` = ``core.goal_targets.target_to_date(r, s, as_of)`` with r = the annual goal.

Read-only.  ADR-002: data through ``UserPortfolioRepo`` / ``UserPortfolioKeyRepo`` /
``MarketDataCacheRepository`` and ``GoalSelectionService``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from rita.core.goal_targets import chain_returns, target_to_date
from rita.repositories.market_data import MarketDataCacheRepository
from rita.repositories.user_portfolio import UserPortfolioRepo
from rita.repositories.user_portfolio_key import UserPortfolioKeyRepo
from rita.schemas.jarvis import (
    MoneyHoldingOut,
    MoneyOut,
    MoneyPointOut,
    PnlHoldingOut,
    PnlOut,
    PnlPointOut,
    TargetPointOut,
)
from rita.services.goal_selection_service import GoalSelectionService
from rita.services.user_portfolio_service import UserPortfolioService, holding_cash, location_currency

_LOOKBACK_DAYS = 15     # closes fetched before a period start to find its base close


class PnlError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class _SavedRow:
    portfolio_id: str
    name: str | None
    created: date
    holdings: list[dict]
    legacy: bool


@dataclass
class _Segment:
    start: date
    end: date | None
    holdings: list[tuple[str, int, str]]      # (instrument, allocation_pct, τ)


@dataclass
class _Period:
    start: date
    end: date | None
    source: str                                # saved | model_sleeves
    values: pd.Series                          # value path, index = dates (base first)


def _d(x: Any) -> date:
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def _created(row: Any) -> date:
    c = row.created_at
    return c.date() if hasattr(c, "date") else _d(c)


def segments_from(raw: list[Any] | None) -> list[_Segment]:
    out = []
    for seg in raw or []:
        g = seg if isinstance(seg, dict) else seg.model_dump(mode="json")
        out.append(_Segment(
            start=_d(g["from"]), end=_d(g["to"]) if g.get("to") else None,
            holdings=[(h["instrument_id"].upper(), int(h["allocation_pct"]), h["tolerance"])
                      for h in g["holdings"]],
        ))
    out.sort(key=lambda s: s.start)
    return out


def chain_periods(periods: list[_Period]) -> tuple[list[tuple[date, float, str]], list[float]]:
    """Chained path over consecutive periods → ``[(date, return since the first base, source)]``
    and the per-period returns (``chain_returns`` of them = the last point)."""
    points: list[tuple[date, float, str]] = []
    period_returns: list[float] = []
    growth = 1.0
    for k, p in enumerate(periods):
        vals = p.values
        if len(vals) == 0:
            continue
        base = float(vals.iloc[0])
        if k == 0 and not points:
            points.append((vals.index[0].date(), 0.0, p.source))
        for ts, v in vals.iloc[1:].items():
            points.append((ts.date(), growth * float(v) / base - 1.0, p.source))
        r = float(vals.iloc[-1]) / base - 1.0
        period_returns.append(r)
        growth *= 1.0 + r
    return points, period_returns


class PortfolioPnlService:
    def __init__(self, db: Session, goal: GoalSelectionService | None = None) -> None:
        self._db = db
        self._goal = goal or GoalSelectionService(db)
        self._market = MarketDataCacheRepository(db)
        self._keys = UserPortfolioKeyRepo(db)
        self._rows = UserPortfolioRepo(db)
        self._ups = UserPortfolioService(db)

    # ── saved rows ─────────────────────────────────────────────────────────────

    def saved_rows(self, user_id: str, location: str) -> list[_SavedRow]:
        """The location's saved rows (oldest first); else the legacy rows filtered to the
        location's instruments."""
        key = self._keys.find_by_user_id(user_id)
        if key is None:
            return []
        rows = self._rows.list_by_key_and_location(key.key_id, location)
        if rows:
            return [_SavedRow(r.portfolio_id, r.name, _created(r), list(r.holdings or []), False)
                    for r in rows]
        out = []
        for r in self._rows.list_by_key_and_location(key.key_id, None):
            hs = [h for h in (r.holdings or [])
                  if self._ups.instrument_location(str(h.get("instrument_id", ""))) == location]
            if hs:
                out.append(_SavedRow(r.portfolio_id, r.name, _created(r), hs, True))
        return out

    def _closes(self, instrument: str, start: date, end: date) -> pd.Series:
        rows = self._market.find_closes(instrument, start - timedelta(days=_LOOKBACK_DAYS), end)
        if not rows:
            return pd.Series(dtype=float)
        return pd.Series([c for _, c in rows], index=pd.DatetimeIndex([d for d, _ in rows]), dtype=float)

    def _saved_values(self, row: _SavedRow, start: date, end: date) -> pd.Series:
        """V_t = Σ shares × close_t + cash, from the last bar ≤ ``start`` to ``end``."""
        cash = sum(holding_cash(h) or 0.0 for h in row.holdings)
        series = []
        for h in row.holdings:
            shares = h.get("shares")
            if not isinstance(shares, (int, float)) or isinstance(shares, bool) or shares <= 0:
                continue
            c = self._closes(str(h["instrument_id"]), start, end)
            if not c.empty:
                series.append(c * float(shares))
        if not series:
            return pd.Series(dtype=float)
        frame = pd.concat(series, axis=1).sort_index().ffill().dropna()
        values = frame.sum(axis=1) + cash
        return _from_base(values, start, end)

    def _sleeve_values(self, seg: _Segment, start: date, end: date) -> tuple[pd.Series, float]:
        """Buy-and-drift of the segment's sleeves over bars in (start, end]; returns the value
        path and the covered weight fraction."""
        weights, rets = [], []
        total = sum(p for _, p, _ in seg.holdings) or 1
        for inst, pct, tau in seg.holdings:
            ir = self._goal.instrument_runs(inst)
            if ir.excluded is not None or not ir.runs or tau not in ir.runs:
                continue
            weights.append(pct / 100.0)
            rets.append(ir.runs[tau].returns_series())
        if not rets:
            return pd.Series(dtype=float), 0.0
        frame = pd.concat(rets, axis=1).sort_index()
        frame = frame[(frame.index > pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))].fillna(0.0)
        w = np.array(weights) / sum(weights)
        growth = (1.0 + frame).cumprod().to_numpy() @ w if len(frame) else np.array([])
        idx = [pd.Timestamp(start)] + list(frame.index)
        covered = sum(weights) * 100.0 / total
        return pd.Series(np.concatenate([[1.0], growth]), index=pd.DatetimeIndex(idx)), covered

    def _sleeve_as_of(self, segs: list[_Segment]) -> date | None:
        dates = []
        for seg in segs:
            for inst, _p, tau in seg.holdings:
                ir = self._goal.instrument_runs(inst)
                if ir.runs and tau in ir.runs:
                    dates.append(ir.runs[tau].as_of)
        return max(dates) if dates else None

    # ── the tool ───────────────────────────────────────────────────────────────

    def pnl(self, user_id: str, location: str, goal_return: float | None = None, source: str = "auto",
            year_start: date | None = None, segments: list[Any] | None = None,
            preview: bool = False) -> PnlOut:
        currency = location_currency(location)
        rows = self.saved_rows(user_id, location) if source in ("auto", "saved") else []
        segs = segments_from(segments) if source in ("auto", "model_sleeves") else []
        if source == "saved" and not rows:
            raise PnlError("not_found", f"no saved portfolio for {location}")
        if source == "model_sleeves" and not segs:
            raise PnlError("not_found", "no model-sleeve segments given")
        if not rows and not segs:
            raise PnlError("not_found", f"no saved portfolio for {location} and no selection")

        as_of = self._as_of(rows, segs)
        if as_of is None:
            raise PnlError("not_found", "no closing prices yet")
        jan1 = date(as_of.year, 1, 1)
        if preview:
            segs = [_Segment(jan1, None, segs[0].holdings)] if segs else []
        relevant = [r for k, r in enumerate(rows) if k == len(rows) - 1 or rows[k + 1].created > jan1]
        saved_start = relevant[0].created if relevant else None
        if year_start is not None:
            s = year_start
        elif segs:
            s = max(jan1, segs[0].start) if not preview else jan1
            if saved_start is not None and not any(g.start < saved_start for g in segs):
                s = max(jan1, saved_start)
        else:
            s = max(jan1, saved_start)

        periods: list[_Period] = []
        coverage_parts: list[float] = []
        # model sleeves before the saved portfolio existed (or with no saved portfolio)
        sleeve_until = saved_start if saved_start is not None and saved_start > s else (
            None if saved_start is None else s)
        for seg in segs:
            start = max(seg.start, s)
            end = min(seg.end or as_of, as_of)
            if sleeve_until is not None:
                end = min(end, sleeve_until)
            if end <= start:
                continue
            vals, cov = self._sleeve_values(seg, start, end)
            if len(vals) > 1:
                periods.append(_Period(start, end, "model_sleeves", vals))
                coverage_parts.append(cov)
        # saved rows, chained at each re-save
        for k, r in enumerate(relevant):
            start = max(r.created, s)
            end = relevant[k + 1].created if k + 1 < len(relevant) else as_of
            if end <= start and k + 1 < len(relevant):
                continue
            vals = self._saved_values(r, start, end)
            if len(vals) >= 1:
                periods.append(_Period(start, end, "saved", vals))
        periods.sort(key=lambda p: p.start)

        points, period_rets = chain_periods(periods)
        kinds = {p.source for p in periods if len(p.values) > 1} or {p.source for p in periods}
        if preview:
            label = "model_sleeves_preview"
        elif kinds == {"saved"}:
            label = "saved"
        elif kinds == {"model_sleeves"}:
            label = "model_sleeves"
        elif kinds:
            label = "mixed"
        else:
            label = "saved" if rows else "model_sleeves"
        ytd = chain_returns(period_rets) if len(points) > 1 else None
        path_as_of = points[-1][0] if points else as_of
        out = PnlOut(
            location=location, currency=currency, source=label, as_of=path_as_of, year_start=s,
            goal_return=goal_return, ytd_return=ytd,
            series=[PnlPointOut(date=d, ret=r, source=src) for d, r, src in points],
            coverage=round(coverage_parts[-1], 4) if (coverage_parts and label != "saved") else 1.0,
        )
        if goal_return is not None:
            out.target_to_date = target_to_date(goal_return, s, path_as_of)
            out.target_path = [TargetPointOut(date=d, target=target_to_date(goal_return, s, d))
                               for d, _r, _s in points]
        if rows and label in ("saved", "mixed"):
            active = relevant[-1] if relevant else rows[-1]
            out.entry_date = active.created
            out.money = self._money(active, path_as_of)
            out.holdings = self._saved_holdings(active, path_as_of)
            out.coverage = self._saved_coverage(out.money, active)
        elif segs:
            cur = segs[-1]
            out.entry_date = max(cur.start, s) if not preview else jan1
            out.holdings = self._sleeve_holdings(cur, max(cur.start, s), path_as_of)
        return out

    def _as_of(self, rows: list[_SavedRow], segs: list[_Segment]) -> date | None:
        dates = []
        if rows:
            for h in rows[-1].holdings:
                latest = self._market.find_latest(str(h.get("instrument_id", "")))
                if latest is not None:
                    dates.append(latest.date)
        if segs:
            d = self._sleeve_as_of(segs)
            if d is not None:
                dates.append(d)
        return max(dates) if dates else None

    def _money(self, row: _SavedRow, as_of: date) -> MoneyOut:
        vals = self._saved_values(row, row.created, as_of)
        cash = float(sum(holding_cash(h) or 0.0 for h in row.holdings))
        money = MoneyOut(portfolio_id=row.portfolio_id, name=row.name, legacy_note=row.legacy, cash=cash)
        if len(vals):
            entry, now = float(vals.iloc[0]), float(vals.iloc[-1])
            money.value_entry, money.value_now, money.pnl = entry, now, now - entry
            money.return_since_entry = now / entry - 1.0 if entry else None
            money.series = [MoneyPointOut(date=ts.date(), value=float(v), pnl=float(v) - entry)
                            for ts, v in vals.items()]
        for h in row.holdings:
            iid = str(h.get("instrument_id", "")).upper()
            shares = h.get("shares") if isinstance(h.get("shares"), int) else None
            c = self._closes(iid, row.created, as_of)
            c_base = _from_base(c, row.created, as_of)
            entry_close = float(c_base.iloc[0]) if len(c_base) else None
            last_close = float(c_base.iloc[-1]) if len(c_base) else None
            pnl = (shares * (last_close - entry_close)
                   if shares and entry_close is not None and last_close is not None else None)
            money.holdings.append(MoneyHoldingOut(instrument_id=iid, shares=shares, entry_close=entry_close,
                                                  last_close=last_close, pnl=pnl))
        return money

    def _saved_holdings(self, row: _SavedRow, as_of: date) -> list[PnlHoldingOut]:
        out = []
        for h in row.holdings:
            iid = str(h.get("instrument_id", "")).upper()
            shares = h.get("shares")
            c = _from_base(self._closes(iid, row.created, as_of), row.created, as_of)
            if not isinstance(shares, (int, float)) or isinstance(shares, bool) or shares <= 0:
                status, ret = "no_shares", None
            elif len(c) == 0:
                status, ret = "no_price_data", None
            else:
                status, ret = "ok", float(c.iloc[-1] / c.iloc[0] - 1.0)
            out.append(PnlHoldingOut(instrument_id=iid, allocation_pct=float(h.get("allocation_pct") or 0.0),
                                     return_since=ret, status=status))
        return out

    @staticmethod
    def _saved_coverage(money: MoneyOut, row: _SavedRow) -> float:
        priced = {h.instrument_id for h in money.holdings if h.last_close is not None and h.shares}
        total = sum(float(h.get("allocation_pct") or 0.0) for h in row.holdings) or 1.0
        covered = sum(float(h.get("allocation_pct") or 0.0) for h in row.holdings
                      if str(h.get("instrument_id", "")).upper() in priced)
        return round(covered / total, 4)

    def _sleeve_holdings(self, seg: _Segment, start: date, as_of: date) -> list[PnlHoldingOut]:
        out = []
        for inst, pct, tau in seg.holdings:
            ir = self._goal.instrument_runs(inst)
            if ir.excluded is not None or not ir.runs or tau not in ir.runs:
                out.append(PnlHoldingOut(instrument_id=inst, allocation_pct=float(pct), status="excluded"))
                continue
            r = ir.runs[tau].returns_series()
            r = r[(r.index > pd.Timestamp(start)) & (r.index <= pd.Timestamp(as_of))]
            out.append(PnlHoldingOut(instrument_id=inst, allocation_pct=float(pct),
                                     return_since=float((1.0 + r).prod() - 1.0), status="ok"))
        return out


def _from_base(values: pd.Series, start: date, end: date) -> pd.Series:
    """The path from the last bar on or before ``start`` to ``end`` (inclusive)."""
    if values.empty:
        return values
    ts0, ts1 = pd.Timestamp(start), pd.Timestamp(end)
    before = values[values.index <= ts0]
    base_idx = before.index[-1] if len(before) else values.index[0]
    return values[(values.index >= base_idx) & (values.index <= ts1)]
