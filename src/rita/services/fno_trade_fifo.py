"""F42 Phase 3 — pure FIFO lot-matching engine over a user's option fills.

No I/O, no DB, no settings import: the service maps ORM rows into the frozen dataclasses
below.  Everything is deterministic and reproducible.  Quantities are in contract UNITS
(never lots: lot sizes are not known here).

Matching: per symbol, oldest lot first; a fill that crosses zero closes the open side and
the remainder opens a new lot on the other side (``flip``).  Lots still open after the last
fill may be closed at spot-intrinsic on their expiry date as a flagged ESTIMATE
(``close_kind == "expiry_est"``) when a spot close exists for that date.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable, Optional

EPS = 1e-9


@dataclass(frozen=True)
class Fill:
    symbol: str
    underlying: str
    itype: str                      # CE | PE
    strike: Optional[float]
    expiry_eff: Optional[date]      # expiry_date or opt_expiry
    expiry_ym: Optional[str]
    trade_date: date
    exec_dt: Optional[datetime]     # naive IST, nullable
    sign: int                       # +1 buy / -1 sell
    qty: int
    price: float
    trade_id: str
    order_id: str


@dataclass(frozen=True)
class Segment:
    """One matched slice: an opening fill (or part of it) closed by a closing fill/expiry."""
    symbol: str
    underlying: str
    itype: str
    strike: Optional[float]
    expiry_eff: Optional[date]
    expiry_ym: Optional[str]
    side: int                       # +1 long, -1 short
    qty: int
    entry_px: float
    exit_px: float
    open_idx: int                   # index of the opening fill in FifoResult.fills
    close_idx: int                  # index of the closing fill, -1 for expiry estimate
    open_trade_id: str
    close_trade_id: Optional[str]
    close_order_id: Optional[str]
    open_date: date
    close_date: date
    open_dt: Optional[datetime]
    close_dt: Optional[datetime]
    same_day: bool
    holding_minutes: Optional[float]
    holding_days: int
    close_kind: str                 # trade | expiry_est
    carried_in: bool                # opened before the window start
    flip: bool                      # lot created by the remainder of a zero-crossing fill

    @property
    def pnl(self) -> float:
        return self.qty * (self.exit_px - self.entry_px) * self.side

    @property
    def estimated(self) -> bool:
        return self.close_kind == "expiry_est"


@dataclass(frozen=True)
class ClosedTrade:
    symbol: str
    underlying: str
    itype: str
    expiry_ym: Optional[str]
    expiry_eff: Optional[date]
    side: int
    qty: int
    pnl: float
    entry_avg: float
    exit_avg: float
    close_date: date
    close_dt: Optional[datetime]
    holding_minutes: Optional[float]    # qty-weighted; None when any segment lacks timestamps
    holding_days: float                 # qty-weighted
    same_day: bool
    estimated: bool
    carried_in: bool
    open_idxs: tuple[int, ...]
    close_idx: int
    n_segments: int

    @property
    def premium(self) -> float:
        return self.entry_avg * self.qty


@dataclass(frozen=True)
class OpenLot:
    symbol: str
    underlying: str
    itype: str
    strike: Optional[float]
    side: int
    qty: int
    avg_entry: float
    open_date: date
    open_idx: int
    expiry_eff: Optional[date]
    expiry_ym: Optional[str]
    expired: bool                   # expiry_eff < as_of
    expiry_unknown: bool
    settlement_unpriced: bool       # expired/at-expiry but no spot close for the expiry date
    est_settled: bool               # closed by an expiry estimate segment
    carried_in: bool


@dataclass(frozen=True)
class FillEvent:
    idx: int
    fill: Fill
    cls: str                        # open_new | scale_in | scale_out | close | flip
    pos_before: int                 # signed units
    avg_before: Optional[float]
    pos_after: int
    avg_after: Optional[float]
    closed_qty: int
    opened_qty: int
    realised: float                 # measured gross P&L realised by this fill
    adverse_add: bool               # scale_in at a price worse than the average entry


@dataclass
class FifoResult:
    fills: list[Fill]
    events: list[FillEvent]
    segments: list[Segment]                 # trade-closed segments (measured)
    est_segments: list[Segment]             # expiry-estimate segments
    residual_lots: list[OpenLot]            # every lot open after the last fill
    window_start: date
    as_of: date
    spot: dict[str, "SpotSeries"] = field(default_factory=dict)
    meta: dict[str, Fill] = field(default_factory=dict)   # first fill per symbol (static fields)

    def all_segments(self, include_est: bool) -> list[Segment]:
        return self.segments + (self.est_segments if include_est else [])

    def open_lots(self, include_est: bool) -> list[OpenLot]:
        return [lot for lot in self.residual_lots if not (include_est and lot.est_settled)]


class SpotSeries:
    """Sorted (date, close) pairs with previous-close lookup."""

    def __init__(self, pairs: Iterable[tuple[date, float]]) -> None:
        pts = sorted(pairs)
        self.dates = [p[0] for p in pts]
        self.closes = [p[1] for p in pts]

    def __bool__(self) -> bool:
        return bool(self.dates)

    def exact(self, d: date) -> Optional[float]:
        i = bisect.bisect_left(self.dates, d)
        if i < len(self.dates) and self.dates[i] == d:
            return self.closes[i]
        return None

    def on_or_before(self, d: date) -> Optional[float]:
        i = bisect.bisect_right(self.dates, d)
        return self.closes[i - 1] if i else None


def sort_key(f: Fill) -> tuple:
    return (f.trade_date, f.exec_dt or datetime.combine(f.trade_date, datetime.min.time()),
            f.order_id, f.trade_id, f.symbol)


def order_fills(fills: Iterable[Fill]) -> list[Fill]:
    return sorted(fills, key=sort_key)


def intrinsic(itype: str, strike: Optional[float], spot: float) -> Optional[float]:
    if strike is None:
        return None
    return max(spot - strike, 0.0) if itype == "CE" else max(strike - spot, 0.0)


@dataclass
class _Lot:
    qty: int
    px: float
    idx: int
    d: date
    dt: Optional[datetime]
    tid: str
    flip: bool


def _minutes(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if a is None or b is None:
        return None
    return max((b - a).total_seconds() / 60.0, 0.0)


def _avg(lots: list[_Lot]) -> Optional[float]:
    q = sum(lot.qty for lot in lots)
    return sum(lot.qty * lot.px for lot in lots) / q if q else None


def run_fifo(fills: Iterable[Fill], *, window_start: date, as_of: date,
             spot: Optional[dict[str, SpotSeries]] = None) -> FifoResult:
    """Match fills FIFO per symbol.  ``as_of`` = min(date_to, today IST); expiry estimates
    are produced for every residual lot with ``expiry_eff < as_of`` and a spot close on
    ``expiry_eff`` (callers choose whether to include them in aggregates)."""
    spot = spot or {}
    ordered = order_fills(fills)
    books: dict[str, list[_Lot]] = {}
    side_of: dict[str, int] = {}
    segments: list[Segment] = []
    events: list[FillEvent] = []

    for idx, f in enumerate(ordered):
        lots = books.setdefault(f.symbol, [])
        side = side_of.get(f.symbol, 0) if lots else 0
        pos_before = sum(lot.qty for lot in lots) * side
        avg_before = _avg(lots)
        closed = opened = 0
        realised = 0.0
        adverse = False
        flip_open = False
        remaining = f.qty
        if lots and side != f.sign:
            while remaining > 0 and lots:
                lot = lots[0]
                take = min(remaining, lot.qty)
                seg = Segment(
                    symbol=f.symbol, underlying=f.underlying, itype=f.itype, strike=f.strike,
                    expiry_eff=f.expiry_eff, expiry_ym=f.expiry_ym, side=side, qty=take,
                    entry_px=lot.px, exit_px=f.price, open_idx=lot.idx, close_idx=idx,
                    open_trade_id=lot.tid, close_trade_id=f.trade_id, close_order_id=f.order_id,
                    open_date=lot.d, close_date=f.trade_date, open_dt=lot.dt, close_dt=f.exec_dt,
                    same_day=lot.d == f.trade_date,
                    holding_minutes=_minutes(lot.dt, f.exec_dt),
                    holding_days=(f.trade_date - lot.d).days, close_kind="trade",
                    carried_in=lot.d < window_start, flip=lot.flip)
                segments.append(seg)
                realised += seg.pnl
                closed += take
                remaining -= take
                lot.qty -= take
                if lot.qty == 0:
                    lots.pop(0)
            flip_open = remaining > 0 and not lots
        if remaining > 0:
            if lots and side == f.sign:
                cur_avg = _avg(lots)
                adverse = cur_avg is not None and side * (f.price - cur_avg) < 0
            lots.append(_Lot(remaining, f.price, idx, f.trade_date, f.exec_dt, f.trade_id,
                             flip_open))
            side_of[f.symbol] = f.sign
            opened = remaining
        pos_after = sum(lot.qty for lot in lots) * side_of.get(f.symbol, 0)
        if closed == 0:
            cls = "open_new" if pos_before == 0 else "scale_in"
        elif opened > 0:
            cls = "flip"
        elif pos_after == 0:
            cls = "close"
        else:
            cls = "scale_out"
        events.append(FillEvent(
            idx=idx, fill=f, cls=cls, pos_before=pos_before, avg_before=avg_before,
            pos_after=pos_after, avg_after=_avg(lots), closed_qty=closed, opened_qty=opened,
            realised=realised, adverse_add=adverse))

    est_segments: list[Segment] = []
    residual: list[OpenLot] = []
    for sym, lots in books.items():
        if not lots:
            continue
        side = side_of[sym]
        for lot in lots:
            f0 = ordered[lot.idx]
            exp = f0.expiry_eff
            expired = exp is not None and exp < as_of
            at_exp = exp is not None and exp == as_of
            px = None
            if expired and exp is not None:
                ss = spot.get(f0.underlying)
                close = ss.exact(exp) if ss else None
                if close is not None:
                    px = intrinsic(f0.itype, f0.strike, close)
            est = px is not None
            if est and exp is not None:
                est_segments.append(Segment(
                    symbol=sym, underlying=f0.underlying, itype=f0.itype, strike=f0.strike,
                    expiry_eff=exp, expiry_ym=f0.expiry_ym, side=side, qty=lot.qty,
                    entry_px=lot.px, exit_px=float(px), open_idx=lot.idx, close_idx=-1,
                    open_trade_id=lot.tid, close_trade_id=None, close_order_id=None,
                    open_date=lot.d, close_date=exp, open_dt=lot.dt, close_dt=None,
                    same_day=lot.d == exp, holding_minutes=None,
                    holding_days=(exp - lot.d).days, close_kind="expiry_est",
                    carried_in=lot.d < window_start, flip=lot.flip))
            residual.append(OpenLot(
                symbol=sym, underlying=f0.underlying, itype=f0.itype, strike=f0.strike, side=side,
                qty=lot.qty, avg_entry=lot.px, open_date=lot.d, open_idx=lot.idx, expiry_eff=exp,
                expiry_ym=f0.expiry_ym, expired=expired, expiry_unknown=exp is None,
                settlement_unpriced=(expired or at_exp) and not est, est_settled=est,
                carried_in=lot.d < window_start))
    return FifoResult(fills=ordered, events=events, segments=segments, est_segments=est_segments,
                      residual_lots=residual, window_start=window_start, as_of=as_of, spot=spot,
                      meta=symbol_meta_of(ordered))


def build_closed_trades(segments: Iterable[Segment]) -> list[ClosedTrade]:
    """Group segments sharing (symbol, close order, close date, close kind)."""
    groups: dict[tuple, list[Segment]] = {}
    for s in segments:
        key = (s.symbol, s.close_order_id, s.close_date, s.close_kind,
               s.expiry_eff if s.estimated else None)
        groups.setdefault(key, []).append(s)
    out: list[ClosedTrade] = []
    for segs in groups.values():
        q = sum(s.qty for s in segs)
        s0 = segs[0]
        mins = [s.holding_minutes for s in segs]
        out.append(ClosedTrade(
            symbol=s0.symbol, underlying=s0.underlying, itype=s0.itype, expiry_ym=s0.expiry_ym,
            expiry_eff=s0.expiry_eff, side=s0.side, qty=q, pnl=sum(s.pnl for s in segs),
            entry_avg=sum(s.qty * s.entry_px for s in segs) / q,
            exit_avg=sum(s.qty * s.exit_px for s in segs) / q, close_date=s0.close_date,
            close_dt=s0.close_dt,
            holding_minutes=(sum(s.qty * m for s, m in zip(segs, mins)) / q
                             if all(m is not None for m in mins) else None),
            holding_days=sum(s.qty * s.holding_days for s in segs) / q,
            same_day=all(s.same_day for s in segs), estimated=s0.estimated,
            carried_in=any(s.carried_in for s in segs),
            open_idxs=tuple(sorted({s.open_idx for s in segs})), close_idx=s0.close_idx,
            n_segments=len(segs)))
    out.sort(key=lambda t: (t.close_date, t.close_dt or datetime.min, t.close_idx, t.symbol))
    return out


# ── EOD position sweep ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PosSnap:
    qty: int                # signed units
    avg: float
    carried: int            # abs units still carried from before the window start


def sweep_positions(res: FifoResult, cutoffs: list[date]) -> dict[date, dict[str, PosSnap]]:
    """EOD positions as of each cutoff date (events with trade_date <= cutoff).

    Expired symbols (cutoff >= expiry_eff) hold no exposure, whether or not they were
    settled by an estimate.  ``carried`` = abs units still outstanding from before the
    window start (FIFO closes the oldest lots first)."""
    out: dict[date, dict[str, PosSnap]] = {}
    state: dict[str, tuple[int, float]] = {}
    carried: dict[str, int] = {}
    ev = res.events
    i = 0
    started = False
    for c in sorted(set(cutoffs)):
        while i < len(ev) and ev[i].fill.trade_date <= c:
            e = ev[i]
            sym = e.fill.symbol
            if not started and e.fill.trade_date >= res.window_start:
                started = True
                carried = {s: abs(q) for s, (q, _a) in state.items()}
            if started and sym in carried:
                carried[sym] = max(0, carried[sym] - e.closed_qty)
            state[sym] = (e.pos_after, e.avg_after or 0.0)
            i += 1
        if not started and c >= res.window_start:
            started = True
            carried = {s: abs(q) for s, (q, _a) in state.items()}
        snap: dict[str, PosSnap] = {}
        for sym, (q, a) in state.items():
            if q == 0:
                continue
            exp = res.meta[sym].expiry_eff
            if exp is not None and c >= exp:
                continue
            snap[sym] = PosSnap(q, a, min(abs(q), carried.get(sym, 0)))
        out[c] = snap
    return out


def symbol_meta_of(fills: Iterable[Fill]) -> dict[str, Fill]:
    meta: dict[str, Fill] = {}
    for f in fills:
        meta.setdefault(f.symbol, f)
    return meta
