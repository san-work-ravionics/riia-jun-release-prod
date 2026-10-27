"""JarvisPageService — the read-only Jarvis page payloads A4–A6 (F44 P4, rev 1 B2/B4/A2, rev 2 N1/N2,
rev 3).

Composition only, over the request's in-memory MCP session (``mcp_client_dependency("jarvis")``):
every figure is a tool field, except the target path to date ``T`` (``core/goal_targets``, B2 —
arithmetic on the user's annual goal) and the engine gap ``return − T``.  **No DB write here**
(A11): the session / message rows are read through the Jarvis repos, and the only side effect of
a request is the ``mcp_calls`` log rows written by the MCP logger in its own session.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.core.goal_targets import target_to_date
from rita.interfaces.mcp_client import McpCallError, McpRequestClient
from rita.repositories.jarvis import JarvisMessageRepo, JarvisSessionRepo
from rita.schemas.goal_selection import GoalOut, RequiredReturnOut
from rita.schemas.jarvis import (
    AstaTraceOut,
    ChartMarkerOut,
    ChipOut,
    ClosePointOut,
    EngineRowOut,
    InstrumentEngineOut,
    InstrumentPageOut,
    InstrumentRowOut,
    JourneyOut,
    LevelOut,
    LevelsOut,
    LiveHoldingOut,
    MessageRowOut,
    PerfOut,
    PerformanceOut,
    PnlOut,
    PortfolioPageOut,
    RationaleInputOut,
    RationaleOut,
    RequiredOut,
    SeriesOut,
    SessionStateOut,
    SigmaLevelsOut,
    SleeveTraceOut,
    StateOut,
)
from rita.services import jarvis_templates as T
from rita.services.journey_service import plan_is_newer
from rita.services.user_portfolio_service import location_currency

TRACKED = ("tracking", "reselect_proposed", "back_to_plan")

ENGINE_LABELS = {"rita": "RITA model (DDQN)", "fno": "FnO σ levels — not a model",
                 "asta": "ASTA model (NIFTY only)", "held": "Your holdings"}


class PageError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _call(mcp: McpRequestClient, tool: str, args: dict[str, Any], model: type[BaseModel]):
    """Tool result as ``model``; ``not_found`` → None; any other error → ``PageError(unavailable)``
    for that one panel (the caller decides)."""
    try:
        res = mcp.call(tool, args)
    except McpCallError as exc:
        if exc.code == "not_found":
            return None
        raise PageError(exc.code, f"{tool}: {exc.code}") from exc
    return model.model_validate(res.structured)


def _try(mcp, tool, args, model):
    try:
        return _call(mcp, tool, args, model)
    except PageError:
        return None


def _open_mix(j: JourneyOut | None) -> list[tuple[str, int, str | None]]:
    """The mix the user holds per the journey (open segment, else tracking, else the selection)."""
    if j is None:
        return []
    seg = next((s for s in reversed(j.segments) if s.to is None), None)
    if seg is not None:
        return [(h.instrument_id, h.allocation_pct, h.tolerance) for h in seg.holdings]
    if j.tracking:
        return [(t.instrument_id, t.allocation_pct, t.tolerance) for t in j.tracking]
    if j.selection is not None:
        return [(h.instrument_id, h.allocation_pct, h.tolerance) for h in j.selection.holdings]
    return []


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


class JarvisPageService:
    def __init__(self, db: Session, mcp: McpRequestClient, user: Any) -> None:
        self._db = db
        self._mcp = mcp
        self._user = user

    # ── shared reads ───────────────────────────────────────────────────────────

    def _goal(self, location: str) -> GoalOut | None:
        return _try(self._mcp, "whatineed.get_goal", {"location": location}, GoalOut)

    def _journey(self, location: str) -> JourneyOut | None:
        return _try(self._mcp, "journey.get_current", {"location": location}, JourneyOut)

    def _trace(self, location: str, inst: str, tolerance: str | None = None, entry: date | None = None,
               since: date | None = None, detail: bool = False) -> SleeveTraceOut | None:
        args: dict[str, Any] = {"location": location, "instrument": inst, "detail": detail}
        if tolerance:
            args["tolerance"] = tolerance
        if entry:
            args["entry_date"] = entry.isoformat()
        if since:
            args["since"] = since.isoformat()
        return _try(self._mcp, "portfolio.sleeve_trace", args, SleeveTraceOut)

    @staticmethod
    def _entry(j: JourneyOut | None, inst: str) -> date | None:
        if j is None:
            return None
        return next((t.entry_date for t in j.tracking if t.instrument_id == inst), None)

    # ── A4 ─────────────────────────────────────────────────────────────────────

    def state(self, location: str) -> StateOut:
        from rita.core import journey_intents

        goal = self._goal(location)
        j = self._journey(location)
        stale = bool(j is not None and goal is not None and goal.saved and j.state != "no_goal"
                     and plan_is_newer(goal.plan_updated_at, j.plan_updated_at))
        sess = JarvisSessionRepo(self._db).latest_open(self._user.id, location)
        msgs = []
        if sess is not None:
            n = get_settings().jarvis.history_messages
            msgs = [MessageRowOut(message_id=m.message_id, role=m.role, text=m.text, intent=m.intent,
                                  template_id=m.template_id, created_at=m.created_at)
                    for m in JarvisMessageRepo(self._db).recent(sess.session_id, n)]
        live = []
        if j is not None and j.state in ("tracking", "reselect_proposed"):
            for inst, _pct, tau in _open_mix(j):
                tr = self._trace(location, inst, tau, self._entry(j, inst))
                if tr is None:
                    live.append(LiveHoldingOut(instrument_id=inst, status="unavailable"))
                elif tr.status != "ok":
                    live.append(LiveHoldingOut(instrument_id=inst, status="excluded"))
                else:
                    live.append(LiveHoldingOut(
                        instrument_id=inst, model_action=tr.today_action, invested_fraction=tr.invested_fraction,
                        sl_distance=tr.sl_distance, sl_hit=tr.sl_hit, next_reset=tr.next_reset, as_of=tr.as_of))
        return StateOut(
            location=location, location_name=T.LOCATION_NAMES[location], currency=location_currency(location),
            goal=goal, plan_stale=stale, journey=j,
            session=SessionStateOut(session_id=sess.session_id, status=sess.status,
                                    last_activity_at=sess.last_activity_at) if sess else None,
            messages=msgs, chips=[ChipOut(**c) for c in T.chips_for(j.state if j else None)],
            chat_model="ready" if journey_intents.is_ready() else "not_loaded", live_holdings=live)

    # ── A5 ─────────────────────────────────────────────────────────────────────

    def _pnl(self, location: str, **args: Any) -> PnlOut | None:
        body = {"location": location, **{k: v for k, v in args.items() if v is not None}}
        return _try(self._mcp, "portfolio.pnl", body, PnlOut)

    @staticmethod
    def _segments(j: JourneyOut) -> list[dict]:
        return [s.model_dump(mode="json", by_alias=True) for s in j.segments]

    @staticmethod
    def _preview_segment(j: JourneyOut) -> list[dict]:
        hs = [{"instrument_id": h.instrument_id, "allocation_pct": h.allocation_pct, "tolerance": h.tolerance}
              for h in j.selection.holdings]
        return [{"from": date(date.today().year, 1, 1).isoformat(), "to": None, "holdings": hs,
                 "cause": "preview"}]

    def portfolio(self, location: str) -> PortfolioPageOut:
        goal = self._goal(location)
        j = self._journey(location)
        r = (j.goal_return if j is not None and j.goal_return is not None
             else goal.goal_return if goal is not None and goal.saved else None)
        tracked = j is not None and j.state in TRACKED and bool(j.segments)
        s = j.plan_year_start if j is not None else None

        perf: PnlOut | None = None
        sleeves: PnlOut | None = None
        if tracked:
            perf = self._pnl(location, goal_return=r, year_start=_iso(s), segments=self._segments(j))
            sleeves = self._pnl(location, goal_return=r, source="model_sleeves", year_start=_iso(s),
                                segments=self._segments(j))
        else:
            perf = self._pnl(location, goal_return=r, source="saved")
            if j is not None and j.selection is not None and j.selection.holdings:
                sleeves = self._pnl(location, goal_return=r, source="model_sleeves", preview=True,
                                    segments=self._preview_segment(j))
                if perf is None:
                    perf = sleeves

        required = None
        if tracked and j.state == "tracking" and perf is not None and perf.ytd_return is not None \
                and perf.as_of is not None and r is not None:
            rr = _try(self._mcp, "portfolio.required_return", {
                "location": location, "goal_return": r, "ytd_return": perf.ytd_return,
                "as_of": perf.as_of.isoformat(), "year_start": perf.year_start.isoformat(),
                "reselections_used": j.reselect_count}, RequiredReturnOut)
            if rr is not None:
                required = RequiredOut(status=rr.status, reason=rr.reason, required_return=rr.required_return,
                                       effective_return=rr.effective_return,
                                       reselections_used=rr.reselections_used,
                                       max_reselections=rr.max_reselections)

        instruments, engines = self._grid(location, j, perf, sleeves, r)
        return PortfolioPageOut(
            location=location, currency=location_currency(location),
            as_of=perf.as_of if perf else None,
            pnl_source=perf.source if perf else "none",
            perf=PerfOut(**perf.model_dump(), pnl_source=perf.source) if perf else None,
            required=required, journey_state=j.state if j else None,
            instruments=instruments, engines=engines)

    def _grid(self, location: str, j: JourneyOut | None, perf: PnlOut | None, sleeves: PnlOut | None,
              r: float | None) -> tuple[list[InstrumentRowOut], list[EngineRowOut]]:
        held: dict[str, Any] = {}
        held_ret: dict[str, float | None] = {}
        if perf is not None and perf.money is not None:
            for h in perf.money.holdings:
                held[h.instrument_id] = h
            for h in perf.holdings:
                held_ret[h.instrument_id] = h.return_since
        mix = {inst: (pct, tau) for inst, pct, tau in _open_mix(j)}
        ids = list(dict.fromkeys([*held.keys(), *mix.keys()]))
        traces: dict[str, SleeveTraceOut | None] = {}
        astas: dict[str, AstaTraceOut | None] = {}
        rows = []
        for inst in ids:
            tau = mix.get(inst, (None, None))[1]
            tr = self._trace(location, inst, tau, self._entry(j, inst))
            traces[inst] = tr
            at = _try(self._mcp, "market.asta_trace", {"instrument": inst}, AstaTraceOut)
            astas[inst] = at
            h = held.get(inst)
            available = ["fno"]
            if tr is not None and tr.status == "ok":
                available.insert(0, "rita")
            if at is not None and at.status != "no_model":
                available.append("asta")
            ok = tr is not None and tr.status == "ok"
            rows.append(InstrumentRowOut(
                instrument_id=inst, held=h is not None, selected=inst in mix,
                allocation_pct=mix[inst][0] if inst in mix else next(
                    (x.allocation_pct for x in (perf.holdings if perf else []) if x.instrument_id == inst), None),
                shares=h.shares if h else None, last_close=(h.last_close if h else None) or (tr.last_close if ok else None),
                pnl=h.pnl if h else None, ret=held_ret.get(inst),
                model_action=tr.today_action if ok else None, sl_distance=tr.sl_distance if ok else None,
                sl_hit=tr.sl_hit if ok else None, engines_available=available))

        engines: list[EngineRowOut] = []
        ref = perf or sleeves
        s = ref.year_start if ref else None
        as_of = ref.as_of if ref else None
        ttd = target_to_date(r, s, as_of) if (r is not None and s and as_of) else None

        def pace(ret: float | None) -> tuple[float | None, bool | None]:
            if ret is None or ttd is None:
                return None, None
            return ret - ttd, ret >= ttd

        # RITA: the model sleeves of the held mix
        if sleeves is not None:
            gap, on = pace(sleeves.ytd_return)
            engines.append(EngineRowOut(engine="rita", label=ENGINE_LABELS["rita"], model_based=True,
                                        coverage=sleeves.coverage, return_since=sleeves.ytd_return,
                                        target_to_date=ttd, gap=gap, on_pace=on, status="ok",
                                        note="preview" if sleeves.source == "model_sleeves_preview" else None))
        else:
            st = "none" if not mix else "unavailable"
            engines.append(EngineRowOut(engine="rita", label=ENGINE_LABELS["rita"], model_based=True, status=st))
        # ASTA: instruments it covers, weighted by the mix
        covered = [(i, a) for i, a in astas.items() if a is not None and a.status != "no_model"]
        if covered:
            weights = {i: (mix[i][0] if i in mix else 0) / 100.0 for i in ids}
            tot_w = sum(weights.values()) or 1.0
            ok_rows = []
            status = "ok"
            for i, a in covered:
                if a.status != "ok":
                    status = a.status
                    continue
                at = _try(self._mcp, "market.asta_trace", {"instrument": i, "since": _iso(s)}, AstaTraceOut) if s else a
                ok_rows.append((i, at.return_since if at else None))
            if status == "ok" and ok_rows and all(x is not None for _i, x in ok_rows):
                cov = sum(weights.get(i, 0.0) for i, _x in ok_rows) / tot_w if tot_w else None
                wsum = sum(weights.get(i, 0.0) for i, _x in ok_rows)
                ret = (sum(weights.get(i, 0.0) * x for i, x in ok_rows) / wsum) if wsum else ok_rows[0][1]
                gap, on = pace(ret)
                engines.append(EngineRowOut(engine="asta", label=ENGINE_LABELS["asta"], model_based=True,
                                            coverage=cov, return_since=ret, target_to_date=ttd, gap=gap,
                                            on_pace=on, status="ok"))
            else:
                engines.append(EngineRowOut(engine="asta", label=ENGINE_LABELS["asta"], model_based=True,
                                            status=status if status != "ok" else "unavailable"))
        else:
            engines.append(EngineRowOut(engine="asta", label=ENGINE_LABELS["asta"], model_based=True,
                                        status="no_model"))
        engines.append(EngineRowOut(engine="fno", label=ENGINE_LABELS["fno"], model_based=False,
                                    status="levels_only", target_to_date=ttd))
        if perf is not None and perf.money is not None:
            gap, on = pace(perf.ytd_return)
            engines.append(EngineRowOut(engine="held", label=ENGINE_LABELS["held"], model_based=False,
                                        coverage=perf.coverage, return_since=perf.ytd_return,
                                        target_to_date=ttd, gap=gap, on_pace=on, status="ok"))
        return rows, engines

    # ── A6 ─────────────────────────────────────────────────────────────────────

    def instrument(self, location: str, instrument: str) -> InstrumentPageOut:
        from rita.services.goal_selection_service import GoalSelectionService

        inst = instrument.upper()
        if inst not in GoalSelectionService(self._db).universe(location):
            raise PageError("not_found", "unknown instrument")
        goal = self._goal(location)
        j = self._journey(location)
        r = (j.goal_return if j is not None and j.goal_return is not None
             else goal.goal_return if goal is not None and goal.saved else None)
        s = (j.plan_year_start if j is not None and j.plan_year_start else None) or date(date.today().year, 1, 1)
        tau = next((t for i, _p, t in _open_mix(j) if i == inst), None)
        engines = [self._rita(location, inst, tau, self._entry(j, inst), s, r),
                   self._fno(inst), self._asta(inst, s, r)]
        as_of = max((e.prices[-1].date for e in engines if e.prices), default=None)
        sig_ccy = next((e.method.get("currency") for e in engines
                        if isinstance(e.method, dict) and e.method.get("currency")), None)
        return InstrumentPageOut(instrument_id=inst, currency=sig_ccy, as_of=as_of, engines=engines)

    @staticmethod
    def _perf(ret: float | None, since: date | None, r: float | None, s: date | None,
              as_of: date | None) -> PerformanceOut | None:
        if ret is None:
            return None
        ttd = target_to_date(r, s, as_of) if (r is not None and s and as_of) else None
        return PerformanceOut(return_since=ret, since=since, target_to_date=ttd,
                              gap=None if ttd is None else ret - ttd)

    def _rita(self, location: str, inst: str, tau: str | None, entry: date | None, s: date | None,
              r: float | None) -> InstrumentEngineOut:
        tr = self._trace(location, inst, tau, entry, s, detail=True)
        base = dict(engine="rita", label=ENGINE_LABELS["rita"], model_based=True)
        if tr is None:
            return InstrumentEngineOut(status="unavailable", **base)
        if tr.status != "ok":
            return InstrumentEngineOut(status="excluded", method={"excluded_reason": tr.excluded_reason}, **base)
        d = tr.detail
        prices = [ClosePointOut(date=x, close=c) for x, c in zip(d.dates, d.close) if c is not None] if d else []
        markers = [ChartMarkerOut(date=m.date, kind=m.kind, close=m.close) for m in (d.markers if d else [])]
        entry_m = next((m for m in reversed(d.markers if d else []) if m.kind == "entry"), None)
        exit_m = next((m for m in reversed(d.markers if d else []) if m.kind == "exit"), None)
        invested = (tr.invested_fraction or 0.0) > 0
        levels = LevelsOut(
            entry=LevelOut(date=entry_m.date, value=entry_m.close, basis="DDQN action change to invested (model)")
            if entry_m and entry_m.close is not None else None,
            exit=LevelOut(date=exit_m.date, value=exit_m.close, basis="DDQN action change to cash (model)")
            if exit_m and exit_m.close is not None and not invested else None,
            stop_loss=LevelOut(value=tr.sl_level, basis="sleeve drawdown at hard_mdd_limit from peak "
                               "(training limit, not a model output)") if tr.sl_level is not None else None,
            target=None)
        return InstrumentEngineOut(
            status="ok", prices=prices, markers=markers, levels=levels,
            series=SeriesOut(sleeve_value=d.sleeve_value if d else [], sl_line=d.sl_line if d else []),
            episode_starts=d.episode_starts if d else [], rationale=d.rationale if d else None,
            performance=self._perf(tr.return_since, tr.since, r, s, tr.as_of),
            method=tr.method.model_dump(), tolerance_rule=tr.tolerance_rule, **base)

    def _fno(self, inst: str) -> InstrumentEngineOut:
        sg = _try(self._mcp, "fno.sigma_levels", {"instrument": inst}, SigmaLevelsOut)
        base = dict(engine="fno", label=ENGINE_LABELS["fno"], model_based=False)
        if sg is None:
            return InstrumentEngineOut(status="unavailable", **base)
        if sg.status != "ok":
            return InstrumentEngineOut(status=sg.status, prices=sg.closes, **base)
        by_month = {m.month: m for m in sg.monthly}
        upper = [by_month[c.date.strftime("%Y-%m")].plus_1sigma if c.date.strftime("%Y-%m") in by_month else None
                 for c in sg.closes]
        lower = [by_month[c.date.strftime("%Y-%m")].minus_1sigma if c.date.strftime("%Y-%m") in by_month else None
                 for c in sg.closes]
        lv = sg.levels
        levels = LevelsOut(
            entry=LevelOut(date=sg.anchor_date, value=lv.entry, basis="anchor: last close (not a model)"),
            exit=None,
            stop_loss=LevelOut(value=lv.minus_1sigma, basis="−1σ monthly (not a model)"),
            target=LevelOut(value=lv.plus_1sigma, basis="+1σ monthly (not a model)"))
        rationale = RationaleOut(
            date=sg.as_of, action=None, prev_action=None,
            inputs=[RationaleInputOut(name="ann_vol_pct", raw=sg.ann_vol_pct),
                    RationaleInputOut(name="lookback_returns", raw=sg.lookback_returns),
                    RationaleInputOut(name="monthly_sigma_pct", raw=sg.monthly_sigma_pct),
                    RationaleInputOut(name="anchor_close", raw=sg.anchor_close)],
            state=[{"name": "anchor_date", "value": _iso(sg.anchor_date)}], note=sg.method)
        return InstrumentEngineOut(status="levels_only", prices=sg.closes, levels=levels,
                                   series=SeriesOut(band_upper=upper, band_lower=lower), rationale=rationale,
                                   method={"text": sg.method, "currency": sg.currency,
                                           "lookback_returns": sg.lookback_returns}, **base)

    def _asta(self, inst: str, s: date | None, r: float | None) -> InstrumentEngineOut:
        args: dict[str, Any] = {"instrument": inst, "detail": True}
        if s:
            args["since"] = s.isoformat()
        at = _try(self._mcp, "market.asta_trace", args, AstaTraceOut)
        base = dict(engine="asta", label=ENGINE_LABELS["asta"], model_based=True)
        if at is None:
            return InstrumentEngineOut(status="unavailable", **base)
        d = at.detail
        prices = [ClosePointOut(date=x, close=c) for x, c in zip(d.dates, d.close)] if d else []
        if at.status not in ("ok", "no_recorded_window"):
            return InstrumentEngineOut(status=at.status, method=at.method.model_dump(),
                                       asta=at.model_copy(update={"detail": None}), **base)
        markers = [ChartMarkerOut(date=m.date, kind=m.kind, close=m.close) for m in (d.markers if d else [])]
        entry_m = next((m for m in reversed(d.markers if d else []) if m.kind == "entry"), None)
        exit_m = next((m for m in reversed(d.markers if d else []) if m.kind == "exit"), None)
        invested = at.today_action in ("half", "full", "hedged")
        sig = at.last_signal
        levels = LevelsOut(
            entry=LevelOut(date=entry_m.date, value=entry_m.close, basis="ASTA DDQN action change to invested (model)")
            if entry_m and entry_m.close is not None else None,
            exit=LevelOut(date=exit_m.date, value=exit_m.close, basis="ASTA DDQN action change to cash (model)")
            if exit_m and exit_m.close is not None and not invested else None,
            stop_loss=LevelOut(date=sig.date, value=sig.stop_loss, basis="ASTA labeller setup level (rule, not a model)")
            if sig and sig.stop_loss is not None else None,
            target=LevelOut(date=sig.date, value=sig.target, basis="ASTA labeller setup level (rule, not a model)")
            if sig and sig.target is not None else None)
        perf = self._perf(at.return_since, at.since, r, s, at.as_of) if at.status == "ok" else None
        return InstrumentEngineOut(status=at.status, prices=prices, markers=markers, levels=levels,
                                   rationale=d.rationale if d else None, performance=perf,
                                   method=at.method.model_dump(),
                                   asta=at.model_copy(update={"detail": None}), **base)
