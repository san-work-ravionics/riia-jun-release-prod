"""F42 Phase 3 — read-only Trade Analysis analytics service (Experience tier).

Pattern of FnoImportReadService: constructor takes a Session, builds repositories, never
commits and never writes.  ORM rows are mapped into the frozen dataclasses of the pure FIFO /
analytics modules; the Kite NFO master (lot sizes) is passed in by the router as a plain
parameter (``master``: any object with ``.body`` -> {symbol: {name, expiry, lot_size, ...}}),
so this module never imports the middleware client.

PERSONAL DATA: logs carry counts only, never symbols, amounts or dates of fills.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.repositories.fno_import import FnoLedgerRepo, FnoPnlRepo, FnoTradeRepo
from rita.repositories.market_data import MarketDataCacheRepository
from rita.schemas.fno_trade_analytics import (
    AnalyticsFilter, BuildupResponse, FoundationResponse, MarginTrapResponse, MarketTurnResponse,
    OvertradingResponse, Quality, SpotVsPnlResponse, SuggestionsResponse, Tags,
)
from rita.services import fno_trade_analytics as an
from rita.services.fno_trade_fifo import Fill, SpotSeries, run_fifo
from rita.services import fno_trade_spot_pnl as spot_pnl
from rita.services.fno_trade_suggestions import (
    DISCLAIMER, SPOT_RULE_IDS, spot_rules,
    suggestions as build_suggestions,
)

log = structlog.get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_REASON_TEXT = {
    "no_data": ("No imported Console data yet. Import your Console files on the Import tab, "
                "or load sample data there."),
    "no_trades_in_scope": "No option fills match the selected underlying, expiry and date filters.",
    "spot_unavailable": "No spot price history for the selected underlying; the spot-vs-P&L view is omitted.",
    "insufficient_sample": "Too few days in this sample for the statistic.",
    "no_open_positions": "No open positions to mark.",
    "sheet_stale": "The P&L sheet snapshot is older than the latest spot day.",
    "no_pnl_sheet": "No P&L sheet line covers the open positions in this scope.",
}

_DEFS = {
    "foundation": "FIFO lot matching of your imported option fills, reconciled with the P&L sheet.",
    "overtrading": "How often and how quickly you traded, what it cost, and how closed trades turned out.",
    "buildup": "How positions were built, added to and reduced over time.",
    "market-turn": "Positioning and realised P&L around days the underlying moved sharply.",
    "margin-trap": "Ledger cash, debit streaks, low-cash days with open losers (proxy) and planned-vs-actual stops.",
    "suggestions": "Rule-based what-ifs derived from your own history.",
    "spot-vs-pnl": "How the underlying moved against your realised P&L and whether your book was with or against it.",
}
_TAGS = {
    "foundation": (["fifo_realised", "sheet_realised", "gap"], ["fifo_expiry_estimate", "intrinsic_px"]),
    "overtrading": (["fills", "orders", "holding", "churn", "winloss", "bursts"], ["charges"]),
    "buildup": (["events", "averaging", "chains", "timeline"], ["short_notional_proxy", "lots_basis"]),
    "market-turn": (["spot_returns", "realised_pnl_day"], ["delta1_bound_pnl", "bias_units"]),
    "margin-trap": (["cash", "debit_streaks"], ["short_notional_proxy", "trap_days", "stops"]),
    "suggestions": ([], ["what_if"]),
    "spot-vs-pnl": (["spot_close", "spot_returns", "realised_pnl_day", "unrealised_snapshot"],
                    ["expiry_estimate", "bias_units", "delta1_bound_pnl", "what_if"]),
}

_RELATED = {"book_against_market": ("bias_limit",), "loses_on_down_days": ("bias_limit",),
            "negative_beta": ("bias_limit",), "big_move_concentration": ("counter_move_entries", "bias_limit"),
            "expiry_day_loss": ("expiry_proximity_entries",)}


@dataclass(frozen=True)
class AnalyticsParams:
    underlying: str = "ALL"
    expiry_month: Optional[int] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    include_expiry_estimate: Optional[bool] = None
    include_lots: bool = True


def lot_info_from_master(master: Any) -> an.LotInfo:
    """Map a Kite NFO master result (``.body``) to LotInfo; any failure -> unavailable."""
    body = getattr(master, "body", None)
    if not isinstance(body, dict) or not body:
        return an.LotInfo(False)
    by_sym: dict[str, int] = {}
    by_und: dict[str, tuple[Any, int]] = {}
    for sym, inst in body.items():
        ls = inst.get("lot_size") if isinstance(inst, dict) else None
        if not ls:
            continue
        by_sym[str(sym)] = int(ls)
        name = str(inst.get("name") or "")
        exp = inst.get("expiry")
        key = (str(exp) if exp else "9999", int(ls))
        if name and (name not in by_und or key < by_und[name]):
            by_und[name] = key  # type: ignore[assignment]
    return an.LotInfo(True, by_sym, {k: v[1] for k, v in by_und.items()})


class FnoTradeAnalyticsService:
    def __init__(self, db: Session, today: Optional[date] = None) -> None:
        self._trades = FnoTradeRepo(db)
        self._pnl = FnoPnlRepo(db)
        self._ledger = FnoLedgerRepo(db)
        self._market = MarketDataCacheRepository(db)
        self._cfg = get_settings().trade_analysis
        self._today = today

    # ── public panels ──────────────────────────────────────────────────────────

    def foundation(self, user_id: str, p: AnalyticsParams) -> FoundationResponse:
        ctx = self._prepare(user_id, p, "foundation")
        if isinstance(ctx, dict):
            return FoundationResponse(**ctx)
        lines = [an.PnlLine(
            symbol=r.symbol, underlying=r.underlying, expiry_ym=r.expiry_ym, period_from=r.period_from,
            period_to=r.period_to, realized_pnl=r.realized_pnl, open_quantity=r.open_quantity,
            open_quantity_type=r.open_quantity_type)
            for r in self._pnl.lines_for_scope(user_id, self._unds(p), self._months(p))]
        lots = an.LotInfo(False)
        pnl_cov = self._pnl.coverage(user_id)
        led_cov = self._ledger.coverage(user_id)
        res = ctx.res
        est_in_window = [s for s in res.est_segments if s.close_date >= ctx.date_from]
        meas = [s for s in res.segments if s.close_date >= ctx.date_from]
        env = self._env(user_id, p, ctx, "foundation")
        return FoundationResponse(
            **env,
            reconciliation=an.reconciliation(ctx, lines),
            coverage={
                "first_fill_date": res.fills[0].trade_date.isoformat() if res.fills else None,
                "last_fill_date": res.fills[-1].trade_date.isoformat() if res.fills else None,
                "ledger_first": led_cov["first_date"].isoformat() if led_cov["first_date"] else None,
                "ledger_last": led_cov["last_date"].isoformat() if led_cov["last_date"] else None,
                "pnl_periods": [{"from_date": a.isoformat(), "to_date": b.isoformat()}
                                for a, b in pnl_cov["periods"]]},
            open_lots=an.open_lots_out(ctx, lots),
            fifo_totals={"closed_trades": len(ctx.trades),
                         "measured_pnl": an._r(sum(s.pnl for s in meas)),
                         "estimated_pnl": an._r(sum(s.pnl for s in est_in_window))})

    def overtrading(self, user_id: str, p: AnalyticsParams) -> OvertradingResponse:
        ctx = self._prepare(user_id, p, "overtrading")
        if isinstance(ctx, dict):
            return OvertradingResponse(**ctx)
        out = an.overtrading(ctx, self._charge_periods(user_id))
        return OvertradingResponse(**self._env(user_id, p, ctx, "overtrading"), **out)

    def buildup(self, user_id: str, p: AnalyticsParams, master: Any = None) -> BuildupResponse:
        ctx = self._prepare(user_id, p, "buildup")
        if isinstance(ctx, dict):
            return BuildupResponse(**ctx)
        lots = lot_info_from_master(master) if p.include_lots else an.LotInfo(False)
        out = an.buildup(ctx, lots)
        env = self._env(user_id, p, ctx, "buildup", lots_cov=out["lots"]["coverage_pct"])
        return BuildupResponse(**env, **out)

    def market_turn(self, user_id: str, p: AnalyticsParams) -> MarketTurnResponse:
        ctx = self._prepare(user_id, p, "market-turn")
        if isinstance(ctx, dict):
            return MarketTurnResponse(**ctx)
        out = an.market_turn(ctx)
        env = self._env(user_id, p, ctx, "market-turn")
        if not out["spot"]["available"]:
            env["reason"] = "spot_unavailable"
            env["message"] = "No spot price history for the selected underlying; the turn analysis is omitted."
        return MarketTurnResponse(**env, **out)

    def margin_trap(self, user_id: str, p: AnalyticsParams) -> MarginTrapResponse:
        ctx = self._prepare(user_id, p, "margin-trap")
        if isinstance(ctx, dict):
            return MarginTrapResponse(**ctx)
        out = self._margin(user_id, ctx)
        env = self._env(user_id, p, ctx, "margin-trap", ledger_gap=out["ledger"]["ledger_gap_days"])
        if not out["ledger"]["available"]:
            env["reason"] = "no_ledger"
            env["message"] = ("No usable ledger cash history (missing or balance sign undetectable); "
                              "cash metrics are omitted, stop what-ifs are still shown.")
        return MarginTrapResponse(**env, **out)

    def suggestions(self, user_id: str, p: AnalyticsParams, master: Any = None) -> SuggestionsResponse:
        ctx = self._prepare(user_id, p, "suggestions")
        if isinstance(ctx, dict):
            return SuggestionsResponse(**ctx)
        lots = lot_info_from_master(master) if p.include_lots else an.LotInfo(False)
        ot = an.overtrading(ctx, self._charge_periods(user_id))
        bu = an.buildup(ctx, lots)
        mt = self._margin(user_id, ctx)
        out = build_suggestions(ctx, ot, bu, mt, lots)
        env = self._env(user_id, p, ctx, "suggestions", lots_cov=bu["lots"]["coverage_pct"])
        env["definition"] = out.pop("definition")
        env["assumptions"] = out.pop("assumptions")
        return SuggestionsResponse(**env, **out)

    def spot_vs_pnl(self, user_id: str, p: AnalyticsParams) -> SpotVsPnlResponse:
        ctx = self._prepare(user_id, p, "spot-vs-pnl")
        if isinstance(ctx, dict):
            return SpotVsPnlResponse(**ctx)
        lines = [an.PnlLine(
            symbol=r.symbol, underlying=r.underlying, expiry_ym=r.expiry_ym, period_from=r.period_from,
            period_to=r.period_to, realized_pnl=r.realized_pnl, open_quantity=r.open_quantity,
            open_quantity_type=r.open_quantity_type,
            unrealized_pnl=float(r.unrealized_pnl) if r.unrealized_pnl is not None else None,
            prev_close_price=float(r.prev_close_price) if r.prev_close_price is not None else None)
            for r in self._pnl.lines_for_scope(user_id, self._unds(p), self._months(p))]
        view = spot_pnl.spot_vs_pnl(ctx, lines, self._unds(p))
        rules, _vetoes = spot_rules(ctx, view)
        obs_ids = {o["id"] for b in view["underlyings"] for o in b["observations"]}
        rule_ids = {r["id"] for r in rules}
        related = [{"observation_id": o, "rule_id": r} for o, rs in _RELATED.items() if o in obs_ids
                   for r in rs if r in rule_ids]
        env = self._env(user_id, p, ctx, "spot-vs-pnl")
        if not ctx.spot:
            env["reason"] = "spot_unavailable"
            env["message"] = _REASON_TEXT["spot_unavailable"]
        improvement = {"disclaimer": DISCLAIMER, "baseline_pnl": an._r(sum(t.pnl for t in ctx.trades)),
                       "rules": [r for r in rules if r["id"] in SPOT_RULE_IDS], "related": related}
        return SpotVsPnlResponse(**env, **view, improvement=improvement)

    def run_all(self, user_id: str, p: AnalyticsParams, master: Any = None) -> dict[str, Any]:
        """All six panels as plain dicts (for scripted end-to-end runs)."""
        return {
            "foundation": self.foundation(user_id, p).model_dump(),
            "overtrading": self.overtrading(user_id, p).model_dump(),
            "buildup": self.buildup(user_id, p, master).model_dump(),
            "market-turn": self.market_turn(user_id, p).model_dump(),
            "margin-trap": self.margin_trap(user_id, p).model_dump(),
            "suggestions": self.suggestions(user_id, p, master).model_dump(),
        }

    # ── internals ──────────────────────────────────────────────────────────────

    def _as_of(self) -> date:
        return self._today or datetime.now(IST).date()

    def _unds(self, p: AnalyticsParams) -> list[str]:
        return list(self._cfg.underlyings) if p.underlying == "ALL" else [p.underlying]

    def _months(self, p: AnalyticsParams) -> list[str]:
        ms = [p.expiry_month] if p.expiry_month else self._cfg.expiry_months
        return [f"{self._cfg.expiry_year:04d}-{m:02d}" for m in ms]

    def _include_est(self, p: AnalyticsParams) -> bool:
        if p.include_expiry_estimate is not None:
            return bool(p.include_expiry_estimate)
        return self._cfg.expiry_settlement == "spot_intrinsic"

    def _filter(self, p: AnalyticsParams, d_from: date, d_to: date) -> AnalyticsFilter:
        cfg = self._cfg
        return AnalyticsFilter(
            underlying=p.underlying,
            expiry_months=[p.expiry_month] if p.expiry_month else list(cfg.expiry_months),
            expiry_year=cfg.expiry_year, date_from=d_from.isoformat(), date_to=d_to.isoformat(),
            include_expiry_estimate=self._include_est(p))

    def _empty(self, p: AnalyticsParams, panel: str, reason: str, d_from: date, d_to: date) -> dict[str, Any]:
        return {"available": False, "reason": reason, "message": _REASON_TEXT.get(reason),
                "as_of": self._as_of().isoformat(), "filter": self._filter(p, d_from, d_to),
                "definition": _DEFS[panel], "assumptions": [], "quality": Quality(),
                "tags": Tags(measured=_TAGS[panel][0], estimated=_TAGS[panel][1])}

    def _prepare(self, user_id: str, p: AnalyticsParams, panel: str) -> Any:
        cfg = self._cfg
        as_of = self._as_of()
        d_from = p.date_from or cfg.date_from
        d_to = p.date_to or as_of
        cov = self._trades.coverage(user_id)
        if not (cov["count"] or self._pnl.coverage(user_id)["line_count"]
                or self._ledger.coverage(user_id)["count"]):
            return self._empty(p, panel, "no_data", d_from, d_to)
        if (p.expiry_month is not None and p.expiry_month not in cfg.expiry_months) or d_from > d_to:
            return self._empty(p, panel, "no_trades_in_scope", d_from, d_to)
        rows = self._trades.fills_for_analysis(user_id, self._unds(p), self._months(p), d_to)
        fills = [self._fill(r) for r in rows]
        if not any(f.trade_date >= d_from for f in fills):
            return self._empty(p, panel, "no_trades_in_scope", d_from, d_to)
        first = min(f.trade_date for f in fills)
        start = min(first, d_from) - timedelta(days=cfg.spot_pad_days)
        spot: dict[str, SpotSeries] = {}
        for u in sorted({f.underlying for f in fills}):
            ss = SpotSeries(self._market.find_closes(u, start, d_to))
            if ss:
                spot[u] = ss
        res = run_fifo(fills, window_start=d_from, as_of=min(d_to, as_of), spot=spot)
        ctx = an.make_ctx(res, cfg, d_from, d_to, self._include_est(p), spot)
        log.info("fno_trade_analytics.prepared", panel=panel, fills=len(fills),
                 segments=len(res.segments), est_segments=len(res.est_segments))
        return ctx

    @staticmethod
    def _fill(r: Any) -> Fill:
        return Fill(
            symbol=r.symbol, underlying=r.underlying, itype=r.instrument_type,
            strike=float(r.strike) if r.strike is not None else None,
            expiry_eff=r.expiry_date or r.opt_expiry, expiry_ym=r.expiry_ym,
            trade_date=r.trade_date, exec_dt=r.order_execution_time,
            sign=1 if str(r.trade_type).lower() == "buy" else -1, qty=int(r.quantity),
            price=float(r.price), trade_id=r.trade_id, order_id=r.order_id)

    def _env(self, user_id: str, p: AnalyticsParams, ctx: an.Ctx, panel: str, lots_cov: Optional[float] = None,
             ledger_gap: Optional[int] = None) -> dict[str, Any]:
        res = ctx.res
        window_days = {e.fill.trade_date for e in ctx.events}
        missing = 0
        for d in window_days:
            und = {e.fill.underlying for e in ctx.events if e.fill.trade_date == d}
            if any(not (ctx.spot.get(u) and ctx.spot[u].exact(d) is not None) for u in und):
                missing += 1
        last = max((s.dates[-1] for s in ctx.spot.values()), default=None)
        q = Quality(
            fills_in_scope=len(ctx.events), unparsed_excluded=self._trades.unparsed_count(user_id, ctx.date_from),
            timestamp_coverage_pct=an._r(ctx.ts_coverage * 100.0), spot_days_missing=missing,
            spot_last_date=last.isoformat() if last else None, ledger_gap_days=ledger_gap,
            lots_coverage_pct=lots_cov,
            expiry_estimated_lots=sum(1 for lot in res.residual_lots if lot.est_settled),
            expiry_unknown_lots=sum(1 for lot in res.residual_lots if lot.expiry_unknown))
        return {"available": True, "reason": None, "message": None, "as_of": self._as_of().isoformat(),
                "filter": self._filter(p, ctx.date_from, ctx.date_to), "definition": _DEFS[panel],
                "assumptions": [
                    "Quantities are contract units; lots appear only where the Kite master knows the symbol.",
                    "Expiry-held lots are closed at spot-intrinsic as a flagged ESTIMATE, separate from measured "
                    "P&L, and can be switched off with the estimate toggle.",
                    "FIFO only sees imported history: a fill with no earlier imported opening (for example a "
                    "buy that covers a short opened before the first import) is treated as a new open of its "
                    "own side, so such pre-history closes show as a lot of the opposite side. The count of "
                    "symbols where the P&L sheet points to this is in the reconciliation totals "
                    "(pre_history_symbols)."],
                "quality": q, "tags": Tags(measured=_TAGS[panel][0], estimated=_TAGS[panel][1])}

    def _charge_periods(self, user_id: str) -> list[an.ChargePeriod]:
        by: dict[tuple[date, date], dict[str, float]] = {}
        for c in self._pnl.charge_summary(user_id):
            slot = by.setdefault((c.period_from, c.period_to), {})
            key = "summary" if (c.section == "summary" and c.item.strip().lower() == "charges") else (
                "items" if c.section == "charges" else "")
            if key:
                slot[key] = slot.get(key, 0.0) + abs(float(c.amount))
        picked: list[tuple[date, date, float]] = []
        for (pf, pt), v in sorted(by.items(), key=lambda kv: (-(kv[0][1] - kv[0][0]).days, kv[0][0])):
            total = v.get("summary", v.get("items"))
            if total is None:
                continue
            if any(pf <= b and a <= pt for a, b, _ in picked):
                continue  # overlapping sheet: keep one total per period (the longest wins)
            picked.append((pf, pt, total))
        return [an.ChargePeriod(pf, pt, tot, self._trades.turnover(user_id, pf, pt))
                for pf, pt, tot in sorted(picked)]

    def _margin(self, user_id: str, ctx: an.Ctx) -> dict[str, Any]:
        rows = self._ledger.series(user_id, ctx.date_from, ctx.date_to)
        led = [an.LedgerRow(r.posting_date, float(r.debit or 0), float(r.credit or 0),
                            float(r.net_balance) if r.net_balance is not None else None, i)
               for i, r in enumerate(rows)]
        b = self._ledger.last_before(user_id, ctx.date_from)
        before = an.LedgerRow(b.posting_date, float(b.debit or 0), float(b.credit or 0),
                              float(b.net_balance) if b.net_balance is not None else None, -1) if b else None
        return an.margin_trap(ctx, led, before)
