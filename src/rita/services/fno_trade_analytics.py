"""F42 Phase 3 — pure analyses 1-6 over the FIFO result (overtrading, win/loss, build-up,
market-turn, margin-trap, planned-vs-actual stops, reconciliation).

No I/O, no DB, no settings import: callers pass a ``cfg`` object exposing the
TradeAnalysisSettings attributes.  Every number is MEASURED from the user's own rows unless a
block says ESTIMATE.  Each sub-analysis returns its own ``definition`` and ``assumptions``.
Returned structures are plain dicts (the service validates them against the Pydantic schema).
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from rita.services.fno_trade_fifo import (
    ClosedTrade, FifoResult, FillEvent, Segment, SpotSeries, build_closed_trades,
    intrinsic, sweep_positions,
)

EPS = 1e-9
TOP_N = 5


# ── inputs ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LedgerRow:
    posting_date: date
    debit: float
    credit: float
    net_balance: Optional[float]
    seq: int


@dataclass(frozen=True)
class PnlLine:
    symbol: str
    underlying: Optional[str]
    expiry_ym: Optional[str]
    period_from: date
    period_to: date
    realized_pnl: Optional[float]
    open_quantity: Optional[int]
    open_quantity_type: Optional[str]


@dataclass(frozen=True)
class ChargePeriod:
    period_from: date
    period_to: date
    total: float
    period_turnover: float


@dataclass(frozen=True)
class LotInfo:
    """Lot sizes from the Kite NFO master, passed in by the caller (never static)."""
    available: bool = False
    by_symbol: dict[str, int] = field(default_factory=dict)
    by_underlying: dict[str, int] = field(default_factory=dict)

    def lot_size(self, symbol: str, underlying: str) -> tuple[Optional[int], str]:
        if not self.available:
            return None, "unknown"
        if symbol in self.by_symbol:
            return self.by_symbol[symbol], "kite_master"
        if underlying in self.by_underlying:
            return self.by_underlying[underlying], "underlying_current"
        return None, "unknown"


@dataclass
class Ctx:
    res: FifoResult
    cfg: Any
    date_from: date
    date_to: date
    include_est: bool
    spot: dict[str, SpotSeries]
    ts_coverage: float
    trades: list[ClosedTrade]       # closed in window, include flag applied
    segs: list[Segment]             # closed in window, include flag applied
    events: list[FillEvent]         # events dated in window
    opened_pnl: dict[int, float]    # opening fill idx -> pnl of its closed segments

    @property
    def ts_ok(self) -> bool:
        return self.ts_coverage >= self.cfg.analytics_min_timestamp_coverage


def make_ctx(res: FifoResult, cfg: Any, date_from: date, date_to: date, include_est: bool,
             spot: dict[str, SpotSeries]) -> Ctx:
    segs = [s for s in res.all_segments(include_est) if s.close_date >= date_from]
    events = [e for e in res.events if e.fill.trade_date >= date_from]
    n_ts = sum(1 for e in events if e.fill.exec_dt is not None)
    cov = n_ts / len(events) if events else 0.0
    opened: dict[int, float] = defaultdict(float)
    for s in segs:
        opened[s.open_idx] += s.pnl
    return Ctx(res=res, cfg=cfg, date_from=date_from, date_to=date_to, include_est=include_est,
               spot=spot, ts_coverage=cov, trades=build_closed_trades(segs), segs=segs,
               events=events, opened_pnl=dict(opened))


# ── small helpers ───────────────────────────────────────────────────────────────


def pct_linear(vals: list[float], p: float) -> Optional[float]:
    if not vals:
        return None
    v = sorted(vals)
    k = (len(v) - 1) * p / 100.0
    lo = math.floor(k)
    hi = math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def pct_nearest(vals: list[float], p: float) -> Optional[float]:
    """Nearest-rank percentile (always an observed value)."""
    if not vals:
        return None
    v = sorted(vals)
    return v[max(0, math.ceil(p / 100.0 * len(v)) - 1)]


def _r(v: Optional[float], d: int = 2) -> Optional[float]:
    return None if v is None else round(float(v), d)


def _iso(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _win_rate(wins: int, losses: int) -> Optional[float]:
    return _r(wins / (wins + losses) * 100.0) if (wins + losses) else None


def delta_sign(itype: str, side: int) -> int:
    """Direction-only delta proxy: long CE / short PE = +1, short CE / long PE = -1."""
    return side if itype == "CE" else -side


def _hhmm(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%H:%M") if dt else None


def _info(definition: str, assumptions: list[str]) -> dict[str, Any]:
    return {"definition": definition, "assumptions": assumptions}


# ── win / loss ──────────────────────────────────────────────────────────────────


def winloss_stats(trades: list[ClosedTrade]) -> dict[str, Any]:
    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > EPS]
    losses = [p for p in pnls if p < -EPS]
    n_scratch = len(pnls) - len(wins) - len(losses)
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = abs(sum(losses) / len(losses)) if losses else None
    payoff = avg_win / avg_loss if avg_win is not None and avg_loss else None
    wr = len(wins) / (len(wins) + len(losses)) if (wins or losses) else None
    expectancy = (sum(pnls) / len(pnls)) if pnls else None
    gross_loss = abs(sum(losses))
    streak = best = 0
    for t in sorted(trades, key=lambda x: (x.close_date, x.close_dt or datetime.min, x.close_idx)):
        if t.pnl < -EPS:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return {
        "n": len(trades), "wins": len(wins), "losses": len(losses), "scratch": n_scratch,
        "win_rate": _r(wr * 100.0) if wr is not None else None,
        "avg_win": _r(avg_win), "avg_loss": _r(avg_loss), "payoff": _r(payoff, 3),
        "expectancy": _r(expectancy), "profit_factor": _r(sum(wins) / gross_loss, 3) if gross_loss > EPS else None,
        "breakeven_win_rate": _r(100.0 / (1.0 + payoff)) if payoff is not None else None,
        "largest_win": _r(max(wins)) if wins else None,
        "largest_loss": _r(min(losses)) if losses else None,
        "max_loss_streak": best, "pnl": _r(sum(pnls)),
    }


def _group_stats(trades: list[ClosedTrade], keyf: Any) -> list[dict[str, Any]]:
    groups: dict[str, list[ClosedTrade]] = defaultdict(list)
    for t in trades:
        groups[str(keyf(t))].append(t)
    out = []
    for k in sorted(groups):
        ts = groups[k]
        w = sum(1 for t in ts if t.pnl > EPS)
        lo = sum(1 for t in ts if t.pnl < -EPS)
        out.append({"key": k, "n": len(ts), "win_rate": _win_rate(w, lo),
                    "pnl": _r(sum(t.pnl for t in ts))})
    return out


# ── 3.1 overtrading ───────────────────────────────────────────────────────────────

def _fmt_min(m: int) -> str:
    return f"{m // 60}h" if m % 60 == 0 else f"{m}m"


def _bucket_labels(edges: Any) -> list[str]:
    """Same-day holding bucket labels for ascending minute edges (default 5 / 30 / 120)."""
    e0, e1, e2 = (int(x) for x in edges)
    return [f"<{e0}m", f"{e0}-{e1}m", f"{e1}m-{_fmt_min(e2)}", f">{_fmt_min(e2)} same-day",
            "1d", "2-5d", ">5d"]


_Q1 = 25.0
_Q3 = 100.0 - _Q1


def _bucket(t: ClosedTrade, ts_ok: bool, edges: Any) -> str:
    labels = _bucket_labels(edges)
    if t.same_day:
        if not ts_ok or t.holding_minutes is None:
            return "same-day (no timestamps)"
        m = t.holding_minutes
        return (labels[0] if m < edges[0] else labels[1] if m < edges[1]
                else labels[2] if m < edges[2] else labels[3])
    d = t.holding_days
    return "1d" if d <= 1 else "2-5d" if d <= 5 else ">5d"


def _clusters(events: list[FillEvent], window_min: int) -> list[list[FillEvent]]:
    by_day: dict[date, list[FillEvent]] = defaultdict(list)
    for e in events:
        if e.fill.exec_dt is not None:
            by_day[e.fill.trade_date].append(e)
    out: list[list[FillEvent]] = []
    for d in sorted(by_day):
        evs = sorted(by_day[d], key=lambda e: (e.fill.exec_dt, e.idx))
        cur = [evs[0]]
        for e in evs[1:]:
            gap = (e.fill.exec_dt - cur[-1].fill.exec_dt).total_seconds() / 60.0  # type: ignore[operator]
            if gap <= window_min:
                cur.append(e)
            else:
                out.append(cur)
                cur = [e]
        out.append(cur)
    return out


def overtrading(ctx: Ctx, charge_periods: list[ChargePeriod]) -> dict[str, Any]:
    cfg = ctx.cfg
    evs = ctx.events
    fills_by_day: dict[date, int] = defaultdict(int)
    for e in evs:
        fills_by_day[e.fill.trade_date] += 1
    counts = list(fills_by_day.values())
    market_days: Optional[int] = None
    spot_dates = {d for s in ctx.spot.values() for d in s.dates if ctx.date_from <= d <= ctx.date_to}
    if spot_dates:
        market_days = len(spot_dates)
    activity = {
        "fills_total": len(evs), "orders_total": len({e.fill.order_id for e in evs}),
        "active_days": len(fills_by_day), "market_days": market_days,
        "fills_per_day": {
            "mean": _r(sum(counts) / len(counts)) if counts else None,
            "median": _r(statistics.median(counts)) if counts else None,
            "p90": _r(pct_linear([float(c) for c in counts], 90)),
            "max": max(counts) if counts else None},
        **_info("Fills (executions) per calendar day on which you traded, inside the filter window.",
                ["A fill is one tradebook row; one order can produce several fills.",
                 "market_days = distinct days with a spot close in the window (null without spot data)."]),
    }

    wk: dict[str, dict[str, Any]] = {}
    for e in evs:
        iso = e.fill.trade_date.isocalendar()
        k = f"{iso[0]}-W{iso[1]:02d}"
        w = wk.setdefault(k, {"week": k, "fills": 0, "days": set(), "closed_trades": 0})
        w["fills"] += 1
        w["days"].add(e.fill.trade_date)
    for t in ctx.trades:
        iso = t.close_date.isocalendar()
        k = f"{iso[0]}-W{iso[1]:02d}"
        if k in wk:
            wk[k]["closed_trades"] += 1
        else:
            wk[k] = {"week": k, "fills": 0, "days": set(), "closed_trades": 1}
    weekly = [{"week": w["week"], "fills": w["fills"], "active_days": len(w["days"]),
               "closed_trades": w["closed_trades"]} for _, w in sorted(wk.items())]

    def by(keyf_fill: Any, keyf_trade: Any) -> list[dict[str, Any]]:
        fills: dict[str, int] = defaultdict(int)
        for e in evs:
            fills[str(keyf_fill(e.fill))] += 1
        stats = {r["key"]: r for r in _group_stats(ctx.trades, keyf_trade)}
        out = []
        for k in sorted(set(fills) | set(stats)):
            r = stats.get(k, {"n": 0, "win_rate": None, "pnl": 0.0})
            out.append({"key": k, "fills": fills.get(k, 0), "closed_trades": r["n"],
                        "win_rate": r["win_rate"], "pnl": r["pnl"]})
        return out

    by_expiry = by(lambda f: f.expiry_ym or "unknown", lambda t: t.expiry_ym or "unknown")
    by_underlying = by(lambda f: f.underlying, lambda t: t.underlying)

    # holding
    ts_ok = ctx.ts_ok
    bucket_counts: dict[str, int] = defaultdict(int)
    for t in ctx.trades:
        bucket_counts[_bucket(t, ts_ok, ctx.cfg.holding_bucket_edges_minutes)] += 1
    labels = _bucket_labels(ctx.cfg.holding_bucket_edges_minutes)
    if bucket_counts.get("same-day (no timestamps)"):
        labels.insert(3, "same-day (no timestamps)")
    mins = [t.holding_minutes for t in ctx.trades if t.same_day and t.holding_minutes is not None]
    multi = [t.holding_days for t in ctx.trades if not t.same_day]
    holding = {
        "available": ts_ok or bool(multi),
        "reason": None if ts_ok else "no_timestamps",
        "median_minutes": _r(pct_linear(mins, 50)) if ts_ok else None,
        "p25": _r(pct_linear(mins, _Q1)) if ts_ok else None,
        "p75": _r(pct_linear(mins, _Q3)) if ts_ok else None,
        "p90": _r(pct_linear(mins, 90)) if ts_ok else None,
        "buckets": [{"label": b, "count": bucket_counts.get(b, 0)} for b in labels],
        "median_days_multiday": _r(pct_linear(multi, 50)),
        **_info("How long closed trades were held. Minute statistics cover same-day trades only; "
                "multi-day trades are bucketed by calendar days.",
                ["Holding time is from the opening fill to the closing fill of each FIFO-matched slice, "
                 "quantity-weighted per closed trade.",
                 "Minute statistics are withheld when too few fills carry an execution time.",
                 "Expiry-estimated trades count as multi-day or same-day by dates only."]),
    }

    # churn
    q_all = sum(s.qty for s in ctx.segs)
    q_same = sum(s.qty for s in ctx.segs if s.same_day)
    same_tr = [t for t in ctx.trades if t.same_day]
    churn = {
        "churn_qty_pct": _r(q_same / q_all * 100.0) if q_all else None,
        "churn_count_pct": _r(len(same_tr) / len(ctx.trades) * 100.0) if ctx.trades else None,
        "churn_pnl": _r(sum(t.pnl for t in same_tr)),
        "same_day_trades": len(same_tr),
        **_info("Share of closed volume and closed trades opened and closed on the same day, and the "
                "gross P&L those same-day trades produced.",
                ["Based on FIFO-matched closed trades; positions still open are not counted.",
                 "P&L is gross of charges."]),
    }

    # bursts + re-entries
    if ts_ok:
        clusters = _clusters(evs, cfg.burst_window_minutes)
        bursts = [c for c in clusters if len(c) >= cfg.burst_min_fills]
        top = sorted(bursts, key=lambda c: (-len(c), c[0].fill.exec_dt))[:TOP_N]
        top_out = [{"date": c[0].fill.trade_date.isoformat(), "start": _hhmm(c[0].fill.exec_dt),
                    "fills": len(c), "symbols_count": len({e.fill.symbol for e in c}),
                    "pnl": _r(sum(e.realised for e in c))} for c in top]
        last_loss: dict[str, datetime] = {}
        re_n = 0
        re_pnl = 0.0
        for e in evs:
            f = e.fill
            if f.exec_dt is None:
                continue
            ll = last_loss.get(f.underlying)
            if e.opened_qty > 0 and ll is not None and \
                    0 <= (f.exec_dt - ll).total_seconds() / 60.0 <= cfg.reentry_window_minutes:
                re_n += 1
                re_pnl += ctx.opened_pnl.get(e.idx, 0.0)
            if e.closed_qty > 0 and e.realised < -EPS:
                last_loss[f.underlying] = f.exec_dt
        bursts_block = {"available": True, "reason": None, "count": len(bursts), "top": top_out,
                        "reentries_after_loss": {"count": re_n, "pnl": _r(re_pnl)}}
    else:
        bursts_block = {"available": False, "reason": "no_timestamps", "count": None, "top": [],
                        "reentries_after_loss": {"count": None, "pnl": None}}
    bursts_block.update(_info(
        "A burst is a run of fills on one day where consecutive fills are within the burst window; "
        "a re-entry is an opening fill in the same underlying within the re-entry window after a "
        "losing close.",
        ["Windows come from configuration (burst_window_minutes, burst_min_fills, reentry_window_minutes).",
         "Re-entry P&L = closed P&L of the slices those opening fills created (open slices not counted).",
         "Needs execution timestamps."]))

    charges = _charges(ctx, charge_periods)
    wl = winloss_stats(ctx.trades)
    wl["by_side"] = _group_stats(ctx.trades, lambda t: "long" if t.side > 0 else "short")
    wl["by_underlying"] = _group_stats(ctx.trades, lambda t: t.underlying)
    meas = [t for t in ctx.trades if not t.estimated]
    mw = winloss_stats(meas)
    wl["measured_only"] = {"n": mw["n"], "win_rate": mw["win_rate"], "expectancy": mw["expectancy"],
                           "pnl": mw["pnl"]}
    wl.update(_info(
        "Closed-trade outcome statistics: win rate, average win/loss, payoff, expectancy, profit "
        "factor, breakeven win rate and longest losing streak.",
        ["Wins/losses are gross of charges; scratch (exactly zero) trades are excluded from the win rate.",
         "payoff = average win / average loss; breakeven win rate = 1 / (1 + payoff).",
         "Streaks are ordered by close time. 'measured_only' excludes expiry-estimated closes."]))
    return {"activity": activity, "weekly": weekly, "by_expiry": by_expiry,
            "by_underlying": by_underlying, "holding": holding, "churn": churn,
            "bursts": bursts_block, "charges": charges, "winloss": wl}


def _charges(ctx: Ctx, periods: list[ChargePeriod]) -> dict[str, Any]:
    info = _info(
        "ESTIMATE of charges attributable to the window: the sheet's charges total split by the "
        "window's share of turnover, compared with gross closed P&L.",
        ["One charges total per sheet period (non-overlapping periods only).",
         "Allocation = total x window turnover / period turnover, where period turnover covers ALL your "
         "tradebook fills in that period (sum of quantity x price).",
         "Only an allocation: the sheet does not itemise charges by symbol."])
    if not periods:
        return {"available": False, "reason": "no_pnl_sheet", "total_sheet": None, "est_window": None,
                "pct_of_gross": None, "per_closed_trade": None, "breakeven_gross_per_trade": None,
                "breakeven_trades_needed": None, "estimated": True, "net_gross_negative": False, **info}
    est = 0.0
    total = 0.0
    for p in periods:
        total += p.total
        lo, hi = max(p.period_from, ctx.date_from), min(p.period_to, ctx.date_to)
        if hi < lo or p.period_turnover <= 0:
            continue
        wt = sum(e.fill.qty * e.fill.price for e in ctx.events if lo <= e.fill.trade_date <= hi)
        est += p.total * wt / p.period_turnover
    gross = sum(t.pnl for t in ctx.trades)
    n = len(ctx.trades)
    neg = n > 0 and gross <= 0
    avg_gross = gross / n if n else None
    return {
        "available": True, "reason": None, "total_sheet": _r(total), "est_window": _r(est),
        "pct_of_gross": _r(est / gross * 100.0) if (n and gross > 0) else None,
        "per_closed_trade": _r(est / n) if n else None,
        "breakeven_gross_per_trade": _r(est / n) if n else None,
        "breakeven_trades_needed": math.ceil(est / avg_gross) if avg_gross and avg_gross > 0 else None,
        "estimated": True, "net_gross_negative": neg, **info}


# ── 3.2 build-up ────────────────────────────────────────────────────────────────


def _chains(ctx: Ctx, spot: dict[str, SpotSeries]) -> list[dict[str, Any]]:
    """Flat-to-flat position chains per symbol, from ALL events (carried-in chains included)."""
    res = ctx.res
    cur: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    est_by_sym: dict[str, float] = defaultdict(float)
    if ctx.include_est:
        for s in res.est_segments:
            est_by_sym[s.symbol] += s.pnl
    est_syms = {s.symbol for s in res.est_segments} if ctx.include_est else set()

    def new_chain(e: FillEvent) -> dict[str, Any]:
        f = e.fill
        return {"symbol": f.symbol, "underlying": f.underlying, "expiry_ym": f.expiry_ym,
                "itype": f.itype, "open_date": f.trade_date, "close_date": None, "peak_qty": 0,
                "adds": 0, "adverse_adds": 0, "spot_adverse_adds": 0, "pnl_measured": 0.0,
                "still_open": True, "side": f.sign}

    for e in res.events:
        f = e.fill
        c = cur.get(f.symbol)
        if c is None and e.opened_qty > 0:
            c = cur[f.symbol] = new_chain(e)
        if c is None:
            continue
        c["pnl_measured"] += e.realised
        if e.cls == "scale_in":
            c["adds"] += 1
            c["adverse_adds"] += 1 if e.adverse_add else 0
            ss = spot.get(f.underlying)
            if ss:
                s0, s1 = ss.on_or_before(c["open_date"]), ss.on_or_before(f.trade_date)
                if s0 and s1:
                    dsign = delta_sign(f.itype, f.sign)
                    if dsign * (s1 / s0 - 1.0) * 100.0 < -ctx.cfg.adverse_spot_pct:
                        c["spot_adverse_adds"] += 1
        c["peak_qty"] = max(c["peak_qty"], abs(e.pos_after), abs(e.pos_before))
        if e.cls in ("close", "flip"):
            c["close_date"] = f.trade_date
            c["still_open"] = False
            out.append(c)
            del cur[f.symbol]
            if e.cls == "flip":
                n = cur[f.symbol] = new_chain(e)
                n["peak_qty"] = abs(e.pos_after)
    for sym, c in cur.items():
        c["pnl_estimated"] = _r(est_by_sym.get(sym)) if sym in est_syms else None
        if sym in est_syms:
            c["still_open"] = False
            exp = res.meta[sym].expiry_eff
            c["close_date"] = exp
        out.append(c)
    return [c for c in out if c["close_date"] is None or c["close_date"] >= ctx.date_from]


def buildup(ctx: Ctx, lots: LotInfo) -> dict[str, Any]:
    res = ctx.res
    evs = ctx.events
    cfg = ctx.cfg
    events_ct = {k: 0 for k in ("open_new", "scale_in", "scale_out", "close", "flip")}
    for e in evs:
        events_ct[e.cls] += 1
    entries = [e for e in evs if e.opened_qty > 0]
    adverse = [e for e in evs if e.adverse_add]
    adv_idx = {e.idx for e in adverse}
    adv_pnl = sum(ctx.opened_pnl.get(i, 0.0) for i in adv_idx)
    adv_open = sum(lot.qty for lot in res.open_lots(ctx.include_est) if lot.open_idx in adv_idx)

    chains = _chains(ctx, ctx.spot)
    spot_adv: Optional[int] = None
    if ctx.spot:
        spot_adv = sum(c["spot_adverse_adds"] for c in chains)
    top_chains = sorted(chains, key=lambda c: (c["pnl_measured"], c["symbol"]))[:TOP_N * 2]
    chains_out = [{
        "symbol": c["symbol"], "expiry_ym": c["expiry_ym"], "side": "long" if c["side"] > 0 else "short",
        "open_date": _iso(c["open_date"]), "close_date": _iso(c["close_date"]),
        "peak_qty": c["peak_qty"], "adds": c["adds"], "adverse_adds": c["adverse_adds"],
        "pnl_measured": _r(c["pnl_measured"]), "pnl_estimated": c.get("pnl_estimated"),
        "still_open": c["still_open"]} for c in top_chains]
    chain_totals = {"count": len(chains), "with_adverse_add": sum(1 for c in chains if c["adverse_adds"]),
                    "max_adds": max((c["adds"] for c in chains), default=0)}

    # daily timeline per (underlying, expiry_ym)
    act: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    active_days: set[date] = set()
    for e in evs:
        f = e.fill
        k = (f.underlying, f.expiry_ym or "unknown", f.trade_date)
        active_days.add(f.trade_date)
        if e.cls in ("open_new", "flip"):
            act[k]["opened"] += e.opened_qty
        if e.cls == "scale_in":
            act[k]["scale_in"] += e.opened_qty
        if e.cls == "scale_out":
            act[k]["scale_out"] += e.closed_qty
        if e.cls in ("close", "flip"):
            act[k]["closed"] += e.closed_qty
        if e.adverse_add:
            act[k]["adverse"] += e.opened_qty
    spot_days = {d for s in ctx.spot.values() for d in s.dates if ctx.date_from <= d <= ctx.date_to}
    days = sorted(active_days | spot_days)
    snaps = sweep_positions(res, days)
    meta = res.meta
    timeline: list[dict[str, Any]] = []
    for d in days:
        groups: dict[tuple, dict[str, Any]] = {}
        for sym, p in snaps[d].items():
            m = meta[sym]
            g = groups.setdefault((m.underlying, m.expiry_ym or "unknown"), {
                "long": 0, "short": 0, "proxy": 0.0, "syms": 0, "carried": 0,
                "long_lots": 0.0, "short_lots": 0.0, "lots_ok": True})
            if p.qty > 0:
                g["long"] += p.qty
            else:
                g["short"] += -p.qty
                if m.strike is not None:
                    g["proxy"] += -p.qty * m.strike
            g["syms"] += 1
            g["carried"] += p.carried
            ls, _basis = lots.lot_size(sym, m.underlying)
            if ls:
                g["long_lots" if p.qty > 0 else "short_lots"] += abs(p.qty) / ls
            else:
                g["lots_ok"] = False
        keys = set(groups) | {(u, x) for (u, x, dd) in act if dd == d}
        for (u, x) in sorted(keys):
            g = groups.get((u, x), {"long": 0, "short": 0, "proxy": 0.0, "syms": 0, "carried": 0,
                                    "long_lots": 0.0, "short_lots": 0.0, "lots_ok": True})
            a = act.get((u, x, d), {})
            timeline.append({
                "underlying": u, "expiry_ym": x, "date": d.isoformat(), "long_units": g["long"],
                "short_units": g["short"], "opened_units": a.get("opened", 0),
                "scale_in_units": a.get("scale_in", 0), "scale_out_units": a.get("scale_out", 0),
                "closed_units": a.get("closed", 0), "adverse_add_units": a.get("adverse", 0),
                "short_notional_proxy": _r(g["proxy"]), "open_symbols": g["syms"],
                "carried_in": g["carried"],
                "long_lots": _r(g["long_lots"]) if lots.available and g["lots_ok"] else None,
                "short_lots": _r(g["short_lots"]) if lots.available and g["lots_ok"] else None})
    syms_in_scope = {e.fill.symbol for e in evs}
    exact = sum(1 for s in syms_in_scope if s in lots.by_symbol) if lots.available else 0
    fallback = sum(1 for s in syms_in_scope if lots.lot_size(s, meta[s].underlying)[1] == "underlying_current")
    cov = _r(exact / len(syms_in_scope) * 100.0) if (syms_in_scope and lots.available) else None
    basis = ("unknown" if not lots.available else "kite_master" if exact == len(syms_in_scope) and exact
             else "mixed" if exact and fallback else "underlying_current" if fallback else "unknown")
    return {
        "timeline": timeline[: max(cfg.analytics_max_rows * 5, 1)], "events": events_ct,
        "averaging": {
            "adverse_add_fills": len(adverse), "adverse_add_units": sum(e.opened_qty for e in adverse),
            "share_of_entries_pct": _r(len(adverse) / len(entries) * 100.0) if entries else None,
            "adverse_add_closed_pnl": _r(adv_pnl), "adverse_add_open_units": adv_open,
            "spot_adverse_adds": spot_adv,
            **_info("Adding to an open position at a price worse than its average entry (long: lower, "
                    "short: higher) is counted as averaging down.",
                    ["Exact: compares the fill price with the average entry of the lots open just before the fill.",
                     "Closed P&L = gross P&L of FIFO slices opened by those fills; slices still open are "
                     "reported as units only (not priced).",
                     "spot_adverse_adds additionally needs spot data: adds made after the spot had moved "
                     "against the position (by more than adverse_spot_pct) since the position was first opened."])},
        "chains": chains_out, "chain_totals": chain_totals,
        "chains_info": _info("A chain runs from a flat position to flat again in one symbol (a fill that "
                             "crosses zero ends one chain and starts the next).",
                             ["Chains still open show their measured P&L so far; expiry-estimated chains are "
                              "marked with an estimated P&L."]),
        "lots": {"lots_available": lots.available, "lots_basis": basis, "coverage_pct": cov},
        "timeline_info": _info("End-of-day long/short units per underlying and expiry, with the units "
                               "opened, added, reduced and closed that day.",
                               ["Units are contracts as traded (quantity), not lots; lots appear only "
                                "when the Kite master knows the symbol.",
                                "short_notional_proxy = sum of short units x strike (an ESTIMATE, not margin).",
                                "Expired contracts carry no exposure after their expiry date."]),
    }


# ── spot returns / market turn ──────────────────────────────────────────────────


def _returns(ss: SpotSeries) -> dict[date, tuple[float, float, Optional[float]]]:
    """date -> (close_t, close_{t-1}, r_{t-1} pct) with r_t computed by the caller."""
    out: dict[date, tuple[float, float, Optional[float]]] = {}
    prev_r: Optional[float] = None
    for i in range(1, len(ss.dates)):
        c0, c1 = ss.closes[i - 1], ss.closes[i]
        r = (c1 / c0 - 1.0) * 100.0 if c0 else 0.0
        out[ss.dates[i]] = (c1, c0, prev_r)
        prev_r = r
    return out


def _sgn(x: Optional[float]) -> int:
    return 0 if x is None or abs(x) < EPS else (1 if x > 0 else -1)


def market_turn(ctx: Ctx) -> dict[str, Any]:
    cfg = ctx.cfg
    res = ctx.res
    info = _info(
        "Days the underlying moved by at least the turn threshold, whether you were positioned the "
        "wrong way going in, and the P&L you realised on those days.",
        ["Return r = close / previous close - 1. A reversal day moves at least the threshold in the "
         "opposite direction to the previous day's return; a zero or missing previous return is not a "
         "reversal, but the day is still listed as a big-move day.",
         "Positioning is the end-of-previous-day book (no intraday hindsight). Direction proxy only: "
         "long CE / short PE = bullish (+1), short CE / long PE = bearish (-1); bias = sum of sign x open units.",
         "A position is adverse-exposed on a day when sign(bias) x return < 0.",
         "realised_pnl_day is MEASURED: gross P&L of slices closed that day (realised timing, not "
         "mark-to-market); it includes trades opened and closed that day, so it is split into "
         "from_carried_in (opened before that day) and from_opened_that_day.",
         "delta1_bound_pnl is an ESTIMATE: bias units x spot change, an upper bound on the option move "
         "(option price moves no more than the underlying).",
         "Option price history is not used."])
    worst_days = _worst_days(ctx)
    base = {"kpis": {"n_turn_days": 0, "n_big_move_days": 0, "n_adverse_exposed": 0,
                     "adverse_exposed_pct": None, "realised_pnl_turn_adverse": None,
                     "realised_from_carried_in": None, "realised_from_opened_that_day": None,
                     "avg_realised_other_days": None},
            "turn_days": [], "series": [], "worst_days": worst_days, "info": info,
            "delta1_note": "delta1_bound_pnl = bias units x spot change; an estimate that bounds, not "
                           "measures, the option P&L."}
    if not ctx.spot:
        return {"spot": {"available": False, "last_date": None, "stale": None}, **base}
    last = max(d for s in ctx.spot.values() for d in s.dates)
    stale = last < min(ctx.date_to, res.as_of) - timedelta(days=ctx.cfg.spot_stale_days)
    unds = sorted(ctx.spot)
    rows: list[dict[str, Any]] = []
    seg_by_key: dict[tuple, list[Segment]] = defaultdict(list)
    for s in ctx.segs:
        seg_by_key[(s.underlying, s.close_date)].append(s)
    series_out = []
    all_cutoffs: list[date] = []
    rets = {u: _returns(ctx.spot[u]) for u in unds}
    for u in unds:
        for d in rets[u]:
            if ctx.date_from <= d <= ctx.date_to:
                all_cutoffs.append(d - timedelta(days=1))
    snaps = sweep_positions(res, all_cutoffs)
    meta = res.meta
    for u in unds:
        s_dates, s_close, s_bias, s_pnl, s_flag = [], [], [], [], []
        for d in ctx.spot[u].dates:
            if d not in rets[u] or not (ctx.date_from <= d <= ctx.date_to):
                continue
            c1, c0, r_prev = rets[u][d]
            r = (c1 / c0 - 1.0) * 100.0 if c0 else 0.0
            snap = snaps[d - timedelta(days=1)]
            bias = 0
            syms_in = []
            proxy_in = 0.0
            for sym, p in snap.items():
                m = meta[sym]
                if m.underlying != u:
                    continue
                bias += delta_sign(m.itype, 1 if p.qty > 0 else -1) * abs(p.qty)
                syms_in.append((abs(p.qty), sym))
                if p.qty < 0 and m.strike is not None:
                    proxy_in += -p.qty * m.strike
            segs = seg_by_key.get((u, d), [])
            carried = sum(s.pnl for s in segs if s.open_date < d)
            opened = sum(s.pnl for s in segs if s.open_date >= d)
            big = abs(r) >= cfg.turn_threshold_pct
            rev = big and _sgn(r_prev) != 0 and _sgn(r) != _sgn(r_prev)
            adverse = _sgn(bias) * r < 0
            row = {
                "date": d.isoformat(), "underlying": u, "spot_close": _r(c1), "ret_pct": _r(r, 3),
                "is_reversal": rev, "bias_units_in": bias,
                "bias_label": "bullish" if bias > 0 else "bearish" if bias < 0 else "flat",
                "adverse_exposed": adverse, "open_symbols_in": [s for _, s in sorted(syms_in, reverse=True)[:6]],
                "short_notional_proxy_in": _r(proxy_in), "realised_pnl_day": _r(carried + opened),
                "realised_from_carried_in": _r(carried), "realised_from_opened_that_day": _r(opened),
                "delta1_bound_pnl": _r(bias * (c1 - c0))}
            rows.append({**row, "_big": big})
            s_dates.append(row["date"])
            s_close.append(row["spot_close"])
            s_bias.append(bias)
            s_pnl.append(row["realised_pnl_day"])
            s_flag.append(1 if rev else 0)
        series_out.append({"underlying": u, "dates": s_dates, "spot_close": s_close, "bias_units": s_bias,
                           "realised_pnl_day": s_pnl, "turn_flag": s_flag})
    big_rows = [r for r in rows if r["_big"]]
    turn_rows = [r for r in big_rows if r["is_reversal"]]
    adv_rows = [r for r in turn_rows if r["adverse_exposed"]]
    adv_keys = {(r["underlying"], r["date"]) for r in adv_rows}
    others = [r["realised_pnl_day"] for r in rows if (r["underlying"], r["date"]) not in adv_keys]
    kp = {
        "n_turn_days": len(turn_rows), "n_big_move_days": len(big_rows), "n_adverse_exposed": len(adv_rows),
        "adverse_exposed_pct": _r(len(adv_rows) / len(turn_rows) * 100.0) if turn_rows else None,
        "realised_pnl_turn_adverse": _r(sum(r["realised_pnl_day"] for r in adv_rows)) if turn_rows else None,
        "realised_from_carried_in": _r(sum(r["realised_from_carried_in"] for r in adv_rows)) if turn_rows else None,
        "realised_from_opened_that_day": _r(sum(r["realised_from_opened_that_day"] for r in adv_rows)) if turn_rows else None,
        "avg_realised_other_days": _r(sum(others) / len(others)) if others else None}
    big_out = [{k: v for k, v in r.items() if k != "_big"} for r in big_rows][: cfg.analytics_max_rows]
    return {"spot": {"available": True, "last_date": _iso(last), "stale": stale}, "kpis": kp,
            "turn_days": big_out, "series": series_out, "worst_days": worst_days, "info": info,
            "delta1_note": base["delta1_note"]}


def _worst_days(ctx: Ctx) -> list[dict[str, Any]]:
    by_day: dict[date, float] = defaultdict(float)
    for s in ctx.segs:
        by_day[s.close_date] += s.pnl
    losers = sorted((d for d in by_day if by_day[d] < -EPS), key=lambda d: (by_day[d], d))[:TOP_N]
    if not losers:
        return []
    snaps = sweep_positions(ctx.res, losers)
    out = []
    for d in sorted(losers, key=lambda x: (by_day[x], x)):
        syms = sorted(snaps[d].items(), key=lambda kv: -abs(kv[1].qty))[:8]
        out.append({"date": d.isoformat(), "realised_pnl_day": _r(by_day[d]),
                    "open_symbols": [s for s, _ in syms]})
    return out


# ── 3.4 margin trap + planned-vs-actual ────────────────────────────────────────────


def detect_balance_sign(rows: list[LedgerRow], tol_frac: float = 0.001, min_tol: float = 1.0,
                        cutoff: float = 0.6) -> tuple[Optional[int], Optional[float]]:
    """Sign s such that cash = s x net_balance, from day-to-day balance changes.

    For each pair of consecutive ledger days the day's net flow (credit - debit) must equal
    +/- the change between some balance of the previous day and some balance of that day."""
    by_day: dict[date, list[LedgerRow]] = defaultdict(list)
    for r in rows:
        if r.net_balance is not None:
            by_day[r.posting_date].append(r)
    pos = neg = total = 0
    days = sorted(by_day)
    for prev_d, d in zip(days, days[1:]):
        flow = sum(r.credit - r.debit for r in by_day[d])
        if abs(flow) <= EPS:
            continue
        total += 1
        tol = max(min_tol, abs(flow) * tol_frac)
        deltas = [c.net_balance - p.net_balance  # type: ignore[operator]
                  for p in by_day[prev_d] for c in by_day[d]]
        if any(abs(x - flow) <= tol for x in deltas):
            pos += 1
        if any(abs(x + flow) <= tol for x in deltas):
            neg += 1
    if not total:
        return None, None
    if pos >= neg:
        return (1 if pos / total >= cutoff else None), _r(pos / total * 100.0)
    return (-1 if neg / total >= cutoff else None), _r(neg / total * 100.0)


def cash_series(rows: list[LedgerRow], before: Optional[LedgerRow], sign: int, days: list[date],
                tolerance: float) -> tuple[dict[date, tuple[float, bool]], int, int]:
    """Per-day cash = sign x net_balance of the day-close ledger row; carry forward on days
    without ledger rows.  Returns (series, ambiguous_days, ledger_gap_days)."""
    by_day: dict[date, list[LedgerRow]] = defaultdict(list)
    for r in rows:
        by_day[r.posting_date].append(r)
    prev_nb: Optional[float] = before.net_balance if before else None
    out: dict[date, tuple[float, bool]] = {}
    ambiguous = gaps = 0
    for d in sorted(set(days) | set(by_day)):
        drows = by_day.get(d)
        if drows:
            with_nb = [r for r in drows if r.net_balance is not None]
            if with_nb:
                chosen = with_nb[-1]
                if prev_nb is not None:
                    flow = sum(r.credit - r.debit for r in drows)
                    expected = prev_nb + sign * flow
                    best = min(with_nb, key=lambda r: abs(r.net_balance - expected))  # type: ignore[operator]
                    if abs(best.net_balance - expected) <= tolerance:  # type: ignore[operator]
                        chosen = best
                    else:
                        ambiguous += 1
                prev_nb = chosen.net_balance
                out[d] = (sign * float(chosen.net_balance), False)  # type: ignore[arg-type]
                continue
        if prev_nb is not None:
            out[d] = (sign * float(prev_nb), True)
            gaps += 1
    return out, ambiguous, gaps


def _last_prices(ctx: Ctx) -> dict[str, tuple[list[date], list[float]]]:
    m: dict[str, tuple[list[date], list[float]]] = {}
    for f in ctx.res.fills:
        a = m.setdefault(f.symbol, ([], []))
        a[0].append(f.trade_date)
        a[1].append(f.price)
    return m


def _mark(prices: dict[str, tuple[list[date], list[float]]], sym: str, d: date,
          max_stale: int) -> Optional[float]:
    import bisect
    ds, ps = prices.get(sym, ([], []))
    i = bisect.bisect_right(ds, d)
    if not i or (d - ds[i - 1]).days > max_stale:
        return None
    return ps[i - 1]


def margin_trap(ctx: Ctx, ledger: list[LedgerRow], ledger_before: Optional[LedgerRow]) -> dict[str, Any]:
    cfg = ctx.cfg
    res = ctx.res
    info_cash = _info(
        "MEASURED from your ledger: settled cash balance per day (sign auto-detected), debit streaks and "
        "days below the low-cash threshold.",
        ["Cash is account-wide (all segments) and ignores the underlying/expiry filter; the exposure proxy "
         "covers in-scope symbols only, so other cash-consuming positions are invisible here.",
         "Ledger cash excludes blocked margin and unrealised P&L; no historical margin series exists in the data.",
         "Days without ledger rows carry the previous balance forward (ledger_gap_days).",
         "When several ledger rows share a day, the day-close row is the one whose balance best matches the "
         "previous close plus that day's net flow; otherwise the last row imported (ordering_ambiguous_days)."])
    info_trap = _info(
        "Low-cash days with open losers (proxy): days when ledger cash was below the threshold while at "
        "least one open position was at a known loss.",
        ["This is a proxy, not evidence that margin prevented square-off: no causal claim is made.",
         "A loser is a position whose last fill price (not older than loser_mark_max_stale_days) is adverse to "
         "its average entry; stale marks are counted as unmarked.",
         "short_notional_proxy = sum of short units x strike (ESTIMATE, not SPAN margin); "
         "long_premium_at_risk = units x average entry."])
    out: dict[str, Any] = {
        "ledger": {"available": False, "balance_sign": None, "balance_sign_match_pct": None,
                   "first": None, "last": None, "ordering_ambiguous_days": 0, "ledger_gap_days": 0},
        "cash": {"start": None, "end": None, "min": None, "min_date": None, "days_below_threshold": 0,
                 "days_negative": 0, "threshold": cfg.low_cash_threshold_inr, "info": info_cash},
        "cash_series": [], "debit_streaks": [],
        "exposure": {"peak_short_notional_proxy": None, "avg_proxy_to_cash_ratio": None,
                     "estimated": True},
        "trap": {"days": 0, "days_list": [], "loss_growth_est": None, "lots_unmarked": 0,
                 "info": info_trap},
        "stops": _stops(ctx, res),
    }
    all_rows = ([ledger_before] if ledger_before else []) + ledger
    sign, match = detect_balance_sign(
        all_rows, ctx.cfg.ledger_sign_tolerance_frac, ctx.cfg.ledger_sign_min_tolerance_inr,
        ctx.cfg.ledger_sign_match_cutoff)
    out["ledger"]["balance_sign_match_pct"] = match
    out["ledger"]["balance_sign"] = sign
    if ledger:
        out["ledger"]["first"] = _iso(ledger[0].posting_date)
        out["ledger"]["last"] = _iso(ledger[-1].posting_date)
    if sign is None or not (ledger or ledger_before):
        return out
    out["ledger"]["available"] = True
    spot_days = {d for s in ctx.spot.values() for d in s.dates if ctx.date_from <= d <= ctx.date_to}
    act_days = {e.fill.trade_date for e in ctx.events}
    days = sorted(spot_days | act_days | {r.posting_date for r in ledger})
    series, ambiguous, gaps = cash_series(ledger, ledger_before, sign, days, 1.0)
    out["ledger"]["ordering_ambiguous_days"] = ambiguous
    out["ledger"]["ledger_gap_days"] = gaps
    sdays = [d for d in sorted(series) if ctx.date_from <= d <= ctx.date_to]
    if not sdays:
        out["ledger"]["available"] = False
        return out
    thr = cfg.low_cash_threshold_inr
    cash_vals = [series[d][0] for d in sdays]
    mn = min(cash_vals)
    out["cash"].update({
        "start": _r(cash_vals[0]), "end": _r(cash_vals[-1]), "min": _r(mn),
        "min_date": sdays[cash_vals.index(mn)].isoformat(),
        "days_below_threshold": sum(1 for c in cash_vals if c < thr),
        "days_negative": sum(1 for c in cash_vals if c < 0)})
    # streaks over ledger days
    flow: dict[date, float] = defaultdict(float)
    for r in ledger:
        flow[r.posting_date] += r.credit - r.debit
    streaks: list[dict[str, Any]] = []
    cur: list[date] = []
    for d in sorted(flow) + [None]:  # type: ignore[list-item]
        if d is not None and flow[d] < -EPS:
            cur.append(d)
            continue
        if len(cur) >= cfg.debit_streak_min_days:
            streaks.append({"start": cur[0].isoformat(), "end": cur[-1].isoformat(), "days": len(cur),
                            "net_outflow": _r(-sum(flow[x] for x in cur)),
                            "cash_at_end": _r(series[cur[-1]][0]) if cur[-1] in series else None})
        cur = []
    out["debit_streaks"] = streaks[: cfg.analytics_max_rows]

    snaps = sweep_positions(res, sdays)
    prices = _last_prices(ctx)
    meta = res.meta
    series_out = []
    proxies: list[float] = []
    ratios: list[float] = []
    trap_days: list[dict[str, Any]] = []
    unmarked = 0
    first_trap: Optional[tuple[date, dict[str, float]]] = None
    for d in sdays:
        cash, carried = series[d]
        proxy = 0.0
        premium = 0.0
        losers = 0
        loss_est = 0.0
        loser_syms: dict[str, float] = {}
        for sym, p in snaps[d].items():
            m = meta[sym]
            if p.qty < 0 and m.strike is not None:
                proxy += -p.qty * m.strike
            if p.qty > 0:
                premium += p.qty * p.avg
            mk = _mark(prices, sym, d, cfg.loser_mark_max_stale_days)
            if mk is None:
                unmarked += 1
                continue
            pl = p.qty * (mk - p.avg)
            if pl < -EPS:
                losers += 1
                loss_est += pl
                loser_syms[sym] = pl
        ratio = _r(proxy / cash, 3) if cash > 0 else None
        series_out.append({"date": d.isoformat(), "cash": _r(cash), "carried": carried})
        proxies.append(proxy)
        if ratio is not None:
            ratios.append(ratio)
        if cash < thr and losers >= 1:
            trap_days.append({"date": d.isoformat(), "cash": _r(cash), "open_losers_count": losers,
                              "short_notional_proxy": _r(proxy), "proxy_to_cash_ratio": ratio,
                              "known_loss_est": _r(loss_est),
                              "long_premium_at_risk": _r(premium)})
            if first_trap is None:
                first_trap = (d, loser_syms)
    out["cash_series"] = series_out
    out["exposure"].update({"peak_short_notional_proxy": _r(max(proxies)) if proxies else None,
                            "avg_proxy_to_cash_ratio": _r(sum(ratios) / len(ratios), 3) if ratios else None})
    growth = None
    if first_trap is not None:
        d0, syms = first_trap
        closed_syms = {s: 0.0 for s in syms}
        ended: set[str] = set()
        for e in res.events:
            s = e.fill.symbol
            if s in closed_syms and e.fill.trade_date > d0 and s not in ended:
                closed_syms[s] += e.realised
                if e.pos_after == 0:
                    ended.add(s)
        use = [s for s in syms if s in ended]
        if use:
            at_trap = sum(syms[s] for s in use)
            final = sum(closed_syms[s] for s in use)
            growth = {"symbols_n": len(use), "first_trap_date": d0.isoformat(),
                      "loss_at_first_trap_est": _r(at_trap), "final_closed_pnl": _r(final),
                      "growth": _r(final - at_trap)}
    out["trap"].update({"days": len(trap_days), "days_list": trap_days[: cfg.analytics_max_rows],
                        "loss_growth_est": growth, "lots_unmarked": unmarked})
    return out


def _stops(ctx: Ctx, res: FifoResult) -> dict[str, Any]:
    cfg = ctx.cfg
    shorts = [t for t in ctx.trades if t.side < 0]
    longs = len(ctx.trades) - len(shorts)
    total_loss = sum(-t.pnl for t in ctx.trades if t.pnl < -EPS)
    prices = _last_prices(ctx)
    as_of = min(ctx.date_to, res.as_of)
    open_shorts = [lot for lot in res.open_lots(ctx.include_est) if lot.side < 0]
    rows = []
    for mult in cfg.stop_loss_multiples:
        n_ex = 0
        real = 0.0
        saved = 0.0
        for t in shorts:
            if t.pnl >= -EPS:
                continue
            planned = mult * t.entry_avg * t.qty
            loss = -t.pnl
            if loss > planned + EPS:
                n_ex += 1
                real += loss
                saved += loss - planned
        ob_n = 0
        ob_x = 0.0
        for lot in open_shorts:
            mk = _mark(prices, lot.symbol, as_of, cfg.loser_mark_max_stale_days)
            if mk is None:
                continue
            loss = lot.qty * (mk - lot.avg_entry)
            planned = mult * lot.avg_entry * lot.qty
            if loss > planned + EPS:
                ob_n += 1
                ob_x += loss - planned
        rows.append({"multiple": mult, "n_exceeded": n_ex, "realised_loss_exceeding": _r(real),
                     "saved_if_stopped": _r(saved),
                     "share_of_total_loss_pct": _r(saved / total_loss * 100.0) if total_loss > EPS else None,
                     "open_beyond_n": ob_n, "open_beyond_excess_est": _r(ob_x)})
    return {"long_closed_excluded": longs, "short_closed": len(shorts), "rows": rows,
            **_info("What-if: had every closed SHORT trade been stopped out at a multiple of the premium "
                    "collected, how much of the realised loss would have been avoided.",
                    ["One-sided: only trades that closed at a loss beyond the stop are adjusted. Shorts that "
                     "touched the stop and then recovered (whipsaw) cannot be seen from fills, so savings can "
                     "read as overstated.",
                     "Assumes the stop fills exactly at the planned level (no slippage or gaps).",
                     "Closed long trades are excluded: their loss is bounded by the premium paid.",
                     "Planned loss at multiple L = L x entry average x quantity; trades losing less than the plan "
                     "are unchanged. open_beyond_* uses the last fill price as a mark (ESTIMATE)."])}


# ── reconciliation (foundation) ───────────────────────────────────────────────────


def _open_sign(t: Optional[str]) -> int:
    return -1 if t and t.strip().lower().startswith("s") else 1


def dedupe_pnl_lines(ls: list[PnlLine]) -> list[PnlLine]:
    """One P&L-sheet line per overlapping period for a symbol (the longest period wins).

    Cumulative exports overlap; summing every line would count the overlap's realised P&L (and
    the FIFO closes inside it) twice.  Mirrors the charge-period dedupe in the service."""
    picked: list[PnlLine] = []
    for ln in sorted(ls, key=lambda x: (-(x.period_to - x.period_from).days, x.period_from)):
        if any(ln.period_from <= k.period_to and k.period_from <= ln.period_to for k in picked):
            continue
        picked.append(ln)
    return sorted(picked, key=lambda x: x.period_from)


def reconciliation(ctx: Ctx, lines: list[PnlLine]) -> dict[str, Any]:
    cfg = ctx.cfg
    res = ctx.res
    tol = cfg.analytics_recon_tolerance_inr
    meas = res.segments
    est = res.est_segments
    by_sym: dict[str, list[PnlLine]] = defaultdict(list)
    for ln in lines:
        by_sym[ln.symbol].append(ln)
    dropped = 0
    for sym_, ls_ in list(by_sym.items()):
        kept = dedupe_pnl_lines(ls_)
        dropped += len(ls_) - len(kept)
        by_sym[sym_] = kept
    fill_syms = set(res.meta)
    first_fill = min((f.trade_date for f in res.fills), default=None)
    resid: dict[str, list] = defaultdict(list)
    for lot in res.residual_lots:
        resid[lot.symbol].append(lot)
    rows = []
    for sym in sorted(fill_syms | set(by_sym)):
        ls = by_sym.get(sym, [])
        m = res.meta.get(sym)
        fm = fe = 0.0
        for ln in ls:
            fm += sum(s.pnl for s in meas if s.symbol == sym and ln.period_from <= s.close_date <= ln.period_to)
            fe += sum(s.pnl for s in est if s.symbol == sym and ln.period_from <= s.close_date <= ln.period_to)
        if not ls:
            fm = sum(s.pnl for s in meas if s.symbol == sym)
            fe = sum(s.pnl for s in est if s.symbol == sym)
        sheet = sum(ln.realized_pnl or 0.0 for ln in ls) if ls else None
        sheet_open = sum((ln.open_quantity or 0) * _open_sign(ln.open_quantity_type) for ln in ls) if ls else None
        lots = resid.get(sym, [])
        fifo_open = sum(lot.qty * lot.side for lot in lots)
        gap_m = (sheet - fm) if sheet is not None else None
        gap_e = (sheet - fm - fe) if sheet is not None else None
        within = gap_m is not None and abs(gap_m) <= tol
        within_e = gap_e is not None and abs(gap_e) <= tol
        causes: list[str] = []
        if not ls:
            causes.append("sheet_missing")
        elif sym not in fill_syms:
            causes.append("trades_missing")
        elif not within:
            if fifo_open != 0 and (sheet_open or 0) == 0:
                causes.append("expiry_unclosed")
            fills_sym = [f for f in res.fills if f.symbol == sym]
            if first_fill and any(ln.period_from < first_fill for ln in ls) and not within_e:
                causes.append("pre_history_open")
            if any(not any(ln.period_from <= f.trade_date <= ln.period_to for ln in ls) for f in fills_sym):
                causes.append("period_mismatch")
            if not within_e and not causes:
                causes.append("unexplained")
        elif gap_m is not None and abs(gap_m) > EPS:
            causes.append("rounding")
        intr = None
        implied = None
        if m is not None and lots and all(lot.side == lots[0].side for lot in lots):
            exp = m.expiry_eff
            ss = ctx.spot.get(m.underlying)
            close = ss.exact(exp) if (ss and exp) else None
            if close is not None:
                intr = intrinsic(m.itype, m.strike, close)
            if sheet is not None and (sheet_open or 0) == 0 and fifo_open != 0:
                avg = sum(lot.qty * lot.avg_entry for lot in lots) / sum(lot.qty for lot in lots)
                implied = avg + (sheet - fm) / fifo_open
        rows.append({
            "symbol": sym, "underlying": m.underlying if m else (ls[0].underlying if ls else None),
            "expiry_ym": m.expiry_ym if m else (ls[0].expiry_ym if ls else None),
            "fifo_measured": _r(fm), "fifo_expiry_estimate": _r(fe), "sheet_realised": _r(sheet),
            "gap_measured": _r(gap_m), "gap_with_estimate": _r(gap_e),
            "within_tolerance": bool(within) if ls else False,
            "within_tolerance_with_estimate": bool(within_e) if ls else False,
            "fifo_open_qty": fifo_open, "sheet_open_qty": sheet_open,
            "intrinsic_px": _r(intr), "sheet_implied_px": _r(implied), "causes": causes})
    ok = sum(1 for r in rows if r["within_tolerance"])
    with_sheet = [r for r in rows if r["sheet_realised"] is not None]
    tot_gap = sum(r["gap_measured"] for r in with_sheet)
    tot_gap_e = sum(r["gap_with_estimate"] for r in with_sheet)
    totals = {"symbols": len(rows), "n_symbols_ok": ok, "n_symbols_gap": len(rows) - ok,
              "fifo_measured": _r(sum(r["fifo_measured"] for r in rows)),
              "fifo_expiry_estimate": _r(sum(r["fifo_expiry_estimate"] for r in rows)),
              "sheet_realised": _r(sum(r["sheet_realised"] for r in with_sheet)),
              "gap_measured": _r(tot_gap), "gap_with_estimate": _r(tot_gap_e),
              "expiry_estimate_explains": _r(tot_gap - tot_gap_e),
              "sheet_lines_overlap_dropped": dropped,
              "pre_history_symbols": sum(1 for r in rows if "pre_history_open" in r["causes"])}
    return {"tolerance_inr": tol, "rows": rows[: cfg.analytics_max_rows], "rows_total": len(rows),
            "totals": totals,
            **_info("Per-symbol comparison of FIFO-matched realised P&L with the realised P&L in your P&L "
                    "sheet. Gaps are shown, never hidden.",
                    ["FIFO realised covers closes dated inside each sheet period; expiry-held lots are shown "
                     "separately as an ESTIMATE (spot-intrinsic) and also cross-checked against the price the "
                     "sheet implies.",
                     "Where P&L-sheet periods overlap for a symbol, only the longest period is used (overlap "
                     "lines are dropped and counted) so sheet and FIFO totals are not double-counted.",
                     "Causes: expiry_unclosed, pre_history_open, period_mismatch, sheet_missing, "
                     "trades_missing, rounding, unexplained."])}


def open_lots_out(ctx: Ctx, lots: LotInfo) -> list[dict[str, Any]]:
    out = []
    for lot in ctx.res.residual_lots:
        ls, basis = lots.lot_size(lot.symbol, lot.underlying)
        out.append({
            "symbol": lot.symbol, "side": "long" if lot.side > 0 else "short", "qty": lot.qty,
            "avg_entry": _r(lot.avg_entry), "open_date": lot.open_date.isoformat(),
            "expiry": _iso(lot.expiry_eff), "expired": lot.expired, "expiry_unknown": lot.expiry_unknown,
            "settlement_unpriced": lot.settlement_unpriced, "est_settled": lot.est_settled,
            "lots": _r(lot.qty / ls) if ls else None, "lots_basis": basis})
    return out[: ctx.cfg.analytics_max_rows]
