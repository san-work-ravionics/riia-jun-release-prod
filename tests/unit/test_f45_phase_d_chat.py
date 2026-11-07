"""F45 Phase D — Jarvis chat intents for the portfolio tracker.

``wn_on_track`` · ``wn_bucket_status`` · ``wn_hedge_signal`` · ``wn_what_needs_hedging`` over the
``whatineed.bucket_status`` tool.  The orchestrator runs against the same fake in-memory MCP client as
the F44 P4 golden tests (the classifier is a lookup, so the set is deterministic; the real MiniLM is
covered by ``test_f44_p4_intents``).  Every reply is also checked for **number provenance**: each
number is a formatted tool field.
"""
# ruff: noqa: F811 — pytest fixtures imported from a sibling module are redefined as test params
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from rita.core import journey_intents as ji
from rita.core.journey_intents import JourneyIntentResult
from rita.core.journey_slots import parse_slots
from rita.schemas.jarvis import CARD_KINDS
from rita.schemas.mcp_tools import BucketInstrumentStatus, BucketStatus, BucketStatusOut
from rita.services import jarvis_chat_service as C
from rita.services.jarvis_chat_service import JarvisChatService

from .f44_p4_helpers import journey_db  # noqa: F401 — fixture
from .test_f44_p4_golden import FakeMcp, User, _session, _turn, assert_numbers_from_tools

INTENT_OF = {
    "am I on track for my retirement": "wn_on_track",
    "how is my index doing": "wn_bucket_status",
    "how is my equity doing": "wn_bucket_status",
    "how is my bucket doing": "wn_bucket_status",
    "do I need to hedge": "wn_hedge_signal",
    "what needs hedging": "wn_what_needs_hedging",
}
TOOLS = ["journey.get_current", "whatineed.bucket_status"]


@pytest.fixture
def fake_classifier(monkeypatch):
    def classify(text, threshold):
        return JourneyIntentResult(intent=INTENT_OF[text], confidence=0.93, low_confidence=False)

    monkeypatch.setattr(ji, "classify_journey", classify)


def bucket(key, ytd=None, ttd=0.0412, at_risk=None, instruments=("E1",), monthly=400.0):
    gap = None if ytd is None else round(ytd - ttd, 6)
    insts = [BucketInstrumentStatus(instrument_id=i, allocation_pct=20.0, ytd_return=ytd) for i in instruments]
    return BucketStatus(key=key, target_rate=0.10, target_to_date=ttd, ytd_return=ytd, gap=gap,
                        at_risk=at_risk, monthly_target=monthly, instruments=insts)


def status(buckets, saved=True, location="europe") -> BucketStatusOut:
    return BucketStatusOut(
        location=location, currency="EUR", saved=saved, at_risk_threshold=-0.02, n_buckets=len(buckets),
        n_at_risk=sum(1 for b in buckets if b.at_risk is True),
        n_on_track=sum(1 for b in buckets if b.at_risk is False),
        n_no_data=sum(1 for b in buckets if b.at_risk is None), buckets=buckets)


def ask(journey_db, payload, text, location="europe"):
    mcp = FakeMcp(journey_db, {"whatineed.bucket_status": payload})
    svc = JarvisChatService(journey_db, mcp, User())
    sid = _session(svc, location)
    out = _turn(svc, mcp, sid, text, location)
    return out, mcp


def check(out, mcp, template, tools=TOOLS):
    r = out.reply
    assert r.template_id == f"{template}.v1", (r.template_id, r.text)
    assert [c.tool for c in r.tool_calls] == tools
    assert [c.mcp_call_id for c in r.tool_calls] == mcp.ids
    assert_numbers_from_tools(r.text, mcp.results)
    return r


RISKY = [bucket("idx", ytd=0.052, at_risk=False), bucket("eq", ytd=-0.03, at_risk=True, instruments=("E1", "E2")),
         bucket("com", instruments=()), bucket("alt", instruments=())]
FINE = [bucket("idx", ytd=0.052, at_risk=False), bucket("eq", ytd=0.045, at_risk=False),
        bucket("com", instruments=()), bucket("alt", instruments=())]
NO_DATA = [bucket("idx", instruments=()), bucket("eq"), bucket("com", instruments=()), bucket("alt", instruments=())]


# ── wn_on_track ─────────────────────────────────────────────────────────────────

def test_on_track_all_measured_buckets_ok(journey_db, fake_classifier):
    out, mcp = ask(journey_db, status(FINE), "am I on track for my retirement")
    r = check(out, mcp, "wn.on_track.ok")
    assert r.cards[0].kind == "bucket_progress"
    assert r.cards[0].data.n_on_track == 2 and r.cards[0].data.n_at_risk == 0
    assert [b.key for b in r.cards[0].data.buckets] == ["idx", "eq", "com", "alt"]


def test_on_track_names_the_at_risk_buckets(journey_db, fake_classifier):
    out, mcp = ask(journey_db, status(RISKY), "am I on track for my retirement")
    r = check(out, mcp, "wn.on_track.risk")
    assert "so far: Equity." in r.text
    assert r.cards[0].data.n_at_risk == 1


def test_on_track_without_data_says_so_not_on_track(journey_db, fake_classifier):
    out, mcp = ask(journey_db, status(NO_DATA), "am I on track for my retirement")
    r = check(out, mcp, "wn.no_data")
    assert "on track" not in r.text.lower()


def test_on_track_no_saved_plan(journey_db, fake_classifier):
    out, mcp = ask(journey_db, status([], saved=False), "am I on track for my retirement")
    r = check(out, mcp, "wn.no_plan")
    assert "Europe" in r.text and r.cards == []


# ── wn_bucket_status ────────────────────────────────────────────────────────────

def test_bucket_status_at_risk_names_bucket_and_points_to_fno(journey_db, fake_classifier):
    out, mcp = ask(journey_db, status(RISKY), "how is my equity doing")
    r = check(out, mcp, "wn.bucket.risk")
    assert r.text.startswith("Equity:") and "FnO" in r.text
    assert r.cards[0].kind == "bucket_status"
    assert r.cards[0].data.key == "eq" and r.cards[0].data.instruments == ["E1", "E2"]


def test_bucket_status_on_track(journey_db, fake_classifier):
    out, mcp = ask(journey_db, status(FINE), "how is my index doing")
    r = check(out, mcp, "wn.bucket.ok")
    assert r.text.startswith("Index fund:") and r.cards[0].data.at_risk is False


def test_bucket_status_with_no_holdings_is_not_a_status(journey_db, fake_classifier):
    out, mcp = ask(journey_db, status(NO_DATA), "how is my index doing")
    r = check(out, mcp, "wn.bucket.empty")
    assert "Index fund" in r.text and r.cards[0].data.instruments == []


def test_bucket_status_with_holdings_but_no_prices(journey_db, fake_classifier):
    out, mcp = ask(journey_db, status(NO_DATA), "how is my equity doing")
    r = check(out, mcp, "wn.bucket.no_data")
    assert r.text.startswith("Equity:")


def test_bucket_status_without_a_named_bucket_asks_which_and_calls_no_tool(journey_db, fake_classifier):
    out, mcp = ask(journey_db, status(FINE), "how is my bucket doing")
    r = check(out, mcp, "wn.bucket.which", tools=["journey.get_current"])
    assert r.cards == []


# ── wn_hedge_signal / wn_what_needs_hedging ─────────────────────────────────────

def test_hedge_signal_none_when_nothing_at_risk(journey_db, fake_classifier):
    out, mcp = ask(journey_db, status(FINE), "do I need to hedge")
    r = check(out, mcp, "wn.hedge.none")
    assert r.cards[0].kind == "hedge_signal" and r.cards[0].data.all_on_track is True
    assert r.cards[0].data.at_risk_buckets == []


def test_hedge_signal_lists_at_risk_and_links_fno_without_computing_a_hedge(journey_db, fake_classifier):
    out, mcp = ask(journey_db, status(RISKY), "do I need to hedge")
    r = check(out, mcp, "wn.hedge.signal")
    assert "Equity" in r.text and "doesn't compute" in r.text
    assert r.cards[0].data.at_risk_buckets == ["eq"] and r.cards[0].data.all_on_track is False
    assert r.cards[0].data.fno_link == "/dashboard/fno.html"


def test_what_needs_hedging_gives_one_line_per_bucket(journey_db, fake_classifier):
    two = [bucket("idx", ytd=-0.04, at_risk=True), bucket("eq", ytd=-0.03, at_risk=True), bucket("com", instruments=()),
           bucket("alt", instruments=())]
    out, mcp = ask(journey_db, status(two), "what needs hedging")
    r = check(out, mcp, "wn.hedge.list")
    assert "Index fund:" in r.text and "Equity:" in r.text
    assert r.cards[0].data.at_risk_buckets == ["idx", "eq"]


def test_what_needs_hedging_with_nothing_at_risk(journey_db, fake_classifier):
    out, mcp = ask(journey_db, status(FINE), "what needs hedging")
    check(out, mcp, "wn.hedge.none")


def test_hedge_without_data_does_not_claim_all_clear(journey_db, fake_classifier):
    out, mcp = ask(journey_db, status(NO_DATA), "do I need to hedge")
    r = check(out, mcp, "wn.no_data")
    assert r.cards[0].data.all_on_track is False


# ── failure + wiring ────────────────────────────────────────────────────────────

def test_tool_down_gives_the_unavailable_reply(journey_db, fake_classifier):
    out, mcp = ask(journey_db, None, "am I on track for my retirement")
    assert out.reply.template_id == "error.unavailable.v1"
    assert "whatineed.bucket_status" in out.reply.text


def test_every_journey_state_accepts_the_four_intents():
    assert C.WN_INTENTS == {"wn_on_track", "wn_bucket_status", "wn_hedge_signal", "wn_what_needs_hedging"}
    assert all(C.WN_INTENTS <= accepted for accepted in C.ACCEPTED.values())
    assert set(C.ACCEPTED) == set(C._ACCEPTED_JOURNEY)


def test_every_intent_has_a_handler_and_templates_exist():
    from rita.services import jarvis_templates as T

    for intent in C.WN_INTENTS:
        assert callable(getattr(JarvisChatService, f"_i_{intent}"))
    for key in ("wn.no_plan", "wn.no_data", "wn.on_track.ok", "wn.on_track.risk", "wn.bucket.which",
                "wn.bucket.empty", "wn.bucket.no_data", "wn.bucket.ok", "wn.bucket.risk", "wn.hedge.none",
                "wn.hedge.signal", "wn.hedge.list", "wn.hedge.line"):
        assert key in T.TEMPLATES
    assert set(T.BUCKET_LABELS) == {"idx", "eq", "com", "alt"}


def test_new_card_kinds_are_registered():
    assert {"bucket_progress", "bucket_status", "hedge_signal"} <= set(CARD_KINDS) and len(CARD_KINDS) == 13


def test_replies_never_use_the_word_corpus():
    from rita.services import jarvis_templates as T

    assert not [k for k, v in T.TEMPLATES.items() if "corpus" in v.lower()]


# ── bucket slot ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,key", [
    ("how is my index doing", "idx"), ("show the indices", "idx"), ("how are my equities doing", "eq"),
    ("show the equity bucket", "eq"), ("how are my commodities", "com"), ("my commodity bucket", "com"),
    ("how are the alternates doing", "alt"), ("show alternative investments", "alt"),
    ("how am I doing", None), ("do I need to hedge", None),
])
def test_bucket_slot(text, key):
    assert parse_slots(text).bucket == key


# ── the MCP tool ────────────────────────────────────────────────────────────────

def _page_out(saved=True, breakdown=()):
    return NS(plan=NS(saved=saved, location="europe", currency="EUR"), bucket_breakdown=list(breakdown))


def _bb(key, at_risk, ytd=0.01, ttd=0.04):
    return NS(key=key, target_rate=0.1, target_to_date=ttd, ytd_return=ytd, gap=None if ytd is None else ytd - ttd,
              at_risk=at_risk, monthly_target=400.0,
              instruments=[NS(instrument_id="E1", allocation_pct=20.0, ytd_return=ytd)])


@pytest.fixture
def tool_env(monkeypatch):
    """Run the tool handler without opening a real MCP session or DB."""
    import rita.interfaces.mcp_client as mc
    import rita.services.jarvis_page_service as ps
    from rita.interfaces.mcp_auth import McpIdentity
    from rita.interfaces.tools import ToolContext
    from rita.models.user import UserModel

    @contextmanager
    def fake_client(_identity):
        yield object()

    class FakeSession:
        def close(self):
            pass

    monkeypatch.setattr(mc, "McpRequestClient", fake_client)
    monkeypatch.setattr("rita.interfaces.tools._base._session_factory", [FakeSession])
    holder = {"out": _page_out()}
    monkeypatch.setattr(ps.JarvisPageService, "__init__", lambda self, db, mcp, user: None)
    monkeypatch.setattr(ps.JarvisPageService, "retirement_plan", lambda self, location: holder["out"])
    ident = McpIdentity.from_user(UserModel(id="alice"), transport="memory", caller="jarvis")
    return NS(ctx=ToolContext(identity=ident), holder=holder)


def test_tool_counts_and_threshold(tool_env):
    from rita.interfaces.tools.whatineed import bucket_status
    from rita.schemas.mcp_tools import BucketStatusIn

    tool_env.holder["out"] = _page_out(breakdown=[_bb("idx", False), _bb("eq", True), _bb("com", None, ytd=None),
                                                  _bb("alt", None, ytd=None)])
    out = bucket_status(BucketStatusIn(location="europe"), tool_env.ctx)
    assert (out.n_buckets, out.n_at_risk, out.n_on_track, out.n_no_data) == (4, 1, 1, 2)
    assert out.at_risk_threshold == -0.02 and out.saved and out.currency == "EUR"
    assert [b.key for b in out.buckets] == ["idx", "eq", "com", "alt"]
    assert out.buckets[1].instruments[0].instrument_id == "E1"


def test_tool_without_a_saved_plan_returns_no_buckets(tool_env):
    from rita.interfaces.tools.whatineed import bucket_status
    from rita.schemas.mcp_tools import BucketStatusIn

    tool_env.holder["out"] = _page_out(saved=False)
    out = bucket_status(BucketStatusIn(location="europe"), tool_env.ctx)
    assert out.saved is False and out.buckets == [] and out.n_buckets == 0


def test_tool_is_registered_user_only_and_forbids_user_id():
    import json

    import rita.interfaces.mcp_tools as mt
    from rita.schemas.mcp_tools import BucketStatusIn

    spec = mt.REGISTRY["whatineed.bucket_status"]
    assert spec.auth == frozenset({"user"}) and spec.output_json_schema() is not None
    assert "user_id" not in json.dumps(spec.input_json_schema())
    with pytest.raises(ValidationError):
        BucketStatusIn(location="europe", user_id="bob")
    with pytest.raises(ValidationError):
        BucketStatusIn(location="mars")
