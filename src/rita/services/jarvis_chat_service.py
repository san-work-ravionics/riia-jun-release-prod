"""JarvisChatService — the Jarvis chat orchestrator (F44 P4 A1–A3, answers rebuilt on saved data).

One message: owner-checked session → MiniLM intent (``core/journey_intents``) → slots
(``core/journey_slots``) → the intent's handler over the in-memory MCP client (one session per
request, the caller's identity) → a versioned template (``jarvis_templates``) → the user and
assistant messages + session counters.

Rules:
- every answer comes from the user's OVERALL saved plan (``whatineed.get_goal``, every region) and the
  saved portfolio (``portfolio.pnl`` in ``saved`` mode, every region) — never from a journey: the chat
  selects nothing, tracks nothing and writes nothing;
- every number in a reply is a tool field, formatted by ``jarvis_templates`` (golden-tested) — no
  counts or sums are computed here;
- low confidence → ``fallback.low_confidence`` with the fixed chips and **no tool call**;
- personal data (goal figures, message text) is never logged — counts and ids only.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rita.config import get_settings
from rita.interfaces.mcp_client import McpCallError, McpRequestClient
from rita.models.jarvis import JarvisMessageModel, JarvisSessionModel
from rita.repositories.jarvis import JarvisMessageRepo, JarvisSessionRepo
from rita.schemas.goal_selection import GoalOut
from rita.schemas.mcp_tools import BucketStatusOut
from rita.schemas.jarvis import (
    ChipOut,
    MessageIn,
    MessageOut,
    PnlOut,
    ReplyOut,
    SessionOut,
    ToolCallOut,
    WarmupOut,
)
from rita.schemas.user_hedge_plan import HedgePlanOut
from rita.services import jarvis_templates as T

log = structlog.get_logger(__name__)

FNO_LINK = "/dashboard/fno.html"
LOCATIONS = ("europe", "india", "us")

# Classifier intents (the journey vocabulary the seed index was built on) that are answered from the saved
# plan and the saved portfolio.  The intent names are kept so the classifier and the stored message
# history stay valid; what they do is not a journey step any more.
SAVED_INTENTS = {
    "take_goal": "_s_plan", "change_goal": "_s_plan",
    "build_selection": "_s_portfolio", "why_this_pick": "_s_portfolio", "cant_reach": "_s_portfolio",
    "track": "_s_portfolio", "confirm": "_s_portfolio", "decline": "_s_portfolio",
    "progress": "_s_progress", "what_if_sl": "_s_progress",
    "show_hedge": "_i_show_hedge",
}
# F45 Phase D: the portfolio-tracker questions (bucket status against the plan, per location).
WN_INTENTS = frozenset({"wn_on_track", "wn_bucket_status", "wn_hedge_signal", "wn_what_needs_hedging"})


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
        log.warning("jarvis.warmup_failed", error=type(exc).__name__, detail=str(exc)[:200])
        raise JarvisChatError("unavailable", "chat model unavailable") from exc
    return WarmupOut(status="ready", intents=n)


class _Turn:
    """One message's tool calls (all over the request's MCP session)."""

    def __init__(self, mcp: McpRequestClient, location: str) -> None:
        self.mcp = mcp
        self.location = location
        self.calls: list[ToolCallOut] = []
        self.last_error = ""

    def call(self, tool: str, args: dict[str, Any], model: type[BaseModel] | None = None,
             *, missing_ok: bool = True):
        try:
            res = self.mcp.call(tool, args)
        except McpCallError as exc:
            status = "not_found" if exc.code == "not_found" else "error"
            self.last_error = exc.message
            self.calls.append(ToolCallOut(tool=tool, mcp_call_id=exc.call_id, status=status))
            if exc.code == "not_found" and missing_ok:
                return None if model is not None else exc
            raise _ToolDown(tool) from exc
        self.calls.append(ToolCallOut(tool=tool, mcp_call_id=res.call_id, status="ok"))
        return model.model_validate(res.structured) if model is not None else res.structured


def _goal_card(g: GoalOut) -> dict:
    return {"kind": "goal", "data": {"location": g.location, "currency": g.currency,
                                     "goal_return": g.goal_return, "horizon_years": g.horizon_years,
                                     "goal_value": g.goal_value,
                                     "plan_updated_at": g.plan_updated_at.isoformat() if g.plan_updated_at else None}}


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

        session = self._owned_session(inp.session_id)
        try:
            res = classify_journey(inp.text, self._cfg.intent_threshold)
        except Exception as exc:  # noqa: BLE001
            log.warning("jarvis.classify_failed", error=type(exc).__name__)
            raise JarvisChatError("unavailable", "chat model unavailable") from exc

        slots = parse_slots(inp.text)
        location = slots.location or inp.location

        intent = res.intent
        low = res.low_confidence
        turn = _Turn(self._mcp, location)

        if low:
            reply = _Reply("fallback.low_confidence")      # never guess, never call a tool
        else:
            try:
                reply = self._dispatch(turn, intent, slots)
            except _ToolDown as exc:
                reply = _Reply("error.unavailable", {"tool": exc.tool})

        text, template_id = self._text(reply)
        chips = [ChipOut(**c) for c in T.chips()]
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
        self._db.commit()
        log.info("jarvis.message", session_id=session.session_id, intent=out_reply.intent,
                 template=template_id, tool_calls=len(turn.calls))
        return MessageOut(session_id=session.session_id, reply=out_reply, journey=None)

    @staticmethod
    def _text(reply: _Reply) -> tuple[str, str]:
        text, tid = T.render(reply.key, **reply.slots)
        lines = [text] + [T.render(k, **s)[0] for k, s in reply.extra]
        if reply.prefix:
            lines.insert(0, reply.prefix)
        return " ".join(lines), tid

    # ── intent plans ───────────────────────────────────────────────────────────

    def _dispatch(self, t: _Turn, intent: str, slots) -> _Reply:
        """Every intent is accepted in every situation: the saved-data handler, a bucket (F45) handler or help."""
        return getattr(self, SAVED_INTENTS.get(intent, f"_i_{intent}"))(t, slots)

    # saved plan + saved portfolio, every region together ---------------------------------

    def _goals(self, t: _Turn) -> dict[str, GoalOut]:
        return {loc: t.call("whatineed.get_goal", {"location": loc}, GoalOut, missing_ok=False)
                for loc in LOCATIONS}

    def _pnls(self, t: _Turn, goals: dict[str, GoalOut] | None = None) -> dict[str, PnlOut | None]:
        out: dict[str, PnlOut | None] = {}
        for loc in LOCATIONS:
            g = goals.get(loc) if goals else None
            out[loc] = t.call("portfolio.pnl", {"location": loc, "source": "saved",
                                                "goal_return": g.goal_return if g is not None and g.saved else None},
                              PnlOut, missing_ok=True)
        return out

    # Replies carry only tool fields (no counts or sums computed here): see assert_numbers_from_tools.

    def _s_plan(self, t: _Turn, _slots) -> _Reply:
        goals = self._goals(t)
        have = [(loc, g) for loc, g in goals.items() if g.saved and g.goal_return is not None]
        if not have:
            return _Reply("saved.plan.none")
        parts = [f"{T.LOCATION_NAMES[loc]} {T.fmt_rate(g.goal_return)} a year over {T.fmt_num(g.horizon_years)} "
                 f"years, goal {T.fmt_money(g.currency, g.goal_value)}" for loc, g in have]
        missing = [T.LOCATION_NAMES[loc] for loc, g in goals.items() if not g.saved]
        note = f" No saved plan yet for {', '.join(missing)}." if missing else ""
        return _Reply("saved.plan", {"list": "; ".join(parts), "missing": note},
                      cards=[_goal_card(g) for _loc, g in have])

    def _s_portfolio(self, t: _Turn, _slots) -> _Reply:
        regions = [(loc, p) for loc, p in self._pnls(t).items() if p is not None and p.holdings]
        if not regions:
            return _Reply("saved.portfolio.none")
        extra = []
        for loc, p in regions:
            mix = ", ".join(
                f"{h.instrument_id} {T.fmt_num(h.allocation_pct)}%"
                + (f" ({T.fmt_rate(h.return_since)} since saved)" if h.return_since is not None else "")
                for h in p.holdings)
            extra.append(("saved.portfolio.line", {"region": T.LOCATION_NAMES[loc], "mix": mix}))
        return _Reply("saved.portfolio", extra=extra)

    def _s_progress(self, t: _Turn, _slots) -> _Reply:
        regions = [(loc, p) for loc, p in self._pnls(t, self._goals(t)).items() if p is not None and p.holdings]
        if not regions:
            return _Reply("saved.portfolio.none")
        extra = []
        for loc, p in regions:
            name = T.LOCATION_NAMES[loc]
            if p.ytd_return is None:
                extra.append(("saved.progress.line_none", {"region": name, "entry": T.fmt_date(p.entry_date)}))
            else:
                extra.append(("saved.progress.line", {"region": name, "ytd": T.fmt_rate(p.ytd_return),
                                                      "target": T.fmt_rate(p.target_to_date)}))
        return _Reply("saved.progress", extra=extra)

    # hedge / help ---------------------------------------------------------------

    def _i_show_hedge(self, t: _Turn, _slots) -> _Reply:
        plan = t.call("fno.get_hedge_plan", {}, HedgePlanOut, missing_ok=True)
        if plan is None:
            # No separately saved FnO hedge plan: answer from the saved plan and portfolio instead.
            r = self._s_progress(t, None)
            r.extra.append(("saved.hedge.pointer", {}))
            return r
        card = {"kind": "hedge", "data": {"n_hedged": len(plan.hedged_ids), "coverage": plan.coverage,
                                          "updated_at": plan.updated_at.isoformat() if plan.updated_at else None}}
        return _Reply("show_hedge.plan", {"n": T.fmt_num(len(plan.hedged_ids)), "coverage": T.fmt_num(plan.coverage)},
                      cards=[card])

    # F45 Phase D — What I Need portfolio tracker ------------------------------------------

    @staticmethod
    def _bucket_row(b) -> dict:
        return {"key": b.key, "ytd_return": b.ytd_return, "target_to_date": b.target_to_date,
                "gap": b.gap, "at_risk": b.at_risk}

    @staticmethod
    def _bucket_names(out: BucketStatusOut, *, at_risk: bool) -> str:
        return ", ".join(T.BUCKET_LABELS[b.key] for b in out.buckets if (b.at_risk is True) == at_risk
                         and b.at_risk is not None)

    @staticmethod
    def _wn_counts(out: BucketStatusOut) -> dict[str, str]:
        return {"n_buckets": T.fmt_num(out.n_buckets), "n_at_risk": T.fmt_num(out.n_at_risk),
                "n_on_track": T.fmt_num(out.n_on_track), "n_no_data": T.fmt_num(out.n_no_data),
                "threshold": T.fmt_rate(abs(out.at_risk_threshold))}

    def _buckets(self, t: _Turn) -> BucketStatusOut:
        return t.call("whatineed.bucket_status", {"location": t.location}, BucketStatusOut, missing_ok=False)

    def _i_wn_on_track(self, t: _Turn, _slots) -> _Reply:
        out = self._buckets(t)
        if not out.saved:
            return _Reply("wn.no_plan", {"location": T.LOCATION_NAMES.get(out.location, out.location)})
        card = {"kind": "bucket_progress", "data": {
            "buckets": [self._bucket_row(b) for b in out.buckets], "n_at_risk": out.n_at_risk,
            "n_on_track": out.n_on_track, "n_no_data": out.n_no_data}}
        counts = self._wn_counts(out)
        if out.n_buckets == 0:
            return _Reply("wn.no_buckets")
        if out.n_at_risk + out.n_on_track == 0:
            return _Reply("wn.no_data", counts, cards=[card])
        if out.n_at_risk == 0:
            return _Reply("wn.on_track.ok", counts, cards=[card])
        return _Reply("wn.on_track.risk", {**counts, "list": self._bucket_names(out, at_risk=True)}, cards=[card])

    def _i_wn_bucket_status(self, t: _Turn, slots) -> _Reply:
        if slots.bucket is None:
            if len(slots.buckets) > 1:
                return _Reply("wn.bucket.which_of", {"list": " or ".join(T.BUCKET_LABELS[k] for k in slots.buckets)})
            return _Reply("wn.bucket.which")
        out = self._buckets(t)
        if not out.saved:
            return _Reply("wn.no_plan", {"location": T.LOCATION_NAMES.get(out.location, out.location)})
        b = next((x for x in out.buckets if x.key == slots.bucket), None)
        if b is None:
            return _Reply("wn.bucket.not_in_plan", {"bucket": T.BUCKET_LABELS[slots.bucket]})
        label = T.BUCKET_LABELS[b.key]
        card = {"kind": "bucket_status", "data": {
            **self._bucket_row(b), "instruments": [i.instrument_id for i in b.instruments]}}
        if not b.instruments:
            return _Reply("wn.bucket.empty", {"bucket": label}, cards=[card])
        if b.at_risk is None:
            return _Reply("wn.bucket.no_data", {"bucket": label}, cards=[card])
        slots_ = {"bucket": label, "ytd": T.fmt_rate(b.ytd_return), "target": T.fmt_rate(b.target_to_date),
                  "gap": T.fmt_rate(b.gap), "threshold": T.fmt_rate(abs(out.at_risk_threshold))}
        return _Reply("wn.bucket.risk" if b.at_risk else "wn.bucket.ok", slots_, cards=[card])

    def _hedge_reply(self, out: BucketStatusOut, *, lines: bool) -> _Reply:
        if not out.saved:
            return _Reply("wn.no_plan", {"location": T.LOCATION_NAMES.get(out.location, out.location)})
        risky = [b for b in out.buckets if b.at_risk is True]
        card = {"kind": "hedge_signal", "data": {
            "at_risk_buckets": [b.key for b in risky],
            "all_on_track": out.n_at_risk == 0 and out.n_on_track > 0, "fno_link": FNO_LINK}}
        counts = self._wn_counts(out)
        if out.n_buckets == 0:
            return _Reply("wn.no_buckets")
        if out.n_at_risk + out.n_on_track == 0:
            return _Reply("wn.no_data", counts, cards=[card])
        if not risky:
            return _Reply("wn.hedge.none_partial" if out.n_no_data else "wn.hedge.none", counts, cards=[card])
        if lines:
            extra = [("wn.hedge.line", {"bucket": T.BUCKET_LABELS[b.key], "ytd": T.fmt_rate(b.ytd_return),
                                        "target": T.fmt_rate(b.target_to_date), "gap": T.fmt_rate(b.gap)})
                     for b in risky]
            return _Reply("wn.hedge.list", counts, cards=[card], extra=extra)
        return _Reply("wn.hedge.signal", {**counts, "list": self._bucket_names(out, at_risk=True)}, cards=[card])

    def _i_wn_hedge_signal(self, t: _Turn, _slots) -> _Reply:
        return self._hedge_reply(self._buckets(t), lines=False)

    def _i_wn_what_needs_hedging(self, t: _Turn, _slots) -> _Reply:
        return self._hedge_reply(self._buckets(t), lines=True)

    def _i_help(self, _t: _Turn, _slots) -> _Reply:
        return _Reply("help.menu")
