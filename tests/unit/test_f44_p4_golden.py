"""F44 P4 — golden Jarvis conversations (EUR / INR / USD), answered from the SAVED plan and portfolio.

The orchestrator (``JarvisChatService``) runs against a fake in-memory MCP client whose tools return valid
canned payloads.  The classifier is replaced by a lookup (intent per text) so the golden set is
deterministic; the real MiniLM is covered by test_f44_p4_intents.

Each turn checks the intent, the template, the tool calls — and the **number provenance**: every number in
the reply is a tool field formatted by ``jarvis_templates`` (``number_tokens``).  The chat selects nothing,
tracks nothing and writes nothing, so there is no journey state to check.
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
from rita.schemas.jarvis import MessageIn, PnlHoldingOut, PnlOut
from rita.schemas.user_hedge_plan import HedgePlanOut
from rita.services import jarvis_templates as T
from rita.services.jarvis_chat_service import JarvisChatService

from .f44_p4_helpers import CCY, PLAN_T0, goal, journey_db  # noqa: F401 — fixture

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
    """Routes tool calls to ``self.payloads`` (a model, a callable returning one, or None → not_found)."""

    def __init__(self, db, payloads: dict):
        self.db = db
        self.payloads = payloads
        self.results: list[dict] = []          # structured results of the current turn
        self.ids: list[str] = []

    def call(self, name, args=None):
        args = args or {}
        cid = str(uuid.uuid4())
        self.ids.append(cid)
        p = self.payloads.get(name)
        p = p(args) if callable(p) else p
        if p is None:
            raise McpCallError(name, "not_found", self.payloads.get(name + ":msg", "none"), cid)
        res = p.model_dump(mode="json")
        self.results.append(res)
        return ToolCallResult(name=name, structured=res, text="", call_id=cid)


def _walk(x, nums: list, strs: list):
    if isinstance(x, dict):
        for v in x.values():
            _walk(v, nums, strs)
    elif isinstance(x, list):
        nums.append(len(x))                     # counts of tool lists (n_hedged)
        for v in x:
            _walk(v, nums, strs)
    elif isinstance(x, bool) or x is None:
        return
    elif isinstance(x, (int, float)):
        nums.append(x)
    elif isinstance(x, str):
        strs.append(x)


_TOKEN = re.compile(r"\d{4}-\d{2}-\d{2}|(?<![A-Za-z])[A-Z]{3} -?[\d,]+(?:\.\d+)?|-?\d[\d,]*(?:\.\d+)?%?")


def _instrument_ids(x, out: set) -> set:
    """Every ``instrument_id`` value in a tool result (DJI, E1, ...): ids, never numbers or currencies."""
    if isinstance(x, dict):
        for k, v in x.items():
            if k == "instrument_id" and isinstance(v, str):
                out.add(v)
            _instrument_ids(v, out)
    elif isinstance(x, list):
        for v in x:
            _instrument_ids(v, out)
    return out


def assert_numbers_from_tools(text: str, results: list[dict]):
    nums, strs = [], []
    for r in results:
        _walk(r, nums, strs)
    allowed = T.number_tokens(nums + strs, currencies=set(CCY.values()))
    named = set()
    for r in results:
        _instrument_ids(r, named)
    ids = sorted({s for s in strs if re.fullmatch(r"[A-Z][A-Z0-9_]*\d[A-Z0-9_]*", s)} | named, key=len, reverse=True)
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


def _pnl(location: str, ytd: float | None, holdings, *, target: float = 0.0412, entry: date | None = None) -> PnlOut:
    s = entry or TODAY - timedelta(days=40)
    return PnlOut(location=location, currency=CCY[location], source="saved", as_of=TODAY, year_start=s,
                  entry_date=s, goal_return=0.0775, ytd_return=ytd, target_to_date=target if ytd is not None else None,
                  coverage=1.0, holdings=[PnlHoldingOut(instrument_id=i, allocation_pct=a, return_since=r,
                                                        status="ok" if r is not None else "no_shares")
                                          for i, a, r in holdings])


def _turn(svc, mcp, sid, text, location):
    mcp.results.clear()
    mcp.ids.clear()
    return svc.message(MessageIn(session_id=sid, text=text, location=location))


def _session(svc, location):
    return svc.open_session(location).session_id


def _check(out, mcp, template, tools=None):
    r = out.reply
    assert r.template_id == f"{template}.v1", (r.template_id, r.text)
    assert out.journey is None                                       # the chat never creates a journey
    if tools is not None:
        assert [c.tool for c in r.tool_calls] == tools
    assert [c.mcp_call_id for c in r.tool_calls] == mcp.ids
    assert_numbers_from_tools(r.text, mcp.results)


GOAL = ["whatineed.get_goal"] * 3
PNL = ["portfolio.pnl"] * 3


def _payloads(goals: dict, pnls: dict, hedge=None):
    return {"whatineed.get_goal": lambda a: goals[a["location"]],
            "portfolio.pnl": lambda a: pnls.get(a["location"]), "fno.get_hedge_plan": hedge}


def test_golden_all_regions(journey_db, fake_classifier):
    """EUR + INR + USD together: plan, portfolio, progress and hedge, with a saved FnO hedge plan."""
    goals = {"europe": goal("europe"), "india": goal("india", r=0.085), "us": goal("us", r=0.07)}
    pnls = {"europe": _pnl("europe", 0.031, [("E1", 60.0, 0.02), ("E2", 40.0, 0.045)]),
            "india": _pnl("india", -0.0412, [("NIFTY", 50.0, -0.03), ("BANKNIFTY", 50.0, -0.05)], target=0.0388),
            "us": _pnl("us", 0.0155, [("DJI", 100.0, 0.0155)], target=0.0301)}
    hedge = HedgePlanOut(key_id="k", hedged_ids=["E1", "E2"], coverage=50, scenario_tab="s", duration="d",
                         updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    mcp = FakeMcp(journey_db, _payloads(goals, pnls, hedge))
    svc = JarvisChatService(journey_db, mcp, User())
    sid = _session(svc, "europe")

    out = _turn(svc, mcp, sid, "hi", "europe")
    _check(out, mcp, "help.menu", [])
    assert [c.label for c in out.reply.chips] == [label for label, _ in T.CHIPS]
    out = _turn(svc, mcp, sid, "use my goal", "europe")
    _check(out, mcp, "saved.plan", GOAL)
    for region, rate in (("Europe", "7.8%"), ("India", "8.5%"), ("US", "7.0%")):
        assert f"{region} {rate} a year over 13 years" in out.reply.text
    assert [c.kind for c in out.reply.cards] == ["goal"] * 3
    out = _turn(svc, mcp, sid, "build my portfolio", "europe")
    _check(out, mcp, "saved.portfolio", PNL)
    assert "Europe: E1 60% (2.0% since saved), E2 40% (4.5% since saved)." in out.reply.text
    assert "India: NIFTY 50% (-3.0% since saved), BANKNIFTY 50% (-5.0% since saved)." in out.reply.text
    assert "US: DJI 100% (1.6% since saved)." in out.reply.text
    out = _turn(svc, mcp, sid, "how am I doing", "europe")
    _check(out, mcp, "saved.progress", GOAL + PNL)
    assert "India: -4.1% this year against 3.9% to date." in out.reply.text
    out = _turn(svc, mcp, sid, "show my hedge plan", "europe")
    _check(out, mcp, "show_hedge.plan", ["fno.get_hedge_plan"])
    assert out.reply.cards[0].kind == "hedge"
    out = _turn(svc, mcp, sid, "blorp zzz", "europe")
    assert out.reply.template_id == "fallback.low_confidence.v1" and out.reply.tool_calls == []
    assert out.reply.low_confidence and out.reply.chips

    rows = journey_db.query(JarvisMessageModel).filter_by(session_id=sid).all()
    assert len(rows) == 12 and {r.role for r in rows} == {"user", "assistant"}
    assistant = [r for r in rows if r.role == "assistant" and r.tool_calls]
    assert all(set(c) == {"tool", "mcp_call_id", "status"} for r in assistant for c in r.tool_calls)


def test_golden_inr_portfolio_saved_but_no_price_after_the_save(journey_db, fake_classifier):
    """India saved index holdings today: there is no measured return yet, and the reply says from when."""
    saved = TODAY
    goals = {"europe": goal("europe", saved=False), "india": goal("india", r=0.085), "us": goal("us", saved=False)}
    pnls = {"india": _pnl("india", None, [("NIFTY", 20.0, None), ("BANKNIFTY", 20.0, None)], entry=saved)}
    mcp = FakeMcp(journey_db, _payloads(goals, pnls))
    svc = JarvisChatService(journey_db, mcp, User())
    sid = _session(svc, "india")
    out = _turn(svc, mcp, sid, "use my goal", "india")
    _check(out, mcp, "saved.plan", GOAL)
    assert "India 8.5% a year" in out.reply.text and "No saved plan yet for Europe, US." in out.reply.text
    out = _turn(svc, mcp, sid, "track it", "india")
    _check(out, mcp, "saved.portfolio", PNL)
    assert out.reply.text.endswith("India: NIFTY 20%, BANKNIFTY 20%.")           # no return → no figure
    out = _turn(svc, mcp, sid, "how am I doing", "india")
    _check(out, mcp, "saved.progress", GOAL + PNL)
    assert f"India: no measured return yet, prices after {saved.isoformat()} are needed." in out.reply.text
    out = _turn(svc, mcp, sid, "show my hedge plan", "india")                    # no FnO plan → from plan + portfolio
    _check(out, mcp, "saved.progress", ["fno.get_hedge_plan"] + GOAL + PNL)
    assert out.reply.text.endswith("A hedge is built in FnO. Open it to review.")


def test_golden_usd_nothing_saved_then_a_plan_and_a_portfolio(journey_db, fake_classifier):
    cur = {"goal": goal("us", saved=False), "pnl": None}
    goals = {"europe": goal("europe", saved=False), "india": goal("india", saved=False)}
    payloads = {"whatineed.get_goal": lambda a: cur["goal"] if a["location"] == "us" else goals[a["location"]],
                "portfolio.pnl": lambda a: cur["pnl"] if a["location"] == "us" else None, "fno.get_hedge_plan": None}
    mcp = FakeMcp(journey_db, payloads)
    svc = JarvisChatService(journey_db, mcp, User())
    sid = _session(svc, "us")
    _check(_turn(svc, mcp, sid, "use my goal", "us"), mcp, "saved.plan.none", GOAL)
    _check(_turn(svc, mcp, sid, "build my portfolio", "us"), mcp, "saved.portfolio.none", PNL)
    _check(_turn(svc, mcp, sid, "how am I doing", "us"), mcp, "saved.portfolio.none", GOAL + PNL)
    _check(_turn(svc, mcp, sid, "show my hedge plan", "us"), mcp, "saved.portfolio.none",
           ["fno.get_hedge_plan"] + GOAL + PNL)                        # never "you have no hedge plan"
    # the user then saves a plan (What I Need) and a portfolio (RITA): the very next question sees both
    cur["goal"] = goal("us", updated=PLAN_T0 + timedelta(days=3), r=0.12)
    cur["pnl"] = _pnl("us", 0.0155, [("DJI", 100.0, 0.0155)], target=0.0301)
    out = _turn(svc, mcp, sid, "use my goal", "us")
    _check(out, mcp, "saved.plan", GOAL)
    assert "US 12.0% a year" in out.reply.text
    out = _turn(svc, mcp, sid, "how am I doing", "us")
    _check(out, mcp, "saved.progress", GOAL + PNL)
    assert "US: 1.6% this year against 3.0% to date." in out.reply.text


def test_no_pnl_anywhere_is_no_portfolio_not_an_invented_return(journey_db, fake_classifier):
    """CR-2 carried over: ``portfolio.pnl`` not_found everywhere → no portfolio, and no number in the reply."""
    goals = {loc: goal(loc) for loc in ("europe", "india", "us")}
    mcp = FakeMcp(journey_db, _payloads(goals, {}))
    svc = JarvisChatService(journey_db, mcp, User())
    sid = _session(svc, "europe")
    for text in ("how am I doing", "what if a stop loss hits"):
        out = _turn(svc, mcp, sid, text, "europe")
        _check(out, mcp, "saved.portfolio.none", GOAL + PNL)
        assert not re.search(r"\d", out.reply.text)


def test_tool_unavailable_replies_error_template(journey_db, fake_classifier):
    def down(_a):
        raise McpCallError("portfolio.pnl", "unavailable", "boom", "cid")

    goals = {loc: goal(loc) for loc in ("europe", "india", "us")}
    mcp = FakeMcp(journey_db, _payloads(goals, {}))
    svc = JarvisChatService(journey_db, mcp, User())
    sid = _session(svc, "europe")
    mcp.payloads["portfolio.pnl"] = down
    out = _turn(svc, mcp, sid, "build my portfolio", "europe")
    assert out.reply.template_id == "error.unavailable.v1" and "portfolio.pnl" in out.reply.text
    assert out.journey is None


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
