"""F42 P4 — "Spot vs P&L": how the underlying moved against the user's realised P&L.

Pure module (no I/O, no DB, no settings import): callers pass ``ctx`` (the shared analytics
context) and the P&L-sheet lines.  Every number is MEASURED from the user's own rows unless it
is tagged ESTIMATE (expiry-held lots closed at spot-intrinsic, the delta-sign bias proxy).

Realised P&L is realised-timing, not mark-to-market: a weak, lagged proxy for exposure.  The
directional-bias alignment is the primary "with or against the market" evidence, correlation and
beta are secondary.  Small samples: every statistic goes null with ``insufficient_sample`` below
its configured minimum.  Descriptive wording only.
"""
from __future__ import annotations

import bisect
import math
import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

from rita.services.fno_trade_analytics import (
    EPS, Ctx, PnlLine, SpotDay, _info, _iso, _r, _sgn, spot_days,
)
from rita.services.fno_trade_fifo import Segment

DELTA1_NOTE = ("delta1_bound_pnl = bias units x spot change; an estimate that bounds, not "
               "measures, the option P&L.")
MULTI_NOTE = ("Several buckets and up to a handful of observations are read off one small sample; "
              "an isolated notable item should not be over-read.")


# ── statistics helpers (plain Python) ───────────────────────────────────────────


def _mean(v: list[float]) -> float:
    return sum(v) / len(v)


def _cov_var(x: list[float], y: list[float]) -> tuple[float, float, float]:
    mx, my = _mean(x), _mean(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy, sxx, syy


def _ranks(v: list[float]) -> list[float]:
    """Average ranks (1-based); tied values share the mean of their positions."""
    order = sorted(range(len(v)), key=lambda i: v[i])
    out = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and abs(v[order[j + 1]] - v[order[i]]) <= EPS:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def corr_block(ret: list[float], pnl: list[float], min_n: int, z: float, mixed: bool) -> dict[str, Any]:
    """Pearson / Spearman / beta (INR per +1% spot) with a no-correlation significance flag."""
    n = len(ret)
    blk: dict[str, Any] = {"n": n, "pearson": None, "spearman": None, "beta_inr_per_pct": None,
                           "r2": None, "significant": None, "reason": None,
                           "min_required": min_n, "basis_tag": "mixed" if mixed else "measured"}
    if n < min_n:
        blk["reason"] = "insufficient_sample"
        return blk
    sxy, sxx, syy = _cov_var(ret, pnl)
    if sxx <= EPS or syy <= EPS:
        blk["reason"] = "no_variation"
        return blk
    pearson = sxy / math.sqrt(sxx * syy)
    rr, rp = _ranks(ret), _ranks(pnl)
    rxy, rxx, ryy = _cov_var(rr, rp)
    blk.update({"pearson": _r(pearson, 4), "spearman": _r(rxy / math.sqrt(rxx * ryy), 4)
                if rxx > EPS and ryy > EPS else None,
                "beta_inr_per_pct": _r(sxy / sxx), "r2": _r(pearson ** 2, 4),
                "significant": abs(pearson) > z / math.sqrt(n)})
    return blk


def wilson(k: int, n: int, z: float) -> tuple[Optional[float], Optional[float]]:
    """Wilson score interval in percent; (None, None) for n == 0."""
    if n <= 0:
        return None, None
    p = k / n
    den = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half) * 100.0, min(1.0, centre + half) * 100.0


# ── daily series ─────────────────────────────────────────────────────────────────


def _segments_by_und(ctx: Ctx) -> dict[str, list[Segment]]:
    out: dict[str, list[Segment]] = defaultdict(list)
    for s in ctx.segs:
        out[s.underlying].append(s)
    return out


def _build_days(ctx: Ctx, u: str, days: list[SpotDay], segs: list[Segment]) -> dict[str, Any]:
    """Aligned per-day arrays for one underlying plus roll-forward bookkeeping."""
    cfg = ctx.cfg
    dates = [sd.d for sd in days]
    meas = [0.0] * len(days)
    est = [0.0] * len(days)
    closing = [0] * len(days)
    rolled_days: set[date] = set()
    rolled_amt = 0.0
    after_amt = 0.0
    after_n = 0
    for s in segs:
        i = bisect.bisect_left(dates, s.close_date)
        if i >= len(dates):
            after_amt += s.pnl
            after_n += 1
            continue
        if dates[i] != s.close_date:
            rolled_days.add(s.close_date)
            rolled_amt += s.pnl
        if s.estimated:
            est[i] += s.pnl
        else:
            meas[i] += s.pnl
        closing[i] = 1
    expiry_dates = {m.expiry_eff for m in ctx.res.meta.values()
                    if m.underlying == u and m.expiry_eff is not None}
    big, rev, exp, adv = [], [], [], []
    for sd in days:
        b = abs(sd.ret) >= cfg.turn_threshold_pct
        big.append(1 if b else 0)
        rev.append(1 if b and _sgn(sd.prev_ret) != 0 and _sgn(sd.ret) != _sgn(sd.prev_ret) else 0)
        exp.append(1 if sd.d in expiry_dates else 0)
        adv.append(1 if _sgn(sd.bias) * sd.ret < 0 else 0)
    return {"dates": dates, "meas": meas, "est": est, "closing": closing, "big": big, "rev": rev,
            "exp": exp, "adv": adv, "rolled_days": len(rolled_days), "rolled_amt": rolled_amt,
            "after_amt": after_amt, "after_n": after_n}


def _bucket(key: str, idxs: list[int], pnl: list[float], meas: list[float], est: list[float],
            closing: list[int], total_loss: float, min_days: int) -> dict[str, Any]:
    n = len(idxs)
    nc = sum(closing[i] for i in idxs)
    blk: dict[str, Any] = {"key": key, "n_days": n, "n_closing_days": nc, "total_pnl": None,
                           "total_measured": None, "total_estimate": None, "mean_pnl": None,
                           "median_pnl": None, "hit_rate_pct": None, "share_of_total_loss_pct": None,
                           "available": n >= min_days, "reason": None, "min_required": min_days}
    if n < min_days:
        blk["reason"] = "insufficient_sample"
        return blk
    vals = [pnl[i] for i in idxs]
    losses = sum(v for v in vals if v < -EPS)
    blk.update({
        "total_pnl": _r(sum(vals)), "total_measured": _r(sum(meas[i] for i in idxs)),
        "total_estimate": _r(sum(est[i] for i in idxs)),
        "mean_pnl": _r(_mean(vals)) if vals else None,
        "median_pnl": _r(statistics.median(vals)) if vals else None,
        "hit_rate_pct": _r(sum(1 for i in idxs if closing[i] and pnl[i] > EPS) / nc * 100.0) if nc else None,
        "share_of_total_loss_pct": _r(losses / total_loss * 100.0) if total_loss < -EPS else None})
    return blk


def _alignment(cfg: Any, days: list[SpotDay]) -> dict[str, Any]:
    band = cfg.spot_flat_band_pct
    with_n = against_n = flat_market = flat_book = 0
    with_pts = against_pts = 0.0
    bull: list[float] = []
    bear: list[float] = []
    for sd in days:
        if sd.bias > 0:
            bull.append(sd.ret)
        elif sd.bias < 0:
            bear.append(sd.ret)
        if sd.bias == 0:
            flat_book += 1
            continue
        if abs(sd.ret) < band or sd.ret == 0:
            flat_market += 1
            continue
        pts = sd.bias * (sd.close - sd.prev_close)
        if _sgn(sd.bias) * sd.ret > 0:
            with_n += 1
            with_pts += pts
        else:
            against_n += 1
            against_pts += pts
    scored = with_n + against_n
    lo, hi = wilson(with_n, scored, cfg.spot_rel_ci_z)
    pct_with = with_n / scored * 100.0 if scored else None
    if scored < cfg.spot_rel_min_bias_days:
        verdict = "insufficient_sample"
    elif lo is not None and lo > 50.0:
        verdict = "with_market"
    elif hi is not None and hi < 50.0:
        verdict = "against_market"
    else:
        verdict = "no_clear_lean"
    return {
        "days_with_bias": len([d for d in days if d.bias != 0]), "with_n": with_n,
        "against_n": against_n, "flat_market_n": flat_market, "flat_book_n": flat_book,
        "pct_with": _r(pct_with), "pct_with_ci_low": _r(lo), "pct_with_ci_high": _r(hi),
        "verdict": verdict, "min_required": cfg.spot_rel_min_bias_days,
        "with_units_pts": _r(with_pts), "against_units_pts": _r(against_pts),
        "net_units_pts": _r(with_pts + against_pts),
        "by_bias": {"bullish": {"n": len(bull), "mean_ret_pct": _r(_mean(bull), 3) if bull else None},
                    "bearish": {"n": len(bear), "mean_ret_pct": _r(_mean(bear), 3) if bear else None}},
        "tag": "estimated",
        "caveat": ("Consecutive days share the same book, so the Wilson interval (which assumes "
                   "independent days) is too narrow: read the verdict as indicative. Bias counts every "
                   "open unit as +1 or -1 regardless of moneyness or delta, so far-OTM and ITM options "
                   "weigh the same; it indicates direction, not magnitude.")}


def _fmt(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:,.0f}"


def _observations(cfg: Any, u: str, rel: dict[str, Any], al: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    src = f"{u}.relationship"

    def ev(label: str, value: Any, path: str) -> dict[str, Any]:
        return {"label": label, "value": value, "source": path}

    if al["verdict"] == "against_market":
        out.append({"id": "book_against_market", "text": (
            f"On {u}, in {al['with_n'] + al['against_n']} scored days your start-of-day book was "
            f"positioned with the market on {al['pct_with']}% of days (95% interval "
            f"{al['pct_with_ci_low']}-{al['pct_with_ci_high']}%), i.e. mostly against it. "
            "Observed in this sample; not a prediction."),
            "evidence": [ev("pct_with", al["pct_with"], f"{u}.alignment.pct_with"),
                         ev("net_units_pts", al["net_units_pts"], f"{u}.alignment.net_units_pts")]})
    elif al["verdict"] == "with_market":
        out.append({"id": "book_with_market", "text": (
            f"On {u}, in {al['with_n'] + al['against_n']} scored days your start-of-day book was "
            f"positioned with the market on {al['pct_with']}% of days (95% interval "
            f"{al['pct_with_ci_low']}-{al['pct_with_ci_high']}%). Observed in this sample; not a "
            "prediction."),
            "evidence": [ev("pct_with", al["pct_with"], f"{u}.alignment.pct_with"),
                         ev("net_units_pts", al["net_units_pts"], f"{u}.alignment.net_units_pts")]})
    down = next((b for b in rel["by_direction"] if b["key"] == "down"), None)
    if down and down["available"] and down["total_pnl"] is not None and down["total_pnl"] < 0:
        out.append({"id": "loses_on_down_days", "text": (
            f"On {u} down days (n={down['n_days']}) your realised P&L was INR {_fmt(down['total_pnl'])} "
            f"in total (median INR {_fmt(down['median_pnl'])}). Observed in this sample; not a prediction."),
            "evidence": [ev("total_pnl", down["total_pnl"], f"{src}.by_direction[down].total_pnl"),
                         ev("n_days", down["n_days"], f"{src}.by_direction[down].n_days")]})
    anyb = rel["big_any"]
    if anyb["available"] and anyb["share_of_total_loss_pct"] is not None \
            and anyb["share_of_total_loss_pct"] >= cfg.spot_obs_concentration_pct:
        out.append({"id": "big_move_concentration", "text": (
            f"On {u}, big-move days (n={anyb['n_days']}) carried {anyb['share_of_total_loss_pct']}% of "
            f"your total realised loss (INR {_fmt(anyb['total_pnl'])} on those days). Observed in this "
            "sample; not a prediction."),
            "evidence": [ev("share_of_total_loss_pct", anyb["share_of_total_loss_pct"],
                            f"{src}.big_any.share_of_total_loss_pct"),
                         ev("n_days", anyb["n_days"], f"{src}.big_any.n_days")]})
    expb = next((b for b in rel["expiry_days"] if b["key"] == "expiry"), None)
    if expb and expb["available"] and expb["total_pnl"] is not None and expb["total_pnl"] < 0:
        out.append({"id": "expiry_day_loss", "text": (
            f"On {u} expiry days (n={expb['n_days']}) realised P&L was INR {_fmt(expb['total_pnl'])} "
            f"(measured INR {_fmt(expb['total_measured'])}, estimate INR {_fmt(expb['total_estimate'])}). "
            "Observed in this sample; not a prediction."),
            "evidence": [ev("total_pnl", expb["total_pnl"], f"{src}.expiry_days[expiry].total_pnl")]})
    cd = rel["closing_days"]
    if cd["significant"] is True and cd["beta_inr_per_pct"] is not None and cd["beta_inr_per_pct"] < 0:
        out.append({"id": "negative_beta", "text": (
            f"On {u} closing days (n={cd['n']}) realised P&L tended to be higher on down days: beta "
            f"INR {_fmt(cd['beta_inr_per_pct'])} per +1% spot, correlation {cd['pearson']}. Observed in "
            "this sample; not a prediction."),
            "evidence": [ev("beta_inr_per_pct", cd["beta_inr_per_pct"], f"{src}.closing_days.beta_inr_per_pct"),
                         ev("pearson", cd["pearson"], f"{src}.closing_days.pearson")]})
    gated: list[str] = []
    for name, blk in (("all-days correlation", rel["all_days"]), ("closing-days correlation", rel["closing_days"])):
        if blk["reason"] == "insufficient_sample":
            gated.append(name)
    for b in rel["by_direction"]:
        if b["key"] in ("up", "down") and b["reason"] == "insufficient_sample":
            gated.append(f"{b['key']}-day bucket")
    if anyb["reason"] == "insufficient_sample":
        gated.append("big-move days")
    if expb and expb["reason"] == "insufficient_sample":
        gated.append("expiry days")
    if al["verdict"] == "insufficient_sample":
        gated.append("directional alignment")
    if gated:
        out.append({"id": "low_sample", "text": (
            f"On {u}, too few days for: {', '.join(gated)}. Those statistics are withheld."),
            "evidence": [ev("withheld", len(gated), f"{u}.relationship")]})
    out = out[: cfg.spot_obs_max]
    if out:
        out[-1] = {**out[-1], "text": out[-1]["text"] + " " + MULTI_NOTE}
    return out


def _snapshot(ctx: Ctx, u: str, lines: list[PnlLine], spot_last: Optional[date]) -> dict[str, Any]:
    cfg = ctx.cfg
    base: dict[str, Any] = {
        "available": False, "reason": None, "as_of": None, "amount": None, "n_symbols": 0,
        "fifo_open_symbols": 0, "symbols_missing_in_sheet": 0, "days_behind_spot": None,
        "stale": None, "tag": "measured",
        "note": ("Unrealised P&L of the open book as marked on the P&L sheet at its period end: one "
                 "snapshot per symbol (latest period), not a daily series and not part of the "
                 "correlation.")}
    fifo_open = {lot.symbol for lot in ctx.res.open_lots(ctx.include_est) if lot.underlying == u}
    mine = [ln for ln in lines if ln.underlying == u]
    latest: dict[str, PnlLine] = {}
    for ln in mine:
        cur = latest.get(ln.symbol)
        if cur is None or (ln.period_to, ln.period_from) > (cur.period_to, cur.period_from):
            latest[ln.symbol] = ln
    used = {sym: ln for sym, ln in latest.items()
            if ln.unrealized_pnl is not None and ln.open_quantity not in (None, 0)}
    base["fifo_open_symbols"] = len(fifo_open)
    base["symbols_missing_in_sheet"] = len(fifo_open - set(used))
    if not fifo_open:
        base["reason"] = "no_open_positions"
        return base
    if not used or base["symbols_missing_in_sheet"] == len(fifo_open):
        base["reason"] = "no_pnl_sheet"
        return base
    as_of = max(ln.period_to for ln in used.values())
    behind = (spot_last - as_of).days if spot_last else None
    stale = behind is not None and behind > cfg.sheet_snapshot_stale_days
    base.update({"available": True, "reason": "sheet_stale" if stale else None, "as_of": _iso(as_of),
                 "amount": _r(sum(float(ln.unrealized_pnl or 0.0) for ln in used.values())),
                 "n_symbols": len(used), "days_behind_spot": behind, "stale": stale})
    return base


def _empty_series() -> dict[str, Any]:
    return {k: [] for k in ("dates", "spot_close", "ret_pct", "realised_measured", "realised_estimate",
                            "cum_measured", "cum_total", "bias_in", "closing_day", "big_move_flag",
                            "reversal_flag", "expiry_flag", "adverse_flag")} | {"truncated": False,
                                                                                "dropped_days": 0}


def _block(ctx: Ctx, u: str, days: Optional[list[SpotDay]], segs: list[Segment],
           lines: list[PnlLine]) -> dict[str, Any]:
    cfg = ctx.cfg
    spot_ss = ctx.spot.get(u)
    spot_last = spot_ss.dates[-1] if spot_ss else None
    stale = (spot_last < min(ctx.date_to, ctx.res.as_of) - timedelta(days=cfg.spot_stale_days)
             if spot_last else None)
    has_fills = any(f.underlying == u for f in ctx.res.fills)
    meas_total = sum(s.pnl for s in segs if not s.estimated)
    est_total = sum(s.pnl for s in segs if s.estimated)
    blk: dict[str, Any] = {
        "underlying": u, "available": True, "reason": None,
        "spot_last_date": _iso(spot_last), "spot_stale": stale, "series": _empty_series(),
        "totals": {"measured_realised": _r(meas_total), "estimated_realised": _r(est_total),
                   "pnl_rolled_days": 0, "pnl_rolled_amount": 0.0, "pnl_after_last_spot": 0.0,
                   "pnl_after_last_spot_count": 0, "n_days": 0, "n_closing_days": 0,
                   "realised_plus_unrealised": None},
        "unrealised_snapshot": _snapshot(ctx, u, lines, spot_last),
        "relationship": None, "alignment": None, "observations": []}
    if not has_fills:
        blk.update({"available": False, "reason": "no_trades_for_underlying"})
        return blk
    if days is None:
        blk.update({"available": False, "reason": "spot_unavailable"})
        return blk

    d = _build_days(ctx, u, days, segs)
    n = len(days)
    pnl = [d["meas"][i] + d["est"][i] for i in range(n)]
    ret = [sd.ret for sd in days]
    band = cfg.spot_flat_band_pct
    thr = cfg.turn_threshold_pct
    total_loss = sum(v for v in pnl if v < -EPS)

    # cumulative (full window, before any truncation)
    cm, ct, cum_m, cum_t = 0.0, 0.0, [], []
    for i in range(n):
        cm += d["meas"][i]
        ct += pnl[i]
        cum_m.append(_r(cm))
        cum_t.append(_r(ct))
    keep = min(n, cfg.spot_series_max_points)
    cut = n - keep
    sl = slice(cut, n)
    blk["series"] = {
        "dates": [x.isoformat() for x in d["dates"][sl]], "spot_close": [_r(sd.close) for sd in days[sl]],
        "ret_pct": [_r(sd.ret, 3) for sd in days[sl]],
        "realised_measured": [_r(v) for v in d["meas"][sl]], "realised_estimate": [_r(v) for v in d["est"][sl]],
        "cum_measured": cum_m[sl], "cum_total": cum_t[sl], "bias_in": [sd.bias for sd in days[sl]],
        "closing_day": d["closing"][sl], "big_move_flag": d["big"][sl], "reversal_flag": d["rev"][sl],
        "expiry_flag": d["exp"][sl], "adverse_flag": d["adv"][sl], "truncated": cut > 0, "dropped_days": cut}

    snap = blk["unrealised_snapshot"]
    blk["totals"].update({
        "pnl_rolled_days": d["rolled_days"], "pnl_rolled_amount": _r(d["rolled_amt"]),
        "pnl_after_last_spot": _r(d["after_amt"]), "pnl_after_last_spot_count": d["after_n"],
        "n_days": n, "n_closing_days": sum(d["closing"]),
        "realised_plus_unrealised": (_r(meas_total + est_total + snap["amount"])
                                     if snap["available"] and snap["amount"] is not None else None)})

    all_idx = list(range(n))
    close_idx = [i for i in all_idx if d["closing"][i]]
    mixed = bool(ctx.include_est)

    def bk(key: str, idxs: list[int]) -> dict[str, Any]:
        return _bucket(key, idxs, pnl, d["meas"], d["est"], d["closing"], total_loss, cfg.spot_rel_min_bucket_days)

    big_up = [i for i in all_idx if ret[i] >= thr]
    big_dn = [i for i in all_idx if ret[i] <= -thr]
    rev_i = [i for i in all_idx if d["rev"][i]]
    big_any = [i for i in all_idx if d["big"][i]]
    other = [i for i in all_idx if not d["big"][i]]
    rel = {
        "all_days": corr_block(ret, pnl, cfg.spot_rel_min_days, cfg.spot_rel_ci_z, mixed),
        "closing_days": corr_block([ret[i] for i in close_idx], [pnl[i] for i in close_idx],
                                   cfg.spot_rel_min_closing_days, cfg.spot_rel_ci_z, mixed),
        "by_direction": [bk("up", [i for i in all_idx if ret[i] >= band and ret[i] > 0]),
                         bk("down", [i for i in all_idx if ret[i] <= -band and ret[i] < 0]),
                         bk("flat", [i for i in all_idx if not (ret[i] >= band and ret[i] > 0) and not (ret[i] <= -band and ret[i] < 0)])],
        "big_move": [bk("big_up", big_up), bk("big_down", big_dn), bk("reversal", rev_i), bk("other", other)],
        "big_any": bk("big_any", big_any),
        "expiry_days": [bk("expiry", [i for i in all_idx if d["exp"][i]]),
                        bk("other", [i for i in all_idx if not d["exp"][i]])]}
    al = _alignment(cfg, days)
    blk["relationship"] = rel
    blk["alignment"] = al
    blk["observations"] = _observations(cfg, u, rel, al)
    return blk


def spot_vs_pnl(ctx: Ctx, pnl_lines: list[PnlLine], unds: list[str],
                days: Optional[dict[str, list[SpotDay]]] = None) -> dict[str, Any]:
    """Per-underlying blocks (never summed across underlyings) plus the view-level info."""
    cfg = ctx.cfg
    days_by_u = days if days is not None else spot_days(ctx, unds)
    segs_by_u = _segments_by_und(ctx)
    blocks = [_block(ctx, u, days_by_u.get(u), segs_by_u.get(u, []), pnl_lines) for u in unds]
    info = _info(
        "How each underlying moved day by day against your daily realised P&L, whether your start-of-day "
        "book was positioned with or against the market, and how the two relate in this sample.",
        ["P&L is REALISED (measured) per closing day, gross of charges, FIFO-matched; expiry-held lots "
         "closed at spot-intrinsic are an ESTIMATE shown separately and counted only when the estimate "
         "toggle is on. Realised timing is not mark-to-market, so correlation and beta are a weak, lagged "
         "proxy; a near-zero value does not mean uncorrelated exposure.",
         "While positions are open the series understates the true P&L swings; open-position "
         "mark-to-market history is not available. The unrealised figure is ONE measured snapshot from "
         "the P&L sheet, never part of the daily series or the statistics.",
         "Beta is INR of daily realised P&L per +1% spot move and is confounded by position-size drift "
         "over the window. Negative beta means P&L tended to be higher on down days in this sample.",
         "Correlation, the significance flag and the Wilson interval assume independent days; consecutive "
         "days share the book and the P&L timing, so the true uncertainty is larger.",
         MULTI_NOTE,
         "Bias is the delta-sign proxy (long CE / short PE = +1, short CE / long PE = -1) x open units at "
         "the end of the previous day; it indicates direction, not magnitude (ESTIMATE).",
         "P&L booked on a date with no spot row is rolled forward to the next spot day; P&L after the "
         "last spot day is reported separately. Statistics use the full window; only the chart arrays "
         f"are capped at {cfg.spot_series_max_points} points (oldest days dropped).",
         "Big-move days use the market-turn threshold; flat/up/down use the flat band. Every statistic "
         "is withheld (insufficient_sample) below its configured minimum number of days."])
    return {"info": info, "underlyings": blocks, "delta1_note": DELTA1_NOTE}
