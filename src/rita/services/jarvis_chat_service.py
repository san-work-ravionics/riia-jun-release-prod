"""JarvisChatService — the Jarvis chat orchestrator (F44 P4 A1–A3; design §2.2 / §3, rev 1–3).

One message: owner-checked session → MiniLM journey intent (``core/journey_intents``) → slots
(``core/journey_slots``) → the state's tool plan over the in-memory MCP client (one session per
request, the caller's identity) → a versioned template (``jarvis_templates``) → the user and
assistant messages + session counters.

Rules:
- every number in a reply is a tool field, formatted by ``jarvis_templates`` (golden-tested);
- the state comes from ``journey.get_current`` (the stored row), never from the client;
- the only journey write is ``journey.save`` (an MCP call, so it is logged in ``mcp_calls``);
- low confidence → ``fallback.low_confidence`` with the state's chips and **no tool call**;
- personal data (goal figures, message text) is never logged — counts and ids only.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.interfaces.mcp_client import McpCallError, McpRequestClient
from rita.models.jarvis import JarvisMessageModel, JarvisSessionModel
from rita.repositories.jarvis import JarvisMessageRepo, JarvisSessionRepo
from rita.schemas.goal_selection import GoalOut, GoalSelectionOut, ModelRunsOut, RequiredReturnOut
from rita.schemas.jarvis import (
    ChipOut,
    JourneyOut,
    MessageIn,
    MessageOut,
    PnlOut,
    ReplyOut,
    SessionOut,
    SleeveTraceOut,
    ToolCallOut,
    WarmupOut,
)
from rita.schemas.user_hedge_plan import HedgePlanOut
from rita.services import jarvis_templates as T
from rita.services.journey_service import plan_is_newer

log = structlog.get_logger(__name__)

ACCEPTED: dict[str, frozenset[str]] = {
    "none": frozenset({"take_goal", "change_goal", "show_hedge", "help"}),
    "no_goal": frozenset({"take_goal", "change_goal", "show_hedge", "help"}),
    "goal_loaded": frozenset({"take_goal", "build_selection", "change_goal", "show_hedge", "help"}),
    "selected": frozenset({"take_goal", "build_selection", "why_this_pick", "cant_reach", "track",
                           "change_goal", "show_hedge", "help"}),
    "cant_reach": frozenset({"take_goal", "build_selection", "why_this_pick", "cant_reach",
                             "change_goal", "show_hedge", "help"}),
    "tracking": frozenset({"take_goal", "why_this_pick", "progress", "what_if_sl", "track",
                           "show_hedge", "change_goal", "help"}),
    "reselect_proposed": frozenset({"confirm", "decline", "why_this_pick", "progress", "what_if_sl",
                                    "help"}),
    "back_to_plan": frozenset({"take_goal", "change_goal", "show_hedge", "help"}),
}


class JarvisChatError(Exception):
    """``not_found`` (session) | ``unavailable`` (chat model)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _ToolDown(Exception):
    def __init__(self, tool: str) -> None:
        super().__init__(tool)
        self.tool = tool


class _Refused(Exception):
    """A ``journey.save`` refused by the stored state (edge 20) → the state prompt."""


@dataclass
class _Reply:
    key: str
    slots: dict[str, str] = field(default_factory=dict)
    cards: list[dict] = field(default_factory=list)
    prefix: str | None = None
    extra: list[tuple[str, dict[str, str]]] = field(default_factory=list)   # extra template lines


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def warmup() -> WarmupOut:
    """A1: load MiniLM (shared singleton) and build the journey seed index."""
    from rita.core import journey_intents

    try:
        n = journey_intents.build_index()
    except Exception as exc:  # noqa: BLE001 — model path missing / load failure
        log.warning("jarvis.warmup_failed", error=type(exc).__name__)
        raise JarvisChatError("unavailable", "chat model unavailable") from exc
    return WarmupOut(status="ready", intents=n)


class _Turn:
    """One message's tool calls (all over the request's MCP session)."""

    def __init__(self, mcp: McpRequestClient, location: str) -> None:
        self.mcp = mcp
        self.location = location
        self.calls: list[ToolCallOut] = []
        self.journey: JourneyOut | None = None
        self.last_error = ""
        self._goal: GoalOut | None = None

    def call(self, tool: str, args: dict[str, Any], model: type[BaseModel] | None = None,
             *, missing_ok: bool = True, refuse_ok: bool = False):
        try:
            res = self.mcp.call(tool, args)
        except McpCallError as exc:
            status = "not_found" if exc.code == "not_found" else "error"
            self.last_error = exc.message
            self.calls.append(ToolCallOut(tool=tool, mcp_call_id=exc.call_id, status=status))
            if exc.code == "not_found" and missing_ok:
                return None if model is not None else exc
            if exc.code == "invalid_input" and refuse_ok:
                raise _Refused(exc.message) from exc
            raise _ToolDown(tool) from exc
        self.calls.append(ToolCallOut(tool=tool, mcp_call_id=res.call_id, status="ok"))
        return model.model_validate(res.structured) if model is not None else res.structured

    # helpers ------------------------------------------------------------------

    def get_journey(self) -> JourneyOut | None:
        self.journey = self.call("journey.get_current", {"location": self.location}, JourneyOut)
        return self.journey

    def goal(self) -> GoalOut:
        if self._goal is None:
            g = self.call("whatineed.get_goal", {"location": self.location}, GoalOut, missing_ok=False)
            self._goal = g
        return self._goal

    def save(self, event: str, **body: Any) -> JourneyOut:
        args: dict[str, Any] = {"location": self.location, "event": event}
        if self.journey is not None and event != "start":
            args["expected_version"] = self.journey.version
        for k, v in body.items():
            if v is None:
                continue
            args[k] = v.model_dump(mode="json") if isinstance(v, BaseModel) else v
        self.journey = self.call("journey.save", args, JourneyOut, missing_ok=False, refuse_ok=True)
        return self.journey


def _state(j: JourneyOut | None) -> str:
    return "none" if j is None else j.state


def _goal_card(g: GoalOut) -> dict:
    return {"kind": "goal", "data": {"location": g.location, "currency": g.currency,
                                     "goal_return": g.goal_return, "horizon_years": g.horizon_years,
                                     "goal_value": g.goal_value,
                                     "plan_updated_at": g.plan_updated_at.isoformat() if g.plan_updated_at else None}}


def _holdings_card(hs) -> list[dict]:
    return [{"instrument_id": h.instrument_id, "allocation_pct": h.allocation_pct,
             "model_action": h.model_action} for h in hs]


def _selection_card(s: GoalSelectionOut) -> dict:
    return {"kind": "selection", "data": {
        "location": s.location, "currency": s.currency, "target_return": s.target_return,
        "meets_goal": s.meets_goal, "tolerance": s.tolerance, "n_tolerances": len(s.ladder),
        "holdings": _holdings_card(s.holdings), "fit_return": s.fit_return,
        "test_return": s.test_return, "test_mdd": s.test_mdd, "gap": s.gap,
        "test_window": {"start": s.test_window.start.isoformat(), "end": s.test_window.end.isoformat()},
        "method_weights": s.method.weights}}


def _closest_card(s: GoalSelectionOut) -> dict:
    c = s.closest
    return {"kind": "closest", "data": {
        "target_return": s.target_return, "holdings": _holdings_card(c.holdings) if c else [],
        "fit_return": c.fit_return if c else None, "test_return": c.test_return if c else None,
        "gap": c.gap if c else None, "cap_fit": s.cap_fit, "cap_test": s.cap_test}}


def _excluded_card(rows: list[tuple[str, str]]) -> dict:
    return {"kind": "excluded", "data": {"rows": [{"instrument_id": i, "reason": r} for i, r in rows]}}


def _excluded_text(rows: list[tuple[str, str]]) -> str:
    return ", ".join(f"{i} ({T.REASON_LABELS.get(r, r)})" for i, r in rows)


def _parse_excluded(message: str) -> list[tuple[str, str]]:
    """``… (excluded: NVIDIA:no_model, ATO:retrain_needed)`` → [(id, reason)] (tool message)."""
    if "excluded:" not in message:
        return []
    body = message.split("excluded:", 1)[1].rstrip(") ").strip()
    out = []
    for part in body.split(","):
        if ":" in part:
            i, r = part.strip().split(":", 1)
            out.append((i.strip(), r.strip()))
    return out


def _open_holdings(j: JourneyOut) -> list[tuple[str, int, str]]:
    """The current segment's mix ``[(instrument, allocation_pct, tolerance)]`` (else tracking)."""
    open_seg = next((s for s in reversed(j.segments) if s.to is None), None)
    if open_seg is not None:
        return [(h.instrument_id, h.allocation_pct, h.tolerance) for h in open_seg.holdings]
    return [(t.instrument_id, t.allocation_pct, t.tolerance) for t in j.tracking]


class JarvisChatService:
    def __init__(self, db: Session, mcp: McpRequestClient, user: Any) -> None:
        self._db = db
        self._mcp = mcp
        self._user = user
        self._sessions = JarvisSessionRepo(db)
        self._messages = JarvisMessageRepo(db)
        self._cfg = get_settings().jarvis

    # ── A2 ─────────────────────────────────────────────────────────────────────

    def open_session(self, location: str) -> SessionOut:
        now = _utcnow()
        row = self._sessions.latest_open(self._user.id, location)
        if row is not None:
            last = _aware(row.last_activity_at) or now
            if now - last <= timedelta(minutes=self._cfg.session_idle_minutes):
                row.last_activity_at = now
                self._db.commit()
                return SessionOut(session_id=row.session_id, started_at=_aware(row.started_at), reused=True)
            row.status = "closed"
        new = JarvisSessionModel(session_id=str(uuid.uuid4()), user_id=self._user.id, location=location,
                                 provider="minilm", message_count=0, started_at=now,
                                 last_activity_at=now, status="open")
        self._sessions.insert(new)
        self._db.commit()
        log.info("jarvis.session_opened", session_id=new.session_id)
        return SessionOut(session_id=new.session_id, started_at=now, reused=False)

    # ── A3 ─────────────────────────────────────────────────────────────────────

    def _owned_session(self, session_id: str) -> JarvisSessionModel:
        row = self._sessions.get(session_id)
        if row is None or row.user_id != self._user.id:
            raise JarvisChatError("not_found", "session not found")
        return row

    def message(self, inp: MessageIn) -> MessageOut:
        from rita.core.journey_intents import classify_journey
        from rita.core.journey_slots import parse_slots
        from rita.services.goal_selection_service import GoalSelectionError, GoalSelectionService
        from rita.services.journey_service import JourneyService

        session = self._owned_session(inp.session_id)
        try:
            res = classify_journey(inp.text, self._cfg.intent_threshold)
        except Exception as exc:  # noqa: BLE001
            log.warning("jarvis.classify_failed", error=type(exc).__name__)
            raise JarvisChatError("unavailable", "chat model unavailable") from exc

        try:
            universe = GoalSelectionService(self._db).universe(inp.location)
        except GoalSelectionError:
            universe = []
        slots = parse_slots(inp.text, universe)
        location = slots.location or inp.location
        if slots.location and slots.location != inp.location:
            try:
                universe = GoalSelectionService(self._db).universe(location)
            except GoalSelectionError:
                universe = []
            slots = parse_slots(inp.text, universe)
            location = slots.location or inp.location

        intent = res.intent
        low = res.low_confidence
        turn = _Turn(self._mcp, location)

        if low:
            # never guess, never call a tool: the state for the chips is read directly
            j = JourneyService(self._db).get_current(self._user.id, location)
            turn.journey = j
            if j is not None and j.state == "reselect_proposed" and slots.yes_no:
                intent, low = ("confirm" if slots.yes_no == "yes" else "decline"), False
        if low:
            reply = _Reply("fallback.low_confidence")
        else:
            try:
                reply = self._dispatch(turn, intent, slots)
            except _ToolDown as exc:
                reply = _Reply("error.unavailable", {"tool": exc.tool})
            except _Refused:
                try:
                    turn.get_journey()
                except _ToolDown:
                    pass
                reply = _Reply(f"state_prompt.{_state(turn.journey)}")

        text, template_id = self._text(reply)
        state = _state(turn.journey)
        chips = [ChipOut(**c) for c in T.chips_for(state)]
        out_reply = ReplyOut(text=text, template_id=template_id, intent=None if low else intent,
                             confidence=round(res.confidence, 4), low_confidence=low, chips=chips,
                             cards=reply.cards, tool_calls=turn.calls)

        now = _utcnow()
        self._messages.append(JarvisMessageModel(
            message_id=str(uuid.uuid4()), session_id=session.session_id, role="user", text=inp.text,
            intent=intent, confidence=res.confidence, slots=slots.to_dict(), provider="minilm",
            created_at=now))
        self._messages.append(JarvisMessageModel(
            message_id=str(uuid.uuid4()), session_id=session.session_id, role="assistant", text=text,
            intent=None if low else intent, template_id=template_id, provider="minilm",
            tool_calls=[c.model_dump() for c in turn.calls], created_at=now + timedelta(microseconds=1)))
        session.message_count = int(session.message_count or 0) + 2
        session.last_activity_at = now
        if turn.journey is not None:
            session.journey_id = turn.journey.journey_id
        self._db.commit()
        log.info("jarvis.message", session_id=session.session_id, intent=out_reply.intent,
                 template=template_id, tool_calls=len(turn.calls), state=state)
        return MessageOut(session_id=session.session_id, reply=out_reply, journey=turn.journey)

    @staticmethod
    def _text(reply: _Reply) -> tuple[str, str]:
        text, tid = T.render(reply.key, **reply.slots)
        lines = [text] + [T.render(k, **s)[0] for k, s in reply.extra]
        if reply.prefix:
            lines.insert(0, reply.prefix)
        return " ".join(lines), tid

    # ── intent plans ───────────────────────────────────────────────────────────

    def _dispatch(self, t: _Turn, intent: str, slots) -> _Reply:
        j = t.get_journey()
        state = _state(j)
        prefix = None
        if intent != "take_goal" and j is not None and state != "no_goal":
            g = t.goal()
            if g.saved and plan_is_newer(g.plan_updated_at, j.plan_updated_at):
                prefix = T.render("notice.plan_changed", plan_updated_at=T.fmt_date(g.plan_updated_at))[0]
        if intent not in ACCEPTED[state]:
            r = _Reply(f"state_prompt.{state}")
        else:
            r = getattr(self, f"_i_{intent}")(t, slots)
        if prefix and r.prefix is None:
            r.prefix = prefix
        return r

    # take_goal / change_goal -----------------------------------------------------

    def _loaded(self, g: GoalOut) -> _Reply:
        return _Reply("take_goal.loaded", {
            "location": T.LOCATION_NAMES.get(g.location, g.location), "goal_return": T.fmt_rate(g.goal_return),
            "horizon": T.fmt_num(g.horizon_years), "goal_value": T.fmt_money(g.currency, g.goal_value)},
            cards=[_goal_card(g)])

    def _i_take_goal(self, t: _Turn, _slots) -> _Reply:
        g = t.goal()
        j = t.journey
        loc = T.LOCATION_NAMES.get(g.location, g.location)
        goal_body = {"saved": g.saved, "plan_updated_at": g.plan_updated_at.isoformat() if g.plan_updated_at else None,
                     "goal_return": g.goal_return, "horizon_years": g.horizon_years, "goal_value": g.goal_value}
        if not g.saved:
            if j is None:
                t.save("start", goal=goal_body)
            return _Reply("take_goal.no_plan", {"location": loc})
        if j is None:
            t.save("start", goal=goal_body)
            return self._loaded(g)
        if plan_is_newer(g.plan_updated_at, j.plan_updated_at):
            t.save("start", goal=goal_body)
            r = self._loaded(g)
            r.prefix = T.render("notice.plan_changed", plan_updated_at=T.fmt_date(g.plan_updated_at))[0]
            return r
        if j.state == "goal_loaded":
            return self._loaded(g)
        return _Reply("take_goal.same_plan", {"plan_updated_at": T.fmt_date(g.plan_updated_at)})

    def _i_change_goal(self, t: _Turn, _slots) -> _Reply:
        g = t.goal()
        if not g.saved:
            return _Reply("take_goal.no_plan", {"location": T.LOCATION_NAMES.get(g.location, g.location)})
        return _Reply("change_goal.info", {"goal_return": T.fmt_rate(g.goal_return)}, cards=[_goal_card(g)])

    # build / why / cant_reach ---------------------------------------------------

    def _i_build_selection(self, t: _Turn, _slots) -> _Reply:
        j = t.journey
        loc = T.LOCATION_NAMES.get(t.location, t.location)
        res = t.call("portfolio.select_for_goal", {"location": t.location, "target_return": j.goal_return},
                     GoalSelectionOut, missing_ok=True)
        if res is None:
            rows = _parse_excluded(t.last_error)
            return _Reply("build.none_eligible", {"location": loc, "excluded": _excluded_text(rows) or "—"},
                          cards=[_excluded_card(rows)] if rows else [])
        t.save("select", selection=res)
        return self._selection_reply(res, loc)

    def _selection_reply(self, s: GoalSelectionOut, loc: str) -> _Reply:
        cards = []
        excl = [(e.instrument_id, e.reason) for e in s.excluded]
        if s.holdings:
            cards.append(_selection_card(s))
            if s.meets_goal:
                r = _Reply("build.meets", {
                    "target": T.fmt_rate(s.target_return), "location": loc, "mix": T.fmt_mix(s.holdings),
                    "test_start": T.fmt_date(s.test_window.start), "as_of": T.fmt_date(s.as_of),
                    "test_return": T.fmt_rate(s.test_return), "test_mdd": T.fmt_rate(s.test_mdd)})
            else:
                r = _Reply("build.test_short", {
                    "target": T.fmt_rate(s.target_return), "fit_start": T.fmt_date(s.fit_window.start),
                    "fit_end": T.fmt_date(s.fit_window.end), "fit_return": T.fmt_rate(s.fit_return),
                    "test_return": T.fmt_rate(s.test_return), "gap": T.fmt_rate(s.gap),
                    "mix": T.fmt_mix(s.holdings)})
        else:
            cards.append(_closest_card(s))
            c = s.closest
            r = _Reply("build.cant_reach", {
                "target": T.fmt_rate(s.target_return), "location": loc,
                "mix": T.fmt_mix(c.holdings) if c else "—",
                "fit_return": T.fmt_rate(c.fit_return if c else None),
                "test_return": T.fmt_rate(c.test_return if c else None), "cap_fit": T.fmt_rate(s.cap_fit)})
        if excl:
            cards.append(_excluded_card(excl))
        r.cards = cards
        return r

    def _i_cant_reach(self, t: _Turn, _slots) -> _Reply:
        s = t.journey.selection
        if s is None:
            return _Reply(f"state_prompt.{t.journey.state}")
        return self._selection_reply(s, T.LOCATION_NAMES.get(t.location, t.location))

    def _i_why_this_pick(self, t: _Turn, slots) -> _Reply:
        j = t.journey
        s = j.selection
        if j.state == "reselect_proposed" and j.proposal is not None and j.proposal.proposal is not None:
            s = j.proposal.proposal
        if s is None:
            return _Reply(f"state_prompt.{j.state}")
        runs = t.call("portfolio.model_runs", {"location": t.location}, ModelRunsOut, missing_ok=False)
        holdings = s.holdings or (s.closest.holdings if s.closest else [])
        if slots.instruments:
            holdings = [h for h in holdings if h.instrument_id in slots.instruments] or holdings
        by_inst = {i.instrument_id: i for i in runs.instruments}
        tau = s.tolerance or (s.closest.tolerance if s.closest else None)
        rows, extra = [], []
        for h in holdings:
            ir = by_inst.get(h.instrument_id)
            run = next((r for r in ir.runs if r.tolerance == (tau or h.tolerance)), None) if ir else None
            rows.append({"instrument_id": h.instrument_id, "allocation_pct": h.allocation_pct,
                         "fit_return": run.fit.ann_return if run else None,
                         "test_return": run.test.ann_return if run else None,
                         "test_mdd": run.test.mdd if run else None,
                         "today_action": run.today_action if run else None})
            extra.append(("why.line", {
                "instrument": h.instrument_id, "allocation": T.fmt_num(h.allocation_pct),
                "fit_return": T.fmt_rate(rows[-1]["fit_return"]), "test_return": T.fmt_rate(rows[-1]["test_return"]),
                "test_mdd": T.fmt_rate(rows[-1]["test_mdd"]),
                "action": T.ACTION_LABELS.get(rows[-1]["today_action"] or "", "n/a").lower()}))
        excl = [(e.instrument_id, e.reason) for e in runs.excluded]
        if excl:
            extra.append(("why.excluded", {"list": _excluded_text(excl)}))
        card = {"kind": "why", "data": {"tolerance": tau, "n_tolerances": len(s.ladder), "rows": rows,
                                        "excluded": [{"instrument_id": i, "reason": r} for i, r in excl]}}
        return _Reply("why.mix", {"n_tolerances": T.fmt_num(len(s.ladder)), "tolerance": tau or "n/a",
                                  "target": T.fmt_rate(s.target_return)}, cards=[card], extra=extra)

    # track / confirm ------------------------------------------------------------

    def _trace(self, t: _Turn, inst: str, tolerance: str | None, **kw: Any) -> SleeveTraceOut:
        args: dict[str, Any] = {"location": t.location, "instrument": inst}
        if tolerance:
            args["tolerance"] = tolerance
        for k, v in kw.items():
            if v is not None:
                args[k] = v.isoformat() if isinstance(v, date) else v
        return t.call("portfolio.sleeve_trace", args, SleeveTraceOut, missing_ok=False)

    def _tracking_entries(self, t: _Turn, s: GoalSelectionOut) -> tuple[list[dict], list[SleeveTraceOut]]:
        entries, traces = [], []
        for h in s.holdings:
            tr = self._trace(t, h.instrument_id, h.tolerance)
            traces.append(tr)
            entries.append({
                "instrument_id": h.instrument_id, "allocation_pct": h.allocation_pct, "tolerance": h.tolerance,
                "entry_date": (tr.as_of or s.as_of).isoformat(), "entry_close": tr.last_close,
                "sl_drawdown_limit": h.sl_drawdown_limit, "episode_start": h.episode_start.isoformat(),
                "episode_length": h.episode_length, "model_sha12": h.model_sha12})
        return entries, traces

    @staticmethod
    def _track_reply(entries: list[dict], traces: list[SleeveTraceOut]) -> _Reply:
        entry = min(e["entry_date"] for e in entries)
        resets = [tr.next_reset for tr in traces if tr.next_reset is not None]
        limit = entries[0]["sl_drawdown_limit"]
        card = {"kind": "tracking", "data": {
            "entry_date": entry, "sl_drawdown_limit": limit,
            "next_reset": min(resets).isoformat() if resets else None,
            "holdings": [{"instrument_id": e["instrument_id"], "entry_close": e["entry_close"],
                          "today_action": tr.today_action} for e, tr in zip(entries, traces)]}}
        return _Reply("track.started", {"entry_date": T.fmt_date(entry), "limit": T.fmt_rate(abs(limit)),
                                        "next_reset": T.fmt_date(min(resets) if resets else None)},
                      cards=[card])

    def _i_track(self, t: _Turn, _slots) -> _Reply:
        j = t.journey
        if j.state == "tracking":       # re-show the levels; no transition
            traces = [self._trace(t, e.instrument_id, e.tolerance, entry_date=e.entry_date) for e in j.tracking]
            entries = [e.model_dump(mode="json") for e in j.tracking]
            return self._track_reply(entries, traces)
        s = j.selection
        if s is None or not s.holdings:
            return _Reply(f"state_prompt.{j.state}")
        entries, traces = self._tracking_entries(t, s)
        as_of = max(e["entry_date"] for e in entries)
        t.save("track", tracking=entries, as_of=as_of)
        return self._track_reply(entries, traces)

    def _i_confirm(self, t: _Turn, _slots) -> _Reply:
        j = t.journey
        p = j.proposal
        if p is None or p.proposal is None or not p.proposal.holdings:
            return _Reply(f"state_prompt.{j.state}")
        entries, _traces = self._tracking_entries(t, p.proposal)
        t.save("accept", tracking=entries, as_of=max(e["entry_date"] for e in entries))
        return _Reply("confirm.accepted", {"mix": T.fmt_mix(p.proposal.holdings),
                                           "effective": T.fmt_rate(p.effective_return)})

    def _i_decline(self, t: _Turn, _slots) -> _Reply:
        j = t.save("decline")
        return _Reply("decline.kept", {"n": T.fmt_num(j.reselect_count), "max": T.fmt_num(j.max_reselections)})

    # progress / what-if ---------------------------------------------------------

    def _ytd(self, t: _Turn) -> tuple[PnlOut | None, float | None, date | None, date | None, str]:
        """``(pnl, ytd, as_of, year_start, source)`` from ``portfolio.pnl`` (saved / segments path).
        No pnl → no ytd (CR-2: summing the open segment alone would drop the earlier segments, rev 2 N1)."""
        j = t.journey
        args: dict[str, Any] = {"location": t.location, "goal_return": j.goal_return}
        if j.plan_year_start is not None:
            args["year_start"] = j.plan_year_start.isoformat()
        if j.segments:
            args["segments"] = [s.model_dump(mode="json", by_alias=True) for s in j.segments]
        p = t.call("portfolio.pnl", args, PnlOut, missing_ok=True)
        if p is not None:
            return p, p.ytd_return, p.as_of, p.year_start, p.source
        return None, None, None, j.plan_year_start, "model_sleeves"

    def _required(self, t: _Turn, ytd: float, as_of: date, year_start: date | None) -> RequiredReturnOut:
        j = t.journey
        args: dict[str, Any] = {"location": t.location, "goal_return": j.goal_return, "ytd_return": ytd,
                                "as_of": as_of.isoformat(), "reselections_used": j.reselect_count}
        if year_start is not None:
            args["year_start"] = year_start.isoformat()
        return t.call("portfolio.required_return", args, RequiredReturnOut, missing_ok=False)

    @staticmethod
    def _progress_card(source: str, as_of, year_start, ytd, ttd, rr: RequiredReturnOut | None) -> dict:
        return {"kind": "progress", "data": {
            "source": source if source in ("saved", "model_sleeves", "mixed") else "model_sleeves",
            "as_of": as_of.isoformat() if as_of else None, "year_start": year_start.isoformat(),
            "ytd_return": ytd, "target_to_date": ttd,
            "required_return": rr.required_return if rr else None,
            "status": rr.status if rr else None, "reason": rr.reason if rr else None}}

    @staticmethod
    def _proposal_reply(j: JourneyOut, rr: RequiredReturnOut) -> _Reply:
        prop = rr.proposal
        card = {"kind": "proposal", "data": {
            "required_return": rr.required_return, "effective_return": rr.effective_return,
            "holdings": _holdings_card(prop.holdings) if prop else [],
            "test_return": prop.test_return if prop else None,
            "reselections_next": rr.reselections_next, "max_reselections": rr.max_reselections}}
        return _Reply("progress.reselect", {
            "ytd": T.fmt_rate(rr.ytd_return), "year_start": T.fmt_date(j.plan_year_start),
            "goal_return": T.fmt_rate(rr.goal_return), "required": T.fmt_rate(rr.required_return),
            "mix": T.fmt_mix(prop.holdings) if prop else "—",
            "test_return": T.fmt_rate(prop.test_return if prop else None),
            "n": T.fmt_num(rr.reselections_next), "max": T.fmt_num(rr.max_reselections)}, cards=[card])

    def _i_progress(self, t: _Turn, _slots) -> _Reply:
        j = t.journey
        if j.state == "reselect_proposed" and j.proposal is not None:
            return self._proposal_reply(j, j.proposal)
        pnl, ytd, as_of, ys, source = self._ytd(t)
        if ytd is None or as_of is None or (pnl is not None and len(pnl.series) < 2):
            entry = (pnl.year_start if pnl else None) or (j.tracking[0].entry_date if j.tracking else None)
            return _Reply("progress.no_data", {"entry_date": T.fmt_date(entry)})
        rr = self._required(t, ytd, as_of, ys)
        card = self._progress_card(source, as_of, ys, rr.ytd_return, pnl.target_to_date if pnl else None, rr)
        if rr.status == "on_track":
            return _Reply("progress.on_track", {
                "source": T.SOURCE_LABELS.get(source, T.SOURCE_LABELS["model_sleeves"]),
                "ytd": T.fmt_rate(rr.ytd_return), "year_start": T.fmt_date(pnl.year_start if pnl else ys),
                "goal_return": T.fmt_rate(rr.goal_return),
                "target_to_date": T.fmt_rate(pnl.target_to_date if pnl else None),
                "required": T.fmt_rate(rr.required_return)}, cards=[card])
        if rr.status == "reselect_proposed":
            hit = False
            for inst, _pct, tau in _open_holdings(j):
                entry = next((e.entry_date for e in j.tracking if e.instrument_id == inst), None)
                if self._trace(t, inst, tau, entry_date=entry).sl_hit:
                    hit = True
            j2 = t.save("propose", proposal=rr, trigger="sl_hit" if hit else "behind_target")
            r = self._proposal_reply(j2, rr)
            r.cards.insert(0, card)
            return r
        t.save("back_to_plan", reason=rr.reason if rr.reason in ("year_end", "count", "cap", "test_shortfall") else "cap")
        key = f"progress.back_to_plan.{rr.reason}" if rr.reason in ("year_end", "count", "cap", "test_shortfall") \
            else "progress.back_to_plan.cap"
        slots = {}
        if key.endswith(("cap", "test_shortfall")):
            slots["required"] = T.fmt_rate(rr.required_return)
        if key.endswith("cap"):
            slots["cap_fit"] = T.fmt_rate(rr.cap_fit)
        return _Reply(key, slots, cards=[card])

    def _i_what_if_sl(self, t: _Turn, slots) -> _Reply:
        j = t.journey
        holdings = _open_holdings(j)
        if slots.instruments:
            holdings = [h for h in holdings if h[0] in slots.instruments] or holdings
        pnl, ytd, as_of, ys, _src = self._ytd(t)
        if ytd is None or as_of is None or (pnl is not None and len(pnl.series) < 2):
            entry = (pnl.year_start if pnl else None) or (j.tracking[0].entry_date if j.tracking else None)
            return _Reply("progress.no_data", {"entry_date": T.fmt_date(entry)})
        rows, shock, extra = [], 0.0, []
        for inst, pct, tau in holdings:
            entry = next((e.entry_date for e in j.tracking if e.instrument_id == inst), None)
            tr = self._trace(t, inst, tau, entry_date=entry)
            rows.append({"instrument_id": inst, "sl_distance": tr.sl_distance})
            if tr.sl_distance is not None:
                shock += pct / 100.0 * tr.sl_distance
            extra.append(("what_if_sl.line", {"instrument": inst, "sl_distance": T.fmt_rate(tr.sl_distance)}))
        hypothetical = (1.0 + ytd) * (1.0 + shock) - 1.0
        rr = self._required(t, hypothetical, as_of, ys)
        card = {"kind": "what_if", "data": {"ytd_return": rr.ytd_return, "required_return": rr.required_return,
                                            "status": rr.status, "reason": rr.reason, "rows": rows}}
        return _Reply("what_if_sl.result", {"ytd": T.fmt_rate(rr.ytd_return),
                                            "required": T.fmt_rate(rr.required_return),
                                            "status": T.WHAT_IF_STATUS[rr.status]}, cards=[card], extra=extra)

    # hedge / help ---------------------------------------------------------------

    def _i_show_hedge(self, t: _Turn, _slots) -> _Reply:
        plan = t.call("fno.get_hedge_plan", {}, HedgePlanOut, missing_ok=True)
        if plan is None:
            return _Reply("show_hedge.none")
        card = {"kind": "hedge", "data": {"n_hedged": len(plan.hedged_ids), "coverage": plan.coverage,
                                          "updated_at": plan.updated_at.isoformat() if plan.updated_at else None}}
        return _Reply("show_hedge.plan", {"n": T.fmt_num(len(plan.hedged_ids)), "coverage": T.fmt_num(plan.coverage)},
                      cards=[card])

    def _i_help(self, _t: _Turn, _slots) -> _Reply:
        return _Reply("help.menu")
