"""F44 P4 — golden Jarvis conversations (EUR / INR / USD).

The orchestrator (``JarvisChatService``) runs against a fake in-memory MCP client: the journey
tools go to the real ``JourneyService`` on a test DB; the P3 / FnO / pnl tools return valid canned
payloads.  The classifier is replaced by a lookup (intent per text) so the golden set is
deterministic; the real MiniLM is covered by test_f44_p4_intents.

Each turn checks the intent, the template, the state transition, the tool calls — and the
**number provenance**: every number in the reply is a tool field formatted by
``jarvis_templates`` (``number_tokens``).
"""
# ruff: noqa: F811 — pytest fixtures imported from a sibling module are redefined as test params
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from rita.core import journey_intents as ji
from rita.core.journey_intents import JourneyIntentResult
from rita.interfaces.mcp_client import McpCallError, ToolCallResult
from rita.models.jarvis import JarvisMessageModel
from rita.schemas.jarvis import JourneyGetIn, JourneySaveIn, MessageIn, PnlOut
from rita.schemas.user_hedge_plan import HedgePlanOut
from rita.services import jarvis_templates as T
from rita.services.jarvis_chat_service import JarvisChatService
from rita.services.journey_service import JourneyError, JourneyService

from .f44_p4_helpers import (
    CCY,
    PLAN_T0,
    goal,
    holding,
    journey_db,  # noqa: F401 — fixture
    required,
    runs_out,
    selection,
    trace,
)

INTENT_OF = {
    "hi": "help", "use my goal": "take_goal", "build my portfolio": "build_selection",
    "why these instruments": "why_this_pick", "track it": "track", "how am I doing": "progress",
    "what if a stop loss hits": "what_if_sl", "show my hedge plan": "show_hedge", "yes": "confirm",
    "no": "decline", "what's the closest": "cant_reach", "change my goal": "change_goal",
}
TODAY = date.today()


class User:
    id = "alice"


class FakeMcp:
    """Routes tool calls: journey.* → the real JourneyService; the rest → ``self.payloads``."""

    def __init__(self, db, payloads: dict):
        self.db = db
        self.payloads = payloads
        self.results: list[dict] = []          # structured results of the current turn
        self.ids: list[str] = []

    def call(self, name, args=None):
        args = args or {}
        cid = str(uuid.uuid4())
        self.ids.append(cid)
        svc = JourneyService(self.db)
        try:
            if name == "journey.get_current":
                out = svc.get_current(User.id, JourneyGetIn(**args).location)
                if out is None:
                    raise McpCallError(name, "not_found", "no journey", cid)
                res = out.model_dump(mode="json")
            elif name == "journey.save":
                res = svc.save(User.id, JourneySaveIn.model_validate(args)).model_dump(mode="json")
            else:
                p = self.payloads.get(name)
                p = p(args) if callable(p) else p
                if p is None:
                    raise McpCallError(name, "not_found", self.payloads.get(name + ":msg", "none"), cid)
                res = p.model_dump(mode="json")
        except JourneyError as exc:
            raise McpCallError(name, exc.code, exc.message, cid) from exc
        self.results.append(res)
        return ToolCallResult(name=name, structured=res, text="", call_id=cid)


def _walk(x, nums: list, strs: list):
    if isinstance(x, dict):
        for v in x.values():
            _walk(v, nums, strs)
    elif isinstance(x, list):
        nums.append(len(x))                     # counts of tool lists (n_tolerances, n_hedged)
        for v in x:
            _walk(v, nums, strs)
    elif isinstance(x, bool) or x is None:
        return
    elif isinstance(x, (int, float)):
        nums.append(x)
    elif isinstance(x, str):
        strs.append(x)


_TOKEN = re.compile(r"\d{4}-\d{2}-\d{2}|(?<![A-Za-z])[A-Z]{3} -?[\d,]+(?:\.\d+)?|-?\d[\d,]*(?:\.\d+)?%?")


def assert_numbers_from_tools(text: str, results: list[dict]):
    nums, strs = [], []
    for r in results:
        _walk(r, nums, strs)
    allowed = T.number_tokens(nums + strs, currencies=set(CCY.values()))
    ids = sorted({s for s in strs if re.fullmatch(r"[A-Z][A-Z0-9_]*\d[A-Z0-9_]*", s)}, key=len, reverse=True)
    scrub = text
    for i in ids:
        scrub = re.sub(rf"\b{re.escape(i)}\b", "ID", scrub)
    for tok in _TOKEN.findall(scrub):
        assert tok in allowed or tok.rstrip("%") in allowed, (tok, text)


@pytest.fixture
def fake_classifier(monkeypatch):
    def classify(text, threshold):
        if text in INTENT_OF:
            return JourneyIntentResult(intent=INTENT_OF[text], confidence=0.93, low_confidence=False)
        return JourneyIntentResult(intent="help", confidence=0.21, low_confidence=True)

    monkeypatch.setattr(ji, "classify_journey", classify)


def _pnl(location: str, ytd: float, s: date, n: int = 30) -> PnlOut:
    from rita.schemas.jarvis import PnlHoldingOut, PnlPointOut, TargetPointOut

    pts = [PnlPointOut(date=s + timedelta(days=k), ret=ytd * k / (n - 1), source="model_sleeves") for k in range(n)]
    return PnlOut(location=location, currency=CCY[location], source="model_sleeves", as_of=pts[-1].date,
                  year_start=s, entry_date=s, goal_return=0.0775, ytd_return=ytd, target_to_date=0.0412,
                  coverage=1.0, series=pts, target_path=[TargetPointOut(date=s, target=0.0)],
                  holdings=[PnlHoldingOut(instrument_id="E1", allocation_pct=60, return_since=ytd, status="ok")])


def _turn(svc, mcp, sid, text, location):
    mcp.results.clear()
    mcp.ids.clear()
    out = svc.message(MessageIn(session_id=sid, text=text, location=location))
    return out


def _session(svc, location):
    return svc.open_session(location).session_id


def _check(out, mcp, template, state, tools=None):
    r = out.reply
    assert r.template_id == f"{template}.v1", (r.template_id, r.text)
    assert (out.journey.state if out.journey else None) == state
    if tools is not None:
        assert [c.tool for c in r.tool_calls] == tools
    assert [c.mcp_call_id for c in r.tool_calls] == mcp.ids
    assert_numbers_from_tools(r.text, mcp.results)


def test_golden_eur(journey_db, fake_classifier):
    sel = selection("europe")
    payloads = {
        "whatineed.get_goal": goal("europe"), "portfolio.select_for_goal": sel,
        "portfolio.model_runs": runs_out("europe", sel),
        "portfolio.sleeve_trace": lambda a: trace(a["instrument"], as_of=TODAY),
        "portfolio.pnl": _pnl("europe", 0.031, TODAY - timedelta(days=40)),
        "portfolio.required_return": lambda a: required(ytd=a["ytd_return"]),
        "fno.get_hedge_plan": HedgePlanOut(key_id="k", hedged_ids=["E1", "E2"], coverage=50, scenario_tab="s",
                                           duration="d", updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc)),
    }
    mcp = FakeMcp(journey_db, payloads)
    svc = JarvisChatService(journey_db, mcp, User())
    sid = _session(svc, "europe")

    _check(_turn(svc, mcp, sid, "hi", "europe"), mcp, "help.menu", None, ["journey.get_current"])
    out = _turn(svc, mcp, sid, "use my goal", "europe")
    _check(out, mcp, "take_goal.loaded", "goal_loaded",
           ["journey.get_current", "whatineed.get_goal", "journey.save"])
    assert "EUR 264,804" in out.reply.text and "7.8%" in out.reply.text
    assert out.reply.cards[0].kind == "goal"
    out = _turn(svc, mcp, sid, "build my portfolio", "europe")
    _check(out, mcp, "build.meets", "selected")
    assert "E1 60%, E2 40%" in out.reply.text and out.reply.cards[0].kind == "selection"
    _check(_turn(svc, mcp, sid, "why these instruments", "europe"), mcp, "why.mix", "selected")
    out = _turn(svc, mcp, sid, "track it", "europe")
    _check(out, mcp, "track.started", "tracking",
           ["journey.get_current", "whatineed.get_goal", "portfolio.sleeve_trace", "portfolio.sleeve_trace",
            "journey.save"])
    assert out.journey.tracking[0].entry_date == TODAY and out.journey.plan_year_start == TODAY
    out = _turn(svc, mcp, sid, "how am I doing", "europe")
    _check(out, mcp, "progress.on_track", "tracking")
    assert out.reply.cards[0].kind == "progress"
    out = _turn(svc, mcp, sid, "what if a stop loss hits", "europe")
    _check(out, mcp, "what_if_sl.result", "tracking")
    assert out.journey.state == "tracking" and out.reply.cards[0].kind == "what_if"   # never transitions
    _check(_turn(svc, mcp, sid, "show my hedge plan", "europe"), mcp, "show_hedge.plan", "tracking")
    out = _turn(svc, mcp, sid, "blorp zzz", "europe")
    assert out.reply.template_id == "fallback.low_confidence.v1" and out.reply.tool_calls == []
    assert out.reply.low_confidence and out.reply.chips

    rows = journey_db.query(JarvisMessageModel).filter_by(session_id=sid).all()
    assert len(rows) == 18 and {r.role for r in rows} == {"user", "assistant"}
    assistant = [r for r in rows if r.role == "assistant" and r.tool_calls]
    assert all(set(c) == {"tool", "mcp_call_id", "status"} for r in assistant for c in r.tool_calls)


def test_golden_inr_reselect_then_back_to_plan(journey_db, fake_classifier):
    sel = selection("india", target=0.085, meets=False,
                    holdings=[holding("NIFTY", 60), holding("RELIANCE", 25), holding("SBIN", 15)])
    prop = selection("india", target=0.11, holdings=[holding("RELIANCE", 70), holding("SBIN", 30)])
    state = {"n": 0}

    def rr(a):
        state["n"] += 1
        if state["n"] == 1:
            return required("reselect_proposed", "ok", ytd=a["ytd_return"], used=a["reselections_used"],
                            proposal=prop, goal=0.085)
        return required("back_to_plan", "count", ytd=a["ytd_return"], used=a["reselections_used"], goal=0.085)

    payloads = {
        "whatineed.get_goal": goal("india", r=0.085), "portfolio.select_for_goal": sel,
        "portfolio.sleeve_trace": lambda a: trace(a["instrument"], as_of=TODAY, sl_hit=a["instrument"] == "NIFTY"),
        "portfolio.pnl": _pnl("india", -0.0412, TODAY - timedelta(days=60)),
        "portfolio.required_return": rr,
    }
    mcp = FakeMcp(journey_db, payloads)
    svc = JarvisChatService(journey_db, mcp, User())
    sid = _session(svc, "india")
    _check(_turn(svc, mcp, sid, "use my goal", "india"), mcp, "take_goal.loaded", "goal_loaded")
    out = _turn(svc, mcp, sid, "build my portfolio", "india")
    _check(out, mcp, "build.test_short", "selected")
    _check(_turn(svc, mcp, sid, "track it", "india"), mcp, "track.started", "tracking")
    out = _turn(svc, mcp, sid, "how am I doing", "india")
    _check(out, mcp, "progress.reselect", "reselect_proposed")
    assert out.journey.reselect_count == 1 and out.journey.reselections[-1].trigger == "sl_hit"
    assert {c.kind for c in out.reply.cards} == {"progress", "proposal"}
    out = _turn(svc, mcp, sid, "yes", "india")
    _check(out, mcp, "confirm.accepted", "tracking")
    assert [s.cause for s in out.journey.segments] == ["track", "accept"]
    assert out.journey.plan_year_start == TODAY
    out = _turn(svc, mcp, sid, "how am I doing", "india")
    _check(out, mcp, "progress.back_to_plan.count", "back_to_plan")
    assert out.journey.back_to_plan_reason == "count"
    _check(_turn(svc, mcp, sid, "use my goal", "india"), mcp, "take_goal.same_plan", "back_to_plan")
    _check(_turn(svc, mcp, sid, "track it", "india"), mcp, "state_prompt.back_to_plan", "back_to_plan")


def test_golden_usd_no_plan_then_newer_plan_cant_reach(journey_db, fake_classifier):
    cur = {"goal": goal("us", saved=False)}
    sel = selection("us", target=0.12, closest=True)
    payloads = {
        "whatineed.get_goal": lambda a: cur["goal"], "portfolio.select_for_goal": sel,
        "fno.get_hedge_plan": None,
    }
    mcp = FakeMcp(journey_db, payloads)
    svc = JarvisChatService(journey_db, mcp, User())
    sid = _session(svc, "us")
    _check(_turn(svc, mcp, sid, "use my goal", "us"), mcp, "take_goal.no_plan", "no_goal")
    _check(_turn(svc, mcp, sid, "build my portfolio", "us"), mcp, "state_prompt.no_goal", "no_goal")
    _check(_turn(svc, mcp, sid, "show my hedge plan", "us"), mcp, "show_hedge.none", "no_goal")
    cur["goal"] = goal("us", updated=PLAN_T0 + timedelta(days=3), r=0.12)
    out = _turn(svc, mcp, sid, "use my goal", "us")
    _check(out, mcp, "take_goal.loaded", "goal_loaded")
    assert out.reply.text.startswith("Your What I Need plan changed on")          # notice prefix
    out = _turn(svc, mcp, sid, "build my portfolio", "us")
    _check(out, mcp, "build.cant_reach", "cant_reach")
    assert out.reply.cards[0].kind == "closest"
    _check(_turn(svc, mcp, sid, "what's the closest", "us"), mcp, "build.cant_reach", "cant_reach")
    _check(_turn(svc, mcp, sid, "track it", "us"), mcp, "state_prompt.cant_reach", "cant_reach")
    _check(_turn(svc, mcp, sid, "change my goal", "us"), mcp, "change_goal.info", "cant_reach")
    # a newer plan while in a journey → notice prefix, no restart until "use my goal"
    cur["goal"] = goal("us", updated=PLAN_T0 + timedelta(days=9), r=0.10)
    out = _turn(svc, mcp, sid, "what's the closest", "us")
    assert out.reply.text.startswith("Your What I Need plan changed on") and out.journey.state == "cant_reach"


def test_none_eligible_lists_the_exclusions(journey_db, fake_classifier):
    payloads = {"whatineed.get_goal": goal("europe"), "portfolio.select_for_goal": None,
                "portfolio.select_for_goal:msg": "no eligible model-managed instrument in europe "
                                                 "(excluded: ATO:retrain_needed, ASRNL:no_model)"}
    mcp = FakeMcp(journey_db, payloads)
    svc = JarvisChatService(journey_db, mcp, User())
    sid = _session(svc, "europe")
    _turn(svc, mcp, sid, "use my goal", "europe")
    out = _turn(svc, mcp, sid, "build my portfolio", "europe")
    assert out.reply.template_id == "build.none_eligible.v1" and out.journey.state == "goal_loaded"
    assert "ATO (model needs retraining" in out.reply.text and out.reply.cards[0].kind == "excluded"


def test_tool_unavailable_replies_error_template(journey_db, fake_classifier):
    def down(_a):
        raise McpCallError("portfolio.select_for_goal", "unavailable", "boom", "cid")

    mcp = FakeMcp(journey_db, {"whatineed.get_goal": goal("europe")})
    svc = JarvisChatService(journey_db, mcp, User())
    sid = _session(svc, "europe")
    _turn(svc, mcp, sid, "use my goal", "europe")
    mcp.payloads["portfolio.select_for_goal"] = down
    out = _turn(svc, mcp, sid, "build my portfolio", "europe")
    assert out.reply.template_id == "error.unavailable.v1" and "portfolio.select_for_goal" in out.reply.text


def test_session_reuse_and_idle_close(journey_db):
    mcp = FakeMcp(journey_db, {})
    svc = JarvisChatService(journey_db, mcp, User())
    a = svc.open_session("europe")
    b = svc.open_session("europe")
    assert b.reused and b.session_id == a.session_id
    from rita.models.jarvis import JarvisSessionModel
    row = journey_db.get(JarvisSessionModel, a.session_id)
    row.last_activity_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    journey_db.commit()
    c = svc.open_session("europe")
    assert not c.reused and c.session_id != a.session_id
    assert journey_db.get(JarvisSessionModel, a.session_id).status == "closed"
    assert svc.open_session("india").session_id != c.session_id        # per location


def test_session_owner_check(journey_db, fake_classifier):
    from rita.services.jarvis_chat_service import JarvisChatError

    mcp = FakeMcp(journey_db, {})
    sid = JarvisChatService(journey_db, mcp, User()).open_session("europe").session_id

    class Bob:
        id = "bob"

    with pytest.raises(JarvisChatError) as e:
        JarvisChatService(journey_db, mcp, Bob()).message(MessageIn(session_id=sid, text="hi", location="europe"))
    assert e.value.code == "not_found"
    with pytest.raises(JarvisChatError):
        JarvisChatService(journey_db, mcp, User()).message(MessageIn(session_id="nope", text="hi", location="europe"))
