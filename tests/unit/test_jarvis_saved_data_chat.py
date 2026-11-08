"""Jarvis chat answers come from the OVERALL saved plan and the saved portfolio — every region together —
never from a journey: the chat selects nothing, tracks nothing and writes nothing.

Per-intent contracts (the end-to-end conversations are in ``test_f44_p4_golden``).  Same harness: the
orchestrator over a fake MCP client, the classifier replaced by a lookup, and every reply checked for
number provenance (each number is a tool field).
"""
# ruff: noqa: F811 — pytest fixtures imported from a sibling module are redefined as test params
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from rita.core import journey_intents as ji
from rita.schemas.jarvis import PnlHoldingOut, PnlOut
from rita.schemas.user_hedge_plan import HedgePlanOut
from rita.services import jarvis_templates as T
from rita.services.jarvis_chat_service import SAVED_INTENTS, WN_INTENTS, JarvisChatService

from .f44_p4_helpers import CCY, goal, journey_db  # noqa: F401 — fixture
from .test_f44_p4_golden import (  # noqa: F401 — fake_classifier is a fixture
    INTENT_OF,
    FakeMcp,
    User,
    _check,
    _session,
    _turn,
    fake_classifier,
)

ENTRY = date(2026, 3, 2)
# nothing the chat does may ever call one of these (they are the journey / model-selection tools)
RETIRED_TOOLS_PREFIX = ("journey.", "portfolio.select_for_goal", "portfolio.sleeve_trace", "portfolio.model_runs",
                        "portfolio.required_return", "market.asta_trace")
GOAL = ["whatineed.get_goal"] * 3
PNL = ["portfolio.pnl"] * 3


def _pnl(loc: str, ytd: float | None, holdings, target: float | None = 0.0412) -> PnlOut:
    return PnlOut(location=loc, currency=CCY[loc], source="saved", as_of=date(2026, 7, 1), year_start=ENTRY,
                  entry_date=ENTRY, goal_return=0.0775, ytd_return=ytd,
                  target_to_date=target if ytd is not None else None, coverage=1.0,
                  holdings=[PnlHoldingOut(instrument_id=i, allocation_pct=a, return_since=r,
                                          status="ok" if r is not None else "no_shares") for i, a, r in holdings])


EUROPE = _pnl("europe", 0.031, [("E1", 60.0, 0.02)])
INDIA = _pnl("india", None, [("NIFTY", 20.0, -0.034), ("BANKNIFTY", 20.0, None)])


def _chat(db, goals: dict, pnls: dict, hedge=None):
    payloads = {"whatineed.get_goal": lambda a: goals[a["location"]],
                "portfolio.pnl": lambda a: pnls.get(a["location"]),
                "fno.get_hedge_plan": hedge}
    mcp = FakeMcp(db, payloads)
    svc = JarvisChatService(db, mcp, User())
    return svc, mcp, _session(svc, "europe")


def _tools(out):
    return [c.tool for c in out.reply.tool_calls]


GOALS_TWO = {"europe": goal("europe"), "india": goal("india", r=0.085), "us": goal("us", saved=False)}
GOALS_NONE = {loc: goal(loc, saved=False) for loc in ("europe", "india", "us")}


# ── plan ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["use my goal", "change my goal"])
def test_plan_question_covers_every_region_with_a_plan_and_names_the_missing_ones(journey_db, fake_classifier, text):
    svc, mcp, sid = _chat(journey_db, GOALS_TWO, {})
    out = _turn(svc, mcp, sid, text, "europe")
    _check(out, mcp, "saved.plan", GOAL)                             # one goal read per region, nothing else
    assert "Europe 7.8% a year over 13 years" in out.reply.text
    assert "India 8.5% a year over 13 years" in out.reply.text
    assert "No saved plan yet for US." in out.reply.text
    assert [c.kind for c in out.reply.cards] == ["goal", "goal"]
    assert {c.data.location for c in out.reply.cards} == {"europe", "india"}


def test_no_plan_saved_anywhere(journey_db, fake_classifier):
    svc, mcp, sid = _chat(journey_db, GOALS_NONE, {})
    out = _turn(svc, mcp, sid, "use my goal", "europe")
    _check(out, mcp, "saved.plan.none", GOAL)
    assert "Save one on What I Need" in out.reply.text


def test_the_location_the_chat_is_opened_on_does_not_narrow_the_answer(journey_db, fake_classifier):
    svc, mcp, sid = _chat(journey_db, GOALS_TWO, {})
    for loc in ("europe", "india", "us"):
        out = _turn(svc, mcp, sid, "use my goal", loc)
        assert "Europe 7.8%" in out.reply.text and "India 8.5%" in out.reply.text, loc


# ── portfolio ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["build my portfolio", "why these instruments", "track it", "yes", "no",
                                  "what's the closest"])
def test_every_journey_intent_answers_from_the_saved_portfolio(journey_db, fake_classifier, text):
    svc, mcp, sid = _chat(journey_db, GOALS_TWO, {"europe": EUROPE, "india": INDIA})
    out = _turn(svc, mcp, sid, text, "europe")
    _check(out, mcp, "saved.portfolio", PNL)
    assert "Europe: E1 60% (2.0% since saved)." in out.reply.text
    assert "India: NIFTY 20% (-3.4% since saved), BANKNIFTY 20%." in out.reply.text      # no return → no figure
    assert "US:" not in out.reply.text                                                    # nothing saved there


def test_portfolio_question_reads_the_saved_path_of_every_region_and_nothing_else(journey_db, fake_classifier):
    seen = []
    svc, mcp, sid = _chat(journey_db, GOALS_TWO, {"europe": EUROPE})
    orig = mcp.payloads["portfolio.pnl"]
    mcp.payloads["portfolio.pnl"] = lambda a: (seen.append((a["location"], a["source"], a["goal_return"])), orig(a))[1]
    _turn(svc, mcp, sid, "build my portfolio", "europe")
    assert seen == [("europe", "saved", None), ("india", "saved", None), ("us", "saved", None)]


def test_no_saved_portfolio(journey_db, fake_classifier):
    svc, mcp, sid = _chat(journey_db, GOALS_TWO, {})
    out = _turn(svc, mcp, sid, "track it", "europe")
    _check(out, mcp, "saved.portfolio.none", PNL)
    assert "Save one in RITA" in out.reply.text


# ── progress ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["how am I doing", "what if a stop loss hits"])
def test_progress_is_each_regions_return_against_its_own_target(journey_db, fake_classifier, text):
    svc, mcp, sid = _chat(journey_db, GOALS_TWO, {"europe": EUROPE, "india": INDIA})
    out = _turn(svc, mcp, sid, text, "europe")
    _check(out, mcp, "saved.progress", GOAL + PNL)
    assert f"Europe: {T.fmt_rate(0.031)} this year against {T.fmt_rate(0.0412)} to date." in out.reply.text
    # India has a saved portfolio but no price after the save date yet: say so, with the date
    assert "India: no measured return yet, prices after 2026-03-02 are needed." in out.reply.text


def test_progress_passes_each_regions_own_goal_return_to_the_target_path(journey_db, fake_classifier):
    seen = []
    svc, mcp, sid = _chat(journey_db, GOALS_TWO, {"europe": EUROPE})
    orig = mcp.payloads["portfolio.pnl"]
    mcp.payloads["portfolio.pnl"] = lambda a: (seen.append((a["location"], a["goal_return"], a["source"])), orig(a))[1]
    _turn(svc, mcp, sid, "how am I doing", "europe")
    assert seen == [("europe", 0.0775, "saved"), ("india", 0.085, "saved"), ("us", None, "saved")]


# ── hedge ──────────────────────────────────────────────────────────────────────

def test_hedge_question_without_a_saved_hedge_plan_answers_from_plan_and_portfolio(journey_db, fake_classifier):
    svc, mcp, sid = _chat(journey_db, GOALS_TWO, {"europe": EUROPE, "india": INDIA}, hedge=None)
    out = _turn(svc, mcp, sid, "show my hedge plan", "europe")
    _check(out, mcp, "saved.progress", ["fno.get_hedge_plan"] + GOAL + PNL)
    assert "no saved hedge plan" not in out.reply.text.lower()
    assert "Europe:" in out.reply.text and out.reply.text.endswith("A hedge is built in FnO. Open it to review.")


def test_hedge_question_with_a_saved_hedge_plan_is_unchanged(journey_db, fake_classifier):
    plan = HedgePlanOut(key_id="k", hedged_ids=["E1", "E2"], coverage=50, scenario_tab="s", duration="d",
                        updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    svc, mcp, sid = _chat(journey_db, GOALS_TWO, {"europe": EUROPE}, hedge=plan)
    out = _turn(svc, mcp, sid, "show my hedge plan", "europe")
    _check(out, mcp, "show_hedge.plan", ["fno.get_hedge_plan"])
    assert out.reply.cards[0].kind == "hedge"


# ── the chat is read-only and journey-free ──────────────────────────────────────

def test_no_intent_ever_calls_a_journey_or_model_selection_tool(journey_db, fake_classifier):
    hedge = HedgePlanOut(key_id="k", hedged_ids=["E1"], coverage=50, scenario_tab="s", duration="d",
                         updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    svc, mcp, sid = _chat(journey_db, GOALS_TWO, {"europe": EUROPE, "india": INDIA}, hedge=hedge)
    called: set[str] = set()
    for text in INTENT_OF:
        out = _turn(svc, mcp, sid, text, "europe")
        assert out.journey is None, text
        called |= set(_tools(out))
    assert called == {"whatineed.get_goal", "portfolio.pnl", "fno.get_hedge_plan"}
    assert not [t for t in called if t.startswith(RETIRED_TOOLS_PREFIX)]


def test_every_reply_carries_the_same_fixed_chips(journey_db, fake_classifier):
    svc, mcp, sid = _chat(journey_db, GOALS_TWO, {"europe": EUROPE})
    expected = [(c["label"], c["text"]) for c in T.chips()]
    assert len(expected) == 4
    for text in ("hi", "use my goal", "build my portfolio", "blorp zzz"):
        out = _turn(svc, mcp, sid, text, "europe")
        assert [(c.label, c.text) for c in out.reply.chips] == expected, text


def test_the_chips_are_questions_the_chat_answers_from_saved_data():
    for _label, text in T.CHIPS:
        assert text in INTENT_OF and INTENT_OF[text] in SAVED_INTENTS


# ── routing contract ───────────────────────────────────────────────────────────

def test_saved_intents_cover_exactly_the_journey_vocabulary_and_each_target_exists():
    assert set(SAVED_INTENTS) == {"take_goal", "change_goal", "build_selection", "why_this_pick", "cant_reach",
                                  "track", "confirm", "decline", "progress", "what_if_sl", "show_hedge"}
    for intent, handler in SAVED_INTENTS.items():
        assert callable(getattr(JarvisChatService, handler)), (intent, handler)


def test_every_classifier_intent_has_a_handler():
    """An intent the classifier can return but nothing handles would raise AttributeError mid-conversation."""
    for name in ji.INTENT_NAMES:
        handler = SAVED_INTENTS.get(name, f"_i_{name}")
        assert callable(getattr(JarvisChatService, handler, None)), name
    assert WN_INTENTS <= set(ji.INTENT_NAMES) and "help" in ji.INTENT_NAMES


def test_no_retired_journey_code_is_left_in_the_chat_service():
    import inspect

    from rita.services import jarvis_chat_service as mod

    src = inspect.getsource(mod)
    for dead in ("_i_build_selection", "_i_track", "_i_confirm", "_progress_card", "_proposal_reply",
                 "journey.save", "state_prompt", "_ACCEPTED_JOURNEY", "select_for_goal", "sleeve_trace"):
        assert dead not in src, dead


def test_templates_are_the_saved_data_set_and_carry_no_forbidden_word():
    keys = ["saved.plan", "saved.plan.none", "saved.portfolio", "saved.portfolio.line", "saved.portfolio.none",
            "saved.progress", "saved.progress.line", "saved.progress.line_none", "saved.hedge.pointer"]
    for k in keys:
        assert k in T.TEMPLATES, k
    for k, v in T.TEMPLATES.items():
        assert "corpus" not in v.lower(), k
        assert not k.startswith(("take_goal.", "build.", "why.", "track.", "progress.", "what_if_sl.", "confirm.",
                                 "decline.", "state_prompt.", "notice.")), f"retired template back: {k}"
    assert "show_hedge.none" not in T.TEMPLATES                      # the handler never says "no hedge plan" now
    assert "{n}" not in T.TEMPLATES["saved.plan"] and "{n}" not in T.TEMPLATES["saved.portfolio"]   # no computed counts
