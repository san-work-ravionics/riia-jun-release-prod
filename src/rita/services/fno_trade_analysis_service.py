"""F42 Trade Analysis — pure aggregation of today's Kite orders/trades/positions.

No I/O: the route fetches via `kite_middleware_client` and hands the results here.
Lot size comes ONLY from the Kite NFO instrument master (joined on tradingsymbol); this
deliberately supersedes the static NIFTY 75 / BANKNIFTY 30 values in project.md §2 for
this feature. Nothing is guessed: rows missing from the master are counted as unresolved.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from rita.schemas.fno_trade_analysis import (
    ExcludedCounts,
    ExpirySummary,
    OrderRow,
    PositionRow,
    SnapshotInfo,
    TradeAnalysisLiveResponse,
    TradeFilter,
    TradeKpis,
    TradeRow,
)
from rita.services.kite_middleware_client import ClientResult

HISTORY_NOTE = (
    "Kite exposes only the current trading day. History accrues from the first daily "
    "snapshot taken by the middleware; Console imports (Phase 2) will backfill earlier days."
)
_TERMINAL_STATUSES = {"COMPLETE", "REJECTED", "CANCELLED"}
_FAIL_PRIORITY = ["token_expired", "middleware_unreachable", "bad_response", "upstream_error"]


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> Optional[int]:
    n = _num(v)
    return None if n is None else int(n)


def _str(v: Any) -> Optional[str]:
    return None if v is None else str(v)


def _lots(qty: Optional[int], lot_size: Optional[int]) -> Optional[float]:
    if qty is None or not lot_size:
        return None
    return round(abs(qty) / lot_size, 2)


def _worst_reason(reasons: list[Optional[str]]) -> Optional[str]:
    present = [r for r in reasons if r]
    for r in _FAIL_PRIORITY:
        if r in present:
            return r
    return present[0] if present else None


class _Scope:
    """Classifies a tradingsymbol against the master / window / selected underlying."""

    def __init__(self, master: dict[str, dict[str, Any]], months: list[int],
                 underlying: str, expiry_month: Optional[int]) -> None:
        self.master, self.months = master, months
        self.underlying, self.expiry_month = underlying, expiry_month
        self.excluded: dict[str, set[str]] = {
            "non_option": set(), "other_underlying": set(), "out_of_window": set(), "unresolved": set(),
        }

    def resolve(self, row: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Master entry when the row is in scope; None (and counted) otherwise."""
        sym = str(row.get("tradingsymbol") or "")
        meta = self.master.get(sym)
        if meta is None:
            exch = row.get("exchange")
            if (exch and exch != "NFO") or sym.endswith("FUT"):
                self.excluded["non_option"].add(sym)
            else:
                self.excluded["unresolved"].add(sym)
            return None
        if self.underlying != "ALL" and meta["name"] != self.underlying:
            self.excluded["other_underlying"].add(sym)
            return None
        if meta["expiry"].month not in self.months:
            self.excluded["out_of_window"].add(sym)
            return None
        if self.expiry_month is not None and meta["expiry"].month != self.expiry_month:
            return None  # user narrowing inside the window: not an exclusion
        return meta

    def counts(self) -> ExcludedCounts:
        return ExcludedCounts(**{k: len(v) for k, v in self.excluded.items()})


def _ident(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "underlying": meta["name"], "expiry": meta["expiry"].isoformat(),
        "strike": meta["strike"], "option_type": meta["instrument_type"],
        "lot_size": meta["lot_size"],
    }


def build_live_payload(
    *,
    orders: ClientResult,
    trades: ClientResult,
    positions: ClientResult,
    master: ClientResult,
    snapshot: ClientResult,
    underlyings: list[str],
    expiry_months: list[int],
    underlying: str = "ALL",
    expiry_month: Optional[int] = None,
    include_closed: bool = True,
    now: Optional[datetime] = None,
) -> TradeAnalysisLiveResponse:
    now = now or datetime.now()
    flt = TradeFilter(underlyings=list(underlyings), expiry_months=list(expiry_months), underlying=underlying)
    base = {"filter": flt, "history_note": HISTORY_NOTE, "as_of_date": now.date().isoformat()}

    if master.body is None:
        return TradeAnalysisLiveResponse(
            available=False, source="fallback", reason=master.reason or "upstream_error",
            message="Instrument master unavailable; cannot resolve lot sizes or expiries.", **base)

    legs = {"orders": orders, "trades": trades, "positions": positions}
    failed = [k for k, r in legs.items() if r.body is None]
    if len(failed) == len(legs):
        return TradeAnalysisLiveResponse(
            available=False, source="fallback",
            reason=_worst_reason([r.reason for r in legs.values()]),
            message="No live Kite data available.", **base)

    scope = _Scope(master.body, expiry_months, underlying, expiry_month)

    order_rows: list[OrderRow] = []
    for o in (orders.body or {}).get("data") or []:
        meta = scope.resolve(o)
        if meta is None:
            continue
        qty = _int(o.get("quantity"))
        order_rows.append(OrderRow(
            order_id=_str(o.get("order_id")), tradingsymbol=o["tradingsymbol"],
            transaction_type=_str(o.get("transaction_type")), status=_str(o.get("status")),
            product=_str(o.get("product")), order_type=_str(o.get("order_type")),
            quantity=qty, filled_quantity=_int(o.get("filled_quantity")),
            pending_quantity=_int(o.get("pending_quantity")),
            average_price=_num(o.get("average_price")),
            lots=_lots(qty, meta["lot_size"]), order_timestamp=_str(o.get("order_timestamp")),
            **_ident(meta)))

    trade_rows: list[TradeRow] = []
    for t in (trades.body or {}).get("data") or []:
        meta = scope.resolve(t)
        if meta is None:
            continue
        qty = _int(t.get("quantity"))
        trade_rows.append(TradeRow(
            trade_id=_str(t.get("trade_id")), order_id=_str(t.get("order_id")),
            tradingsymbol=t["tradingsymbol"], transaction_type=_str(t.get("transaction_type")),
            quantity=qty, average_price=_num(t.get("average_price")),
            lots=_lots(qty, meta["lot_size"]), fill_timestamp=_str(t.get("fill_timestamp")),
            **_ident(meta)))

    all_positions: list[PositionRow] = []
    for p in ((positions.body or {}).get("data") or {}).get("net") or []:
        meta = scope.resolve(p)
        if meta is None:
            continue
        net = _int(p.get("quantity")) or 0
        all_positions.append(PositionRow(
            tradingsymbol=p["tradingsymbol"], product=_str(p.get("product")),
            net_quantity=net, lots=_lots(net, meta["lot_size"]),
            side="LONG" if net > 0 else "SHORT" if net < 0 else "FLAT",
            average_price=_num(p.get("average_price")), last_price=_num(p.get("last_price")),
            pnl=_num(p.get("pnl")), m2m=_num(p.get("m2m")),
            realised=_num(p.get("realised")), unrealised=_num(p.get("unrealised")),
            **_ident(meta)))

    # ── KPIs ──
    def _sum(rows: list[PositionRow], attr: str) -> float:
        return round(sum(getattr(r, attr) or 0.0 for r in rows), 2)

    buy = sum(r.quantity or 0 for r in trade_rows if r.transaction_type == "BUY")
    sell = sum(r.quantity or 0 for r in trade_rows if r.transaction_type == "SELL")
    lot_rows = [r for r in trade_rows if r.lot_size and r.quantity is not None]
    lots_traded = round(sum(r.quantity / r.lot_size for r in lot_rows), 2) if lot_rows else None

    per_sym: dict[str, dict[str, Any]] = {}
    for r in trade_rows:
        e = per_sym.setdefault(r.tradingsymbol, {"BUY": 0, "SELL": 0, "lot": r.lot_size})
        if r.transaction_type in ("BUY", "SELL"):
            e[r.transaction_type] += r.quantity or 0
    round_trips = sum(min(e["BUY"], e["SELL"]) // e["lot"] for e in per_sym.values() if e["lot"])

    statuses = [(o.status or "").upper() for o in order_rows]
    fo, ft, fp = "orders" in failed, "trades" in failed, "positions" in failed
    n = lambda bad, v: None if bad else v  # noqa: E731
    kpis = TradeKpis(
        orders_total=n(fo, len(order_rows)),
        orders_complete=n(fo, statuses.count("COMPLETE")),
        orders_rejected=n(fo, statuses.count("REJECTED")),
        orders_cancelled=n(fo, statuses.count("CANCELLED")),
        orders_open=n(fo, sum(1 for s_ in statuses if s_ not in _TERMINAL_STATUSES)),
        trades_count=n(ft, len(trade_rows)), buy_qty=n(ft, buy), sell_qty=n(ft, sell),
        lots_traded=n(ft, lots_traded),
        open_positions=n(fp, sum(1 for p in all_positions if p.side != "FLAT")),
        net_pnl=n(fp, _sum(all_positions, "pnl")), realised_pnl=n(fp, _sum(all_positions, "realised")),
        unrealised_pnl=n(fp, _sum(all_positions, "unrealised")), round_trips_today=n(ft, int(round_trips)),
    )

    # ── by expiry ──
    groups: dict[tuple[str, str], dict[str, Any]] = {}

    def _g(und: Optional[str], exp: Optional[str]) -> dict[str, Any]:
        return groups.setdefault((und or "", exp or ""), {
            "trades": 0, "orders": 0, "net_quantity": 0, "open_legs": 0, "pnl": 0.0})

    for r in trade_rows:
        _g(r.underlying, r.expiry)["trades"] += 1
    for o in order_rows:
        _g(o.underlying, o.expiry)["orders"] += 1
    for p in all_positions:
        g = _g(p.underlying, p.expiry)
        g["net_quantity"] += p.net_quantity
        g["open_legs"] += 1 if p.side != "FLAT" else 0
        g["pnl"] += p.pnl or 0.0
    by_expiry = [
        ExpirySummary(
            underlying=und, expiry=exp,
            label=f"{und} {datetime.fromisoformat(exp).strftime('%d %b %Y')}",
            trades=g["trades"], orders=g["orders"], net_quantity=g["net_quantity"],
            open_legs=g["open_legs"], pnl=round(g["pnl"], 2))
        for (und, exp), g in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0]))
    ]

    # ── snapshot info ──
    snap = SnapshotInfo()
    if snapshot.body is not None:
        snap = SnapshotInfo(
            available=True, days_captured=len(snapshot.body.get("days") or []),
            first_date=snapshot.body.get("first_date"), last_date=snapshot.body.get("last_date"),
            total_trades=int(snapshot.body.get("total_trades") or 0))

    labels = {"orders": "orders", "trades": "trades", "positions": "positions"}
    message = (f"Partial data: {', '.join(labels[k] for k in failed)} unavailable." if failed else None)

    return TradeAnalysisLiveResponse(
        available=True, source="kite", reason=None, message=message,
        fetched_at=now.isoformat(), kpis=kpis, orders=order_rows, trades=trade_rows,
        positions=[p for p in all_positions if include_closed or p.side != "FLAT"],
        by_expiry=by_expiry, snapshot=snap, excluded=scope.counts(), **base)
