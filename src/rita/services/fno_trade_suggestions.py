"""F42 Phase 3 — rule-based, deterministic what-if observations (analysis 7).

Descriptive only: every rule restates the user's own history and recomputes P&L as if an
opening-fill veto (or an exit adjustment) had applied.  No LLM, no external call, no forecast.

What-if model: a rule assigns a veto fraction f in [0, 1] to each opening fill in the window;
``whatif_pnl = baseline_pnl - sum(f x pnl of the FIFO slices opened by that fill)``.  The FIFO is
NOT re-run (in-sample, no second-order effects).
"""
from __future__ import annotations

import bisect
import statistics
from collections import defaultdict
from datetime import date
from typing import Any, Optional

from rita.services.fno_trade_analytics import (
    EPS, Ctx, LotInfo, SpotDay, _info, _r, _ret_pct, _sgn, delta_sign, pct_nearest, spot_days,
)
from rita.services.fno_trade_fifo import ClosedTrade, FillEvent, sweep_positions
from rita.services.fno_trade_spot_pnl import spot_vs_pnl

DISCLAIMER = "Observations from your own imported history, not investment advice or a forecast."
_VETO_RULES = ("max_trades_per_day", "qty_cap_per_expiry", "margin_headroom_floor",
               "no_averaging_down", "cooling_off_after_loss", "bias_limit",
               "expiry_proximity_entries", "counter_move_entries")
SPOT_RULE_IDS = ("bias_limit", "expiry_proximity_entries", "counter_move_entries",
                 "bias_hedge_illustrative")
# Every rule id the Suggestions payload can carry (entry-rule modules above + spot-linked rules + stop discipline).
# The dashboard's _RULE_COPY map must have exactly these keys (checked by test_f42_p6_backend).
RULE_IDS = ("max_trades_per_day", "qty_cap_per_expiry", "margin_headroom_floor", "stop_discipline",
            "no_averaging_down", "cooling_off_after_loss", *SPOT_RULE_IDS)
_CAVEATS = ["In-sample what-if on your own history; no second-order effects (the book is not re-simulated).",
            "Gross of charges; open slices of vetoed fills are reported as units, not priced."]


def _release_expired(book: dict[tuple, dict[str, Any]], res: Any, d: date) -> None:
    """Drop symbols whose expiry is before ``d`` from a per-group open-units book.

    Same rule as ``sweep_positions`` (an expired symbol carries no exposure into a later day);
    a symbol with unknown expiry is never released."""
    for syms in book.values():
        for sym in [s for s in syms if (x := res.meta[s].expiry_eff) is not None and x < d]:
            del syms[sym]


def _what_if(ctx: Ctx, f: dict[int, float], baseline: float, open_units: dict[int, int],
             method: str) -> dict[str, Any]:
    f = {k: v for k, v in f.items() if v > EPS}
    delta = -sum(v * ctx.opened_pnl.get(i, 0.0) for i, v in f.items())
    idxs = set(f)
    qty = {e.idx: e.opened_qty for e in ctx.events}
    return {
        "baseline_pnl": _r(baseline), "whatif_pnl": _r(baseline + delta), "delta": _r(delta),
        "trades_removed": len(f), "units_removed": _r(sum(v * qty.get(i, 0) for i, v in f.items())),
        "closed_trades_affected": sum(1 for t in ctx.trades if idxs & set(t.open_idxs)),
        "open_units_vetoed": _r(sum(v * open_units.get(i, 0) for i, v in f.items())), "method": method}


def _rule(rid: str, title: str, status: str, parameter: Optional[dict[str, Any]], basis: str,
          what_if: Optional[dict[str, Any]], evidence: list[dict[str, Any]],
          caveats: list[str], **extra: Any) -> dict[str, Any]:
    return {"id": rid, "title": title, "status": status, "parameter": parameter,
            "threshold_basis": basis, "what_if": what_if, "evidence": evidence,
            "caveats": caveats, "variants": extra.get("variants", [])}


def _ev(label: str, value: Any, source: str) -> dict[str, Any]:
    return {"label": label, "value": value if value is None or isinstance(value, (int, float, str)) else str(value),
            "source": source}


def _stop_saved(trades: list[ClosedTrade], mult: float) -> tuple[float, int, dict[tuple, float]]:
    saved = 0.0
    n = 0
    per: dict[tuple, float] = {}
    for t in trades:
        if t.side >= 0 or t.pnl >= -EPS:
            continue
        planned = mult * t.entry_avg * t.qty
        if -t.pnl > planned + EPS:
            s = -t.pnl - planned
            saved += s
            n += 1
            per[(t.symbol, t.close_idx, t.close_date, t.estimated)] = s
    return saved, n, per


def suggestions(ctx: Ctx, overtrading: dict[str, Any], build: dict[str, Any],
                margin: dict[str, Any], lots: LotInfo) -> dict[str, Any]:
    cfg = ctx.cfg
    res = ctx.res
    p = cfg.suggestion_percentile
    trades = ctx.trades
    baseline = sum(t.pnl for t in trades)
    n_closed = len(trades)
    open_units: dict[int, int] = defaultdict(int)
    for lot in res.open_lots(ctx.include_est):
        open_units[lot.open_idx] += lot.qty
    entries = [e for e in ctx.events if e.opened_qty > 0]
    enough = n_closed >= cfg.suggestion_min_closed_trades
    rules: list[dict[str, Any]] = []
    vetoes: dict[str, dict[int, float]] = {}

    def insufficient(rid: str, title: str, why: str) -> dict[str, Any]:
        return _rule(rid, title, "insufficient_data", None, why, None, [], _CAVEATS)

    def finish(rid: str, title: str, f: dict[int, float], param: dict[str, Any], basis: str,
               evidence: list[dict[str, Any]], caveats: list[str], method: str = "veto_opening_fills") -> None:
        if not f:
            rules.append(_rule(rid, title, "not_triggered", param, basis, None, evidence, caveats))
            return
        vetoes[rid] = f
        rules.append(_rule(rid, title, "applicable", param, basis,
                           _what_if(ctx, f, baseline, open_units, method), evidence, caveats))

    # 1 — max trades per day
    t1 = "What-if: cap new entries per day"
    if not enough:
        rules.append(insufficient("max_trades_per_day", t1, "too few closed trades"))
    else:
        per_day: dict[date, list[FillEvent]] = defaultdict(list)
        for e in entries:
            per_day[e.fill.trade_date].append(e)
        counts = [float(len(v)) for v in per_day.values()]
        cap = int(pct_nearest(counts, p) or 0)
        f1 = {e.idx: 1.0 for evs in per_day.values() for e in sorted(evs, key=lambda x: x.idx)[cap:]}
        n_over = sum(1 for c in counts if c > cap)
        finish("max_trades_per_day", f"What-if: at most {cap} new entries per day",
               f1, {"name": "max_entries_per_day", "value": cap, "unit": "entries"},
               f"{p}th percentile of your daily entry counts over {len(counts)} active days",
               [_ev("Days above the cap", n_over, "overtrading.activity.active_days"),
                _ev("Median fills per active day", overtrading["activity"]["fills_per_day"]["median"],
                    "overtrading.activity.fills_per_day.median")],
               _CAVEATS + ["Entries beyond the cap each day (in time order) are treated as not taken."])

    # 2 — quantity cap per expiry
    t2 = "What-if: cap open units per expiry"
    gross: dict[tuple, dict[str, int]] = defaultdict(dict)
    peaks: dict[tuple, int] = {}
    for e in res.events:
        g = (e.fill.underlying, e.fill.expiry_ym or "unknown")
        _release_expired(gross, res, e.fill.trade_date)
        gross[g][e.fill.symbol] = abs(e.pos_after)
        if e.fill.trade_date >= ctx.date_from:
            peaks[g] = max(peaks.get(g, 0), sum(gross[g].values()))
    if not enough or len(peaks) < 2:
        rules.append(insufficient("qty_cap_per_expiry", t2,
                                  "too few closed trades" if not enough else "fewer than two expiry groups"))
    else:
        cap2 = int(pct_nearest([float(v) for v in peaks.values()], p) or 0)
        # Effective (post-veto) open units per group, tracked per symbol so lots held to expiry
        # (never closed by a fill) are released once the symbol has expired.
        eff: dict[tuple, dict[str, float]] = defaultdict(dict)
        f2: dict[int, float] = {}
        for e in res.events:
            g = (e.fill.underlying, e.fill.expiry_ym or "unknown")
            _release_expired(eff, res, e.fill.trade_date)
            sym = e.fill.symbol
            if e.closed_qty:
                eff[g][sym] = max(0.0, eff[g].get(sym, 0.0) - e.closed_qty)
            if e.opened_qty:
                add = e.opened_qty
                veto_u = 0.0
                if e.fill.trade_date >= ctx.date_from:
                    excess = max(0.0, sum(eff[g].values()) + add - cap2)
                    frac = min(1.0, excess / add)
                    if frac > EPS:
                        f2[e.idx] = frac
                    veto_u = frac * add
                eff[g][sym] = eff[g].get(sym, 0.0) + add - veto_u
        sizes = {lots.by_underlying.get(u) for (u, _x) in peaks if lots.available}
        lot_note = (_r(cap2 / next(iter(sizes)), 2) if len(sizes) == 1 and None not in sizes else None)
        finish("qty_cap_per_expiry", f"What-if: at most {cap2} open units per expiry",
               f2, {"name": "max_open_units_per_expiry", "value": cap2, "unit": "units",
                    "lots": lot_note},
               f"{p}th percentile of your peak open units across {len(peaks)} underlying/expiry groups",
               [_ev("Largest peak open units", max(peaks.values()), "buildup.timeline")],
               _CAVEATS + ["Chronological per underlying/expiry; a fill is vetoed pro rata by the units above the "
                           "cap (min(1, excess / fill units)); later closes do not reinstate vetoed units.",
                           "Lots shown only when the Kite master gives a single lot size."])

    # 3 — margin headroom floor
    t3 = "What-if: no new short entries when cash is low"
    cs = margin["cash_series"]
    vals = [c["cash"] for c in cs] if cs else []
    floor = pct_nearest(vals, 100 - p) if vals else None
    if not enough or not margin["ledger"]["available"] or not cs:
        rules.append(insufficient("margin_headroom_floor", t3,
                                  "too few closed trades" if not enough else "needs ledger cash history"))
    elif floor is not None and floor <= 0:
        # Ledger cash at/below zero for most of the period: margin is most likely funded by collateral
        # (e.g. pledged holdings) that the ledger does not show, so a cash floor is not meaningful.
        rules.append(insufficient(
            "margin_headroom_floor", t3,
            "ledger balance is at or below zero for most of the period (margin is probably funded by "
            "collateral the ledger does not show), so a cash floor is not meaningful"))
    else:
        dates = [c["date"] for c in cs]
        import bisect
        f3: dict[int, float] = {}
        for e in entries:
            if e.fill.sign >= 0:
                continue
            i = bisect.bisect_left(dates, e.fill.trade_date.isoformat())
            if i and vals[i - 1] < floor:
                f3[e.idx] = 1.0
        finish("margin_headroom_floor", f"What-if: no new short entries below {_r(floor, 0):,.0f} cash",
               f3, {"name": "min_cash_for_short_entry", "value": floor, "unit": "INR"},
               f"{100 - p}th percentile of your own daily ledger cash over {len(vals)} days",
               [_ev("Low-cash days (proxy)", margin["trap"]["days"], "margintrap.trap.days"),
                _ev("Lowest cash", margin["cash"]["min"], "margintrap.cash.min")],
               _CAVEATS + ["Prior-day settled cash only: excludes blocked margin and unrealised P&L; "
                           "cash is account-wide."])

    # 4 — stop discipline (exit adjustment, not a veto)
    t4 = "What-if: stop closed short trades at a multiple of premium"
    stop_delta = 0.0
    per_stop: dict[tuple, float] = {}
    ratios = [(-t.pnl) / (t.entry_avg * t.qty) for t in trades
              if t.side < 0 and t.pnl < -EPS and t.entry_avg * t.qty > 0]
    if not enough or not ratios:
        rules.append(insufficient("stop_discipline", t4,
                                  "too few closed trades" if not enough else "no losing short trades"))
    else:
        step = cfg.stop_multiple_step
        lstar = max(step, round(statistics.median(ratios) / step) * step)
        mults = sorted({lstar, *cfg.stop_loss_multiples})
        variants = []
        for m in mults:
            s, n, per = _stop_saved(trades, m)
            variants.append({"multiple": m, "saved_if_stopped": _r(s), "n_exceeded": n})
            if m == lstar:
                stop_delta, per_stop = s, per
        wi = {"baseline_pnl": _r(baseline), "whatif_pnl": _r(baseline + stop_delta),
              "delta": _r(stop_delta), "trades_removed": 0, "units_removed": 0.0,
              "closed_trades_affected": len(per_stop), "open_units_vetoed": 0.0,
              "method": "exit_adjustment_one_sided"}
        rules.append(_rule(
            "stop_discipline", f"What-if: stop shorts at {lstar:g}x premium", "applicable" if per_stop else "not_triggered",
            {"name": "stop_multiple", "value": lstar, "unit": "x premium"},
            f"median loss / premium over {len(ratios)} losing short trades, rounded to {step:g}",
            wi if per_stop else None,
            [_ev("Losing short trades", len(ratios), "margintrap.stops.short_closed"),
             _ev("Median loss / premium", _r(statistics.median(ratios), 3), "margintrap.stops.rows")],
            _CAVEATS + ["One-sided: whipsaw stops (price touched the stop then recovered) and slippage cannot be "
                        "seen from fills, so the saving can read as overstated.",
                        "Exit adjustment, reported separately from the entry vetoes."],
            variants=variants))

    # 5 — no averaging down
    t5 = "What-if: no adds at a worse price than the average entry"
    if not enough:
        rules.append(insufficient("no_averaging_down", t5, "too few closed trades"))
    else:
        f5 = {e.idx: 1.0 for e in ctx.events if e.adverse_add}
        finish("no_averaging_down", t5, f5, {"name": "adverse_adds_allowed", "value": 0, "unit": "fills"},
               "every add made at a price worse than the average entry of the open position",
               [_ev("Adverse-add fills", build["averaging"]["adverse_add_fills"],
                    "buildup.averaging.adverse_add_fills"),
                _ev("Closed P&L of slices opened by adverse adds", build["averaging"]["adverse_add_closed_pnl"],
                    "buildup.averaging.adverse_add_closed_pnl")],
               _CAVEATS)

    # 6 — cooling-off after a loss
    t6 = "What-if: pause after a losing close"
    if not enough or not ctx.ts_ok:
        rules.append(insufficient("cooling_off_after_loss", t6,
                                  "too few closed trades" if not enough else "needs execution timestamps"))
    else:
        last_loss: dict[str, Any] = {}
        gaps: list[tuple[int, float]] = []
        for e in res.events:
            f = e.fill
            if f.exec_dt is None:
                continue
            ll = last_loss.get(f.underlying)
            if e.opened_qty > 0 and ll is not None and ll.date() == f.exec_dt.date() \
                    and f.trade_date >= ctx.date_from:
                gaps.append((e.idx, (f.exec_dt - ll).total_seconds() / 60.0))
            if e.closed_qty > 0 and e.realised < -EPS:
                last_loss[f.underlying] = f.exec_dt
        if not gaps:
            rules.append(_rule("cooling_off_after_loss", t6, "not_triggered", None,
                               "no same-day re-entry after a losing close", None, [], _CAVEATS))
        else:
            k = min(max(round(statistics.median(g for _, g in gaps)), cfg.cooling_off_min_minutes),
                    cfg.cooling_off_max_minutes)
            f6 = {i: 1.0 for i, g in gaps if g < k}
            finish("cooling_off_after_loss", f"What-if: wait {k} minutes after a losing close",
                   f6, {"name": "cooling_off_minutes", "value": k, "unit": "minutes"},
                   f"median re-entry gap after a losing close over {len(gaps)} re-entries, clamped to "
                   f"[{cfg.cooling_off_min_minutes}, {cfg.cooling_off_max_minutes}]",
                   [_ev("Re-entries after a loss", len(gaps), "overtrading.bursts.reentries_after_loss.count")],
                   _CAVEATS + ["Same underlying, same day only."])

    # 7-10 — spot-linked rules (F42 P4), same Rule shape and what-if arithmetic
    spot_view = spot_vs_pnl(ctx, [], sorted({f.underlying for f in res.fills}))
    sp_rules, sp_vetoes = spot_rules(ctx, spot_view)
    rules.extend(sp_rules)
    vetoes.update(sp_vetoes)

    # combined (union of veto rules; max fraction per fill) + stop add-on reported separately
    inc = [r for r in _VETO_RULES if r in vetoes]
    comb: dict[int, float] = {}
    for rid in inc:
        for i, v in vetoes[rid].items():
            comb[i] = max(comb.get(i, 0.0), v)
    combined: dict[str, Any] = {"rules_included": inc, "what_if": _what_if(ctx, comb, baseline, open_units,
                                "union_of_vetoes_max_fraction") if comb else None,
                                "stop_addon": _r(stop_delta) if per_stop else None,
                                "combined_with_stop": None}
    if per_stop and enough:
        seg_by_trade: dict[tuple, list] = defaultdict(list)
        for s in ctx.segs:
            seg_by_trade[(s.symbol, s.close_idx, s.close_date, s.estimated)].append(s)
        extra = 0.0
        for key, saved in per_stop.items():
            ss = seg_by_trade.get(key, [])
            q = sum(s.qty for s in ss)
            keep = sum(s.qty * (1.0 - comb.get(s.open_idx, 0.0)) for s in ss)
            extra += saved * (keep / q if q else 0.0)
        base_delta = combined["what_if"]["delta"] if combined["what_if"] else 0.0
        combined["combined_with_stop"] = _r(base_delta + extra)
    combined.update(_info(
        "Union of the entry vetoes (largest veto fraction per fill, so nothing is double counted). The stop "
        "rule is an exit adjustment: its saving is shown separately as stop_addon, and combined_with_stop adds "
        "it only on the non-vetoed share of each stopped trade.",
        ["In-sample what-if; no second-order effects; gross of charges."]))

    # observations
    obs: list[dict[str, Any]] = []
    ch = overtrading["churn"]
    if ch["churn_qty_pct"] is not None and ch["churn_qty_pct"] >= cfg.observation_high_churn_pct:
        obs.append({"id": "high_churn", "text": f"{ch['churn_qty_pct']}% of closed volume was opened and closed "
                    f"the same day ({ch['same_day_trades']} trades, gross P&L {ch['churn_pnl']}).",
                    "evidence": [_ev("churn_qty_pct", ch["churn_qty_pct"], "overtrading.churn.churn_qty_pct")]})
    av = build["averaging"]
    if av["adverse_add_fills"]:
        obs.append({"id": "averaging_down_present", "text": f"{av['adverse_add_fills']} adds were made at a worse "
                    f"price than the average entry ({av['share_of_entries_pct']}% of entries); closed P&L of the "
                    f"slices they opened: {av['adverse_add_closed_pnl']}.",
                    "evidence": [_ev("adverse_add_fills", av["adverse_add_fills"],
                                     "buildup.averaging.adverse_add_fills")]})
    rows = margin["stops"]["rows"]
    if rows and rows[0]["n_exceeded"]:
        r0 = rows[0]
        obs.append({"id": "stops_exceeded", "text": f"{r0['n_exceeded']} closed short trades lost more than "
                    f"{r0['multiple']:g}x the premium collected (loss beyond that level: "
                    f"{r0['saved_if_stopped']}).",
                    "evidence": [_ev("n_exceeded", r0["n_exceeded"], "margintrap.stops.rows")]})
    if margin["trap"]["days"]:
        obs.append({"id": "low_cash_with_losers", "text": f"{margin['trap']['days']} days (proxy) combined low "
                    f"ledger cash with at least one open position at a known loss.",
                    "evidence": [_ev("days", margin["trap"]["days"], "margintrap.trap.days")]})

    order = {"applicable": 0, "not_triggered": 1, "insufficient_data": 2, "illustrative": 3}
    rules.sort(key=lambda r: (order[r["status"]], -(r["what_if"]["delta"] if r["what_if"] else 0.0)))
    return {"disclaimer": DISCLAIMER, "sample": {"closed_trades": n_closed,
                                                 "min_required": cfg.suggestion_min_closed_trades},
            "baseline_pnl": _r(baseline), "rules": rules, "combined": combined, "observations": obs,
            **_info("Rule-based what-ifs built from your own closed trades: each rule's threshold comes from "
                    "your own percentiles or medians, and the what-if shows the P&L had that rule applied.",
                    ["Descriptive, deterministic, computed locally; no model or external service is used.",
                     "Vetoing an entry removes the FIFO slices it opened; the book is not re-simulated."])}


# ── F42 P4: spot-linked rules ────────────────────────────────────────────────────


def _eod_bias_samples(ctx: Ctx) -> list[float]:
    """|EOD directional bias| of each underlying on each day the user had a fill in the window."""
    res = ctx.res
    active: dict[str, set[date]] = defaultdict(set)
    for e in ctx.events:
        active[e.fill.underlying].add(e.fill.trade_date)
    cutoffs = sorted({d for ds in active.values() for d in ds})
    snaps = sweep_positions(res, cutoffs)
    out: list[float] = []
    for u, ds in active.items():
        for d in ds:
            b = sum(delta_sign(res.meta[s].itype, 1 if p.qty > 0 else -1) * abs(p.qty)
                    for s, p in snaps[d].items() if res.meta[s].underlying == u)
            out.append(float(abs(b)))
    return out


def _bias_of(eff: dict[str, float], res: Any, u: str) -> float:
    return sum(delta_sign(res.meta[s].itype, 1 if q > 0 else -1) * abs(q)
               for s, q in eff.items() if q and res.meta[s].underlying == u)


def spot_rules(ctx: Ctx, spot_view: dict[str, Any],
               days: Optional[dict[str, list[SpotDay]]] = None) -> tuple[list[dict[str, Any]], dict[str, dict[int, float]]]:
    """The four spot-linked rules.  Returns (rules, veto fractions per veto rule id).

    1 bias_limit, 2 expiry_proximity_entries, 3 counter_move_entries are opening-fill vetoes with
    the shared what-if arithmetic; 4 bias_hedge_illustrative is an ESTIMATE-tagged bound, never a
    veto and never part of ``combined``."""
    days = spot_days(ctx) if days is None else days
    cfg = ctx.cfg
    res = ctx.res
    p = cfg.suggestion_percentile
    baseline = sum(t.pnl for t in ctx.trades)
    enough = len(ctx.trades) >= cfg.suggestion_min_closed_trades
    open_units: dict[int, int] = defaultdict(int)
    for lot in res.open_lots(ctx.include_est):
        open_units[lot.open_idx] += lot.qty
    entries = [e for e in ctx.events if e.opened_qty > 0]
    rules: list[dict[str, Any]] = []
    vetoes: dict[str, dict[int, float]] = {}
    blocks = {b["underlying"]: b for b in spot_view.get("underlyings", [])}
    has_spot = any(u in ctx.spot for u in blocks)

    def insufficient(rid: str, title: str, why: str) -> None:
        rules.append(_rule(rid, title, "insufficient_data", None, why, None, [], _CAVEATS))

    def finish(rid: str, title: str, f: dict[int, float], param: dict[str, Any], basis: str,
               evidence: list[dict[str, Any]], caveats: list[str]) -> None:
        if not f:
            rules.append(_rule(rid, title, "not_triggered", param, basis, None, evidence, caveats))
            return
        vetoes[rid] = f
        rules.append(_rule(rid, title, "applicable", param, basis,
                           _what_if(ctx, f, baseline, open_units, "veto_opening_fills"), evidence, caveats))

    def al_ev() -> list[dict[str, Any]]:
        out = []
        for u, b in sorted(blocks.items()):
            al = b.get("alignment")
            if al:
                out.append(_ev(f"{u} share of days with the market", al["pct_with"], f"spotpnl.{u}.alignment.pct_with"))
                out.append(_ev(f"{u} net units x points", al["net_units_pts"], f"spotpnl.{u}.alignment.net_units_pts"))
        return out

    # 1 — bias limit
    t1 = "What-if: net directional bias capped"
    samples = _eod_bias_samples(ctx) if enough and has_spot else []
    bound = pct_nearest(samples, p) if samples else None
    if not enough or not has_spot or bound is None:
        insufficient("bias_limit", t1, "too few closed trades" if not enough else
                     "needs spot history and trading days")
    else:
        cap = int(bound)
        eff: dict[str, float] = {}
        f1: dict[int, float] = {}
        for e in res.events:
            f = e.fill
            for sym in [s for s in eff if (x := res.meta[s].expiry_eff) is not None and x < f.trade_date]:
                del eff[sym]
            sym = f.symbol
            if e.closed_qty:
                q = eff.get(sym, 0.0)
                eff[sym] = max(0.0, q - e.closed_qty) if q > 0 else min(0.0, q + e.closed_qty)
            if e.opened_qty:
                add = float(e.opened_qty)
                veto_u = 0.0
                if f.trade_date >= ctx.date_from:
                    u = f.underlying
                    b = _bias_of(eff, res, u)
                    d = delta_sign(f.itype, f.sign)
                    nb = b + d * add
                    floor_ = max(float(cap), abs(b))
                    if abs(nb) > floor_ + EPS:
                        frac = min(1.0, (abs(nb) - floor_) / add)
                        f1[e.idx] = frac
                        veto_u = frac * add
                eff[sym] = eff.get(sym, 0.0) + f.sign * (add - veto_u)
        finish("bias_limit", f"What-if: net directional bias capped at {cap} units", f1,
               {"name": "max_abs_bias_units", "value": cap, "unit": "units"},
               f"{p}th percentile of your end-of-day |directional bias| over {len(samples)} "
               "underlying-days on which you traded",
               [_ev("Days sampled", len(samples), "spotpnl.alignment")] + al_ev(),
               _CAVEATS + ["Per underlying, chronological; a fill is vetoed pro rata by the units that push "
                           "|bias| above the limit in the direction increasing |bias|.",
                           "Bias is a delta-sign proxy counting every open unit as +-1 regardless of delta."])

    # 2 — expiry proximity
    t2 = "What-if: no new entries close to expiry"
    if not enough:
        insufficient("expiry_proximity_entries", t2, "too few closed trades")
    else:
        n_d = cfg.expiry_proximity_days
        f2 = {e.idx: 1.0 for e in entries
              if e.fill.expiry_eff is not None and 0 <= (e.fill.expiry_eff - e.fill.trade_date).days <= n_d}
        exp_ev = []
        for u, b in sorted(blocks.items()):
            rel = b.get("relationship")
            xb = next((x for x in rel["expiry_days"] if x["key"] == "expiry"), None) if rel else None
            if xb and xb["available"]:
                exp_ev.append(_ev(f"{u} expiry-day P&L", xb["total_pnl"], f"spotpnl.{u}.relationship.expiry_days"))
        finish("expiry_proximity_entries", f"What-if: no new entries within {n_d} days of expiry", f2,
               {"name": "expiry_proximity_days", "value": n_d, "unit": "days"},
               "entries made within the configured number of calendar days of the symbol's expiry",
               [_ev("Entries in window", len(entries), "buildup.events")] + exp_ev,
               _CAVEATS + ["The delta can be positive or negative; reported either way."])

    # 3 — counter-move entries
    t3 = "What-if: no entries leaning against a just-completed sharp move"
    if not enough or not ctx.spot:
        insufficient("counter_move_entries", t3,
                     "too few closed trades" if not enough else "needs spot history")
    else:
        f3: dict[int, float] = {}
        for e in entries:
            f = e.fill
            ss = ctx.spot.get(f.underlying)
            if not ss:
                continue
            i = bisect.bisect_left(ss.dates, f.trade_date) - 1      # previous session (may precede date_from)
            if i < 1 or (f.trade_date - ss.dates[i]).days > cfg.spot_stale_days:
                continue
            r = _ret_pct(ss.closes[i], ss.closes[i - 1])
            if abs(r) >= cfg.turn_threshold_pct and delta_sign(f.itype, f.sign) * _sgn(r) < 0:
                f3[e.idx] = 1.0
        big_ev = []
        for u, b in sorted(blocks.items()):
            rel = b.get("relationship")
            if rel and rel["big_any"]["available"]:
                big_ev.append(_ev(f"{u} big-move-day P&L", rel["big_any"]["total_pnl"],
                                  f"spotpnl.{u}.relationship.big_any"))
        finish("counter_move_entries", t3, f3,
               {"name": "turn_threshold_pct", "value": cfg.turn_threshold_pct, "unit": "% prior-day move"},
               "entries whose delta direction opposed the previous session's return when that return was "
               "at least the turn threshold",
               [_ev("Entries in window", len(entries), "buildup.events")] + big_ev,
               _CAVEATS + ["Previous session = last spot day before the fill (within the stale limit)."])

    # 4 — illustrative delta-1 offset (ESTIMATE, not a veto, not in combined)
    t4 = "Illustrative: delta-1 offset of units above the bias limit"
    if not enough or not has_spot or bound is None:
        insufficient("bias_hedge_illustrative", t4, "too few closed trades" if not enough else
                     "needs spot history and trading days")
    else:
        cap4 = float(int(bound))
        offset = 0.0
        n_days = 0
        for day_list in days.values():
            for sd in day_list:
                if abs(sd.bias) > cap4:
                    excess = sd.bias - _sgn(sd.bias) * cap4
                    offset += -excess * (sd.close - sd.prev_close)
                    n_days += 1
        if n_days:
            rules.append(_rule(
                "bias_hedge_illustrative", t4, "illustrative",
                {"name": "illustrative_offset_inr", "value": _r(offset), "unit": "INR (estimate)"},
                f"Illustrative bound: offsetting the units above {int(cap4)} with a delta-1 hedge on {n_days} "
                f"days would have changed P&L by INR {_r(offset):,.0f} (ESTIMATE, upper bound, not P&L you "
                "would have had).", None, [_ev("Days above the limit", n_days, "spotpnl.alignment")],
                _CAVEATS + ["A delta-1 hedge over-states the hedge of an option book (option delta <= 1); no "
                            "hedge instrument, cost or margin is modelled.",
                            "Not a veto and not part of the combined what-if."]))
        else:
            rules.append(_rule("bias_hedge_illustrative", t4, "not_triggered",
                               {"name": "illustrative_offset_inr", "value": 0.0, "unit": "INR (estimate)"},
                               "no day had |bias| above the limit", None, [], _CAVEATS))
    return rules, vetoes
