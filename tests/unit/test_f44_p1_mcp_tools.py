"""F44 P1 — MCP bus: namespaced tools, dispatch (identity, access, error codes, logging),
in-memory client, stdio surface, legacy aliases (ADR-007, Spec_MCP_Server § F44 tool catalogue).

DoD items covered here:
- every P1 tool returns structured content matching its Pydantic output model; error codes
- no tool imports a router module or a repository; no tool has a ``user_id`` input
- in-memory client: a sync service can call ``whatineed.get_plan`` for its user; two concurrent
  requests get their own users' data; the sync bridge never blocks the event loop
- every call writes one ``mcp_calls`` row with transport / caller / user_id
- legacy aliases answer with the same Markdown as before (old renderers copied below)
"""
from __future__ import annotations

import ast
import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import rita.interfaces.mcp_tools as mt
from rita.database import Base
from rita.interfaces.mcp_auth import McpIdentity, identity_scope
from rita.interfaces.mcp_client import (
    McpCallError,
    McpRequestClient,
    identity_for,
    memory_client,
)
from rita.interfaces.tools import ToolSpec, set_session_factory
from rita.models.user import UserModel
from rita.models.user_hedge_plan import UserHedgePlanModel
from rita.models.user_portfolio_key import UserPortfolioKeyModel
from rita.schemas.mcp_tools import NoArgsIn
from rita.schemas.user_portfolio import HoldingItem

_SRC = Path(__file__).resolve().parents[2] / "src" / "rita"

P1_TOOLS = {
    "whatineed.get_plan", "portfolio.get_holdings", "portfolio.optimal_allocation",
    "fno.position_value", "fno.get_hedge_plan", "market.overview", "market.ask", "market.monitor",
}
ALIASES = {"ask_rita", "rita_market_overview", "rita_monitor"}
STDIO_TOOLS = {"portfolio.optimal_allocation", "market.overview", "market.ask"} | ALIASES


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def tool_db(tmp_path):
    """File SQLite DB (thread-safe across the worker threads tools run in) for every tool call."""
    engine = create_engine(f"sqlite:///{tmp_path / 'tools.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    set_session_factory(maker)
    try:
        yield maker
    finally:
        set_session_factory(None)
        engine.dispose()


@pytest.fixture
def calls():
    """Capture mcp_calls writes (the real logger is covered in test_logger_writes_new_columns)."""
    rows: list[dict] = []
    with patch.object(mt, "_log_call", side_effect=lambda **kw: rows.append(kw)):
        yield rows


def _seed_users(maker):
    from rita.services.retirement_plan_service import RetirementPlanService, default_plan
    from rita.services.user_portfolio_service import UserPortfolioService

    db = maker()
    try:
        for uid in ("alice", "bob", "opsuser"):
            db.add(UserModel(id=uid, can_access_ops=(uid == "opsuser")))
        db.commit()
        base = default_plan("europe").inputs
        RetirementPlanService(db).save("alice", base.model_copy(update={"ret": 60}), "europe")
        RetirementPlanService(db).save("bob", base.model_copy(update={"ret": 63}), "europe")
        UserPortfolioService(db).save(
            "alice",
            [HoldingItem(instrument_id="NIFTY", allocation_pct=60, shares=3, cash_eur=12.5),
             HoldingItem(instrument_id="ASML", allocation_pct=40, shares=1, cash_eur=4.0)],
            name="Alice PF", total_value_eur=10_000,
        )
        key = db.query(UserPortfolioKeyModel).filter_by(user_id="alice").one()
        db.add(UserHedgePlanModel(key_id=key.key_id, hedged_ids=["ASML"], coverage=60,
                                  scenario_tab="pp", duration="1y", last_step="save",
                                  updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
        db.commit()
    finally:
        db.close()


def _user(uid: str, ops: bool = False) -> UserModel:
    return UserModel(id=uid, can_access_ops=ops)


def _run(coro):
    return asyncio.run(coro)


async def _call(identity: McpIdentity, name: str, args: dict | None = None):
    async with memory_client(identity) as c:
        return await c.call(name, args or {})


async def _raw(identity: McpIdentity, name: str, args: dict | None = None):
    """Raw CallToolResult (keeps isError / structuredContent) over an in-memory session."""
    with identity_scope(identity):
        async with create_connected_server_and_client_session(mt.server) as s:
            return await s.call_tool(name, args or {})


def _fake_classify():
    from rita.core.classifier import INTENTS, IntentResult

    return IntentResult(intent=INTENTS[0], confidence=0.87, low_confidence=False)


# ── catalogue + import rules ───────────────────────────────────────────────────

def test_registry_has_p1_tools_and_aliases():
    assert set(mt.REGISTRY) == P1_TOOLS | ALIASES
    assert mt.tools_registered() == 11


def test_no_tool_has_a_user_id_input():
    async def go():
        async with memory_client(identity_for(_user("alice"), "jarvis")) as c:
            return await c.list_tools()
    tools = _run(go())
    assert {t.name for t in tools} == P1_TOOLS | ALIASES
    for t in tools:
        props = (t.inputSchema or {}).get("properties", {})
        assert "user_id" not in props, t.name
        assert "user_id" not in json.dumps(t.inputSchema), t.name


def test_output_schemas_present_for_namespaced_tools():
    for name, spec in mt.REGISTRY.items():
        schema = spec.output_json_schema()
        if name in ALIASES:
            assert schema is None
        else:
            assert schema and schema.get("type") == "object", name


def test_tool_modules_import_no_router_or_repository():
    """Static (AST) + runtime check over rita.interfaces.tools.* (ADR-007 §2)."""
    tools_dir = _SRC / "interfaces" / "tools"
    files = sorted(tools_dir.glob("*.py"))
    assert len(files) >= 6
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for m in mods:
                assert not m.startswith(("rita.api", "rita.repositories")), f"{f.name} imports {m}"
    import importlib
    for f in files:
        mod = importlib.import_module(f"rita.interfaces.tools.{f.stem}" if f.stem != "__init__" else "rita.interfaces.tools")
        for val in vars(mod).values():
            origin = getattr(val, "__module__", "") or getattr(val, "__name__", "")
            assert not str(origin).startswith(("rita.api", "rita.repositories")), f"{f.name}: {origin}"


def test_extra_user_id_argument_is_invalid_input():
    with pytest.raises(McpCallError) as e:
        _run(_call(identity_for(_user("alice"), "jarvis"), "portfolio.get_holdings", {"user_id": "bob"}))
    assert e.value.code == "invalid_input"


# ── structured outputs ─────────────────────────────────────────────────────────

def _assert_matches_schema(name: str, structured: dict):
    jsonschema.validate(structured, mt.REGISTRY[name].output_json_schema())
    mt.REGISTRY[name].output_model.model_validate(structured)


def test_whatineed_get_plan_is_per_user(tool_db, calls):
    _seed_users(tool_db)
    a = _run(_call(identity_for(_user("alice"), "jarvis"), "whatineed.get_plan"))
    b = _run(_call(identity_for(_user("bob"), "jarvis"), "whatineed.get_plan", {"location": "europe"}))
    for r in (a, b):
        _assert_matches_schema("whatineed.get_plan", r.structured)
        assert r.structured["saved"] is True and r.structured["currency"] == "EUR"
    assert a.structured["result"]["retire_age"] == 60
    assert b.structured["result"]["retire_age"] == 63
    india = _run(_call(identity_for(_user("alice"), "jarvis"), "whatineed.get_plan", {"location": "india"}))
    assert india.structured["saved"] is False and india.structured["currency"] == "INR"
    with pytest.raises(McpCallError) as e:
        _run(_call(identity_for(_user("alice"), "jarvis"), "whatineed.get_plan", {"location": "mars"}))
    assert e.value.code == "invalid_input"
    # summaries: no amounts / personal figures
    for row in calls:
        assert "need" not in row["result_summary"] and "portfolio_at" not in row["result_summary"]


def test_portfolio_get_holdings(tool_db, calls):
    _seed_users(tool_db)
    r = _run(_call(identity_for(_user("alice"), "module:fno"), "portfolio.get_holdings"))
    _assert_matches_schema("portfolio.get_holdings", r.structured)
    s = r.structured
    assert s["name"] == "Alice PF" and s["currency"] == "EUR" and s["location"] is None
    assert s["total_value"] == 10_000
    assert [(h["instrument_id"], h["shares"], h["cash"]) for h in s["holdings"]] == [
        ("NIFTY", 3, 12.5), ("ASML", 1, 4.0)]
    with pytest.raises(McpCallError) as e:
        _run(_call(identity_for(_user("bob"), "module:fno"), "portfolio.get_holdings"))
    assert e.value.code == "not_found"
    assert calls[-1]["status"] == "error" and calls[-1]["result_summary"].startswith("not_found")


def test_portfolio_optimal_allocation(tool_db):
    from rita.schemas.portfolio_optimizer import OptimalAllocationResponse

    fake = OptimalAllocationResponse(horizon="long_term", instrument_count=0, solver_status="NO_INSTRUMENTS",
                                     estimated_sharpe=0.0, estimated_mdd_pct=0.0, allocations=[])
    with patch("rita.services.optimal_allocation_service.optimize_allocation", return_value=fake) as opt:
        r = _run(_call(identity_for(None, "external"), "portfolio.optimal_allocation", {"horizon": "long_term"}))
    _assert_matches_schema("portfolio.optimal_allocation", r.structured)
    assert r.structured["solver_status"] == "NO_INSTRUMENTS"
    opt.assert_called_once()
    with pytest.raises(McpCallError) as e:
        _run(_call(identity_for(None, "external"), "portfolio.optimal_allocation", {"horizon": "forever"}))
    assert e.value.code == "invalid_input"


def test_fno_position_value_and_hedge_plan(tool_db):
    _seed_users(tool_db)
    ident = identity_for(_user("alice"), "jarvis")
    pv = _run(_call(ident, "fno.position_value", {"months": 6}))
    _assert_matches_schema("fno.position_value", pv.structured)
    assert {i["instrument_id"] for i in pv.structured["items"]} == {"NIFTY", "ASML"}
    assert "lot_size" not in json.dumps(pv.structured)

    hp = _run(_call(ident, "fno.get_hedge_plan"))
    _assert_matches_schema("fno.get_hedge_plan", hp.structured)
    assert hp.structured["hedged_ids"] == ["ASML"] and hp.structured["coverage"] == 60
    with pytest.raises(McpCallError) as e:
        _run(_call(identity_for(_user("bob"), "jarvis"), "fno.get_hedge_plan"))
    assert e.value.code == "not_found"
    with pytest.raises(McpCallError) as e:
        _run(_call(ident, "fno.position_value", {"months": 99}))
    assert e.value.code == "invalid_input"


def test_market_overview_structured_and_not_found():
    from rita.core.data_understanding import find_instrument_csv

    try:
        find_instrument_csv("NIFTY")
    except FileNotFoundError:
        pytest.skip("no NIFTY price CSV in this checkout")
    r = _run(_call(identity_for(None, "jarvis"), "market.overview", {"instrument": "nifty"}))
    _assert_matches_schema("market.overview", r.structured)
    assert r.structured["instrument"] == "NIFTY" and r.structured["as_of"]
    assert set(r.structured["signals"]) == {"trend", "macd", "rsi", "bollinger", "volatility"}
    with pytest.raises(McpCallError) as e:
        _run(_call(identity_for(None, "jarvis"), "market.overview", {"instrument": "NOPE_XYZ"}))
    assert e.value.code == "invalid_input"  # well-formed but not a known instrument


def test_market_ask_structured(calls):
    import pandas as pd

    df = pd.DataFrame({"Close": [1.0]})
    with patch("rita.services.market_analysis_service.get_indicator_df", return_value=df), \
         patch("rita.core.classifier.classify", return_value=_fake_classify()), \
         patch("rita.core.classifier.dispatch", return_value="Answer text") as disp:
        r = _run(_call(identity_for(None, "jarvis"), "market.ask",
                       {"query": "Should I invest now?", "instrument": "NIFTY",
                        "portfolio_value": 2_000_000, "currency": "INR", "target_return": 0.12}))
    _assert_matches_schema("market.ask", r.structured)
    assert r.structured["answer"] == "Answer text" and r.structured["low_confidence"] is False
    kw = disp.call_args.kwargs
    assert kw["portfolio_inr"] == 2_000_000 and kw["target_return_pct"] == pytest.approx(12.0)
    # message text is never logged — only its length
    assert "invest" not in calls[-1]["args_summary"] and "query_len=" in calls[-1]["args_summary"]


def test_market_monitor_needs_ops():
    fake = ({"total_queries": 3}, [{"intent_name": "x", "count": 3}], [{"query_text": "q"}])
    with patch("rita.interfaces.tools.market.monitor_data", return_value=fake):
        r = _run(_call(identity_for(_user("opsuser", ops=True), "external"), "market.monitor"))
        _assert_matches_schema("market.monitor", r.structured)
        with pytest.raises(McpCallError) as e:
            _run(_call(identity_for(_user("alice"), "external"), "market.monitor"))
        assert e.value.code == "forbidden"
        with pytest.raises(McpCallError) as e:
            _run(_call(identity_for(_user("alice"), "external"), "rita_monitor"))
        assert e.value.code == "forbidden"


# ── error codes ────────────────────────────────────────────────────────────────

def test_user_tools_forbidden_without_user():
    for name in ("whatineed.get_plan", "portfolio.get_holdings", "fno.position_value", "fno.get_hedge_plan"):
        res = _run(_raw(identity_for(None, "jarvis"), name))
        assert res.isError and res.structuredContent["error"]["code"] == "forbidden", name


def test_unknown_tool_not_found():
    res = _run(_raw(identity_for(None, "jarvis"), "nope.tool"))
    assert res.isError and res.structuredContent["error"]["code"] == "not_found"


def test_unknown_tool_name_is_never_logged(calls):
    """Review #10: a client-sent unknown name (HTML / script, 500+ chars) is logged as the fixed
    ``unknown`` with only its length; the caller still gets the coded not_found."""
    evil = "<img src=x onerror=alert(1)><script>alert(2)</script>" + "A" * 500
    res = _run(_raw(identity_for(None, "jarvis"), evil, {"q": "<b>x</b>"}))
    assert res.isError and res.structuredContent["error"]["code"] == "not_found"
    assert len(calls) == 1
    row = calls[0]
    assert row["tool_name"] == mt.UNKNOWN_TOOL == "unknown"
    assert row["args_summary"] == f"name_len={len(evil)}"
    assert row["result_summary"] == "not_found: unknown tool"
    assert row["status"] == "error" and res.meta["mcp_call_id"] == row["call_id"]
    assert all("<" not in str(v) and "A" * 50 not in str(v) for v in row.values())


def test_registered_and_legacy_names_are_logged_as_is(calls):
    for name in ("market.overview", "rita_market_overview"):
        _run(_raw(identity_for(None, "jarvis"), name, {"instrument": "NOPE_XYZ"}))
    assert [c["tool_name"] for c in calls] == ["market.overview", "rita_market_overview"]


def test_tool_exception_is_unavailable_not_a_crash(tool_db, calls):
    with patch("rita.services.hedge_plan_service.HedgePlanService.get_for_user",
               side_effect=RuntimeError("db down")):
        res = _run(_raw(identity_for(_user("alice"), "jarvis"), "fno.get_hedge_plan"))
    assert res.isError
    assert res.structuredContent == {"error": {"code": "unavailable",
                                               "message": "fno.get_hedge_plan failed: RuntimeError"}}
    assert calls[-1]["status"] == "error"


def test_logger_failure_never_fails_the_tool():
    with patch.object(mt, "_log_call", side_effect=RuntimeError("log db gone")), \
         patch("rita.services.optimal_allocation_service.optimize_allocation", side_effect=RuntimeError("x")):
        r = _run(_call(identity_for(None, "jarvis"), "portfolio.optimal_allocation", {"horizon": "short_term"}))
    assert r.structured["solver_status"] == "ERROR"


# ── logging (transport / caller / user_id) ─────────────────────────────────────

def test_every_call_logs_transport_caller_user(tool_db, calls):
    _seed_users(tool_db)
    _run(_call(identity_for(_user("alice"), "jarvis"), "whatineed.get_plan"))
    _run(_call(identity_for(_user("bob"), "module:portfolio"), "whatineed.get_plan"))
    _run(_raw(McpIdentity(transport="sse", caller="external", user_id="alice"), "fno.get_hedge_plan"))
    _run(_raw(McpIdentity(transport="stdio", caller="external"), "whatineed.get_plan"))
    got = [(c["tool_name"], c["transport"], c["caller"], c["user_id"], c["status"]) for c in calls]
    assert got == [
        ("whatineed.get_plan", "memory", "jarvis", "alice", "ok"),
        ("whatineed.get_plan", "memory", "module:portfolio", "bob", "ok"),
        ("fno.get_hedge_plan", "sse", "external", "alice", "ok"),
        ("whatineed.get_plan", "stdio", "external", None, "error"),
    ]
    assert all(c["call_id"] for c in calls)


def test_call_result_carries_mcp_call_id(calls):
    with patch("rita.services.optimal_allocation_service.optimize_allocation", side_effect=RuntimeError("x")):
        r = _run(_call(identity_for(None, "jarvis"), "portfolio.optimal_allocation", {"horizon": "short_term"}))
    assert r.call_id == calls[-1]["call_id"]


def test_logger_writes_new_columns(tmp_path):
    from rita.core import mcp_logger
    from rita.core.mcp_logger import get_mcp_calls, log_mcp_call

    engine = create_engine(f"sqlite:///{tmp_path / 'log.db'}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    before = mcp_logger._session_factory[0]
    mcp_logger.set_session_factory(maker)
    try:
        cid = log_mcp_call("whatineed.get_plan", "location=europe", "saved=True", 3.2, "ok",
                           transport="memory", caller="jarvis", user_id="alice")
        rows = get_mcp_calls(5)
    finally:
        mcp_logger._session_factory[0] = before
    assert rows[0]["call_id"] == cid
    assert (rows[0]["transport"], rows[0]["caller"], rows[0]["user_id"]) == ("memory", "jarvis", "alice")
    engine.dispose()


def test_tests_never_log_into_the_dev_db(tool_db):
    """conftest points the logger at a temp DB; a tool fixture's reset restores that, not SessionLocal."""
    from rita.core import mcp_logger

    assert mcp_logger._session_factory[0] is not mcp_logger._default_session
    assert mcp_logger._session_factory[0] is tool_db  # tools + logger share the test DB
    set_session_factory(None)
    assert mcp_logger._session_factory[0] is not mcp_logger._default_session
    set_session_factory(tool_db)  # fixture teardown resets again


def test_dispatch_writes_real_log_row_to_test_db(tool_db):
    from rita.models.mcp_call import MCPCallModel

    with patch("rita.services.optimal_allocation_service.optimize_allocation", side_effect=RuntimeError("x")):
        r = _run(_call(identity_for(_user("alice"), "module:portfolio"), "portfolio.optimal_allocation",
                       {"horizon": "short_term"}))
    db = tool_db()
    try:
        row = db.get(MCPCallModel, r.call_id)
        assert (row.transport, row.caller, row.user_id, row.args_summary) == (
            "memory", "module:portfolio", "alice", "horizon=short_term")
    finally:
        db.close()


# ── review advisories: args allow-list, instrument ids, gate fails closed ──────

def test_args_summary_allow_list():
    out = mt._summarise_args({
        "query": "Should I sell everything, I owe 40k?", "instrument": "NIFTY", "location": "india",
        "portfolio_value": 2_500_000, "portfolio_inr": 1_000_000, "target_return": 0.12,
        "target_return_pct": 12.0, "value_now": 50_000, "goal_value": 900_000, "horizon": "long_term",
        "months": 6, "note": "free text", "ann_vol_pct": 18.5, "currency": "INR", "skip": None,
    })
    parts = out.split(", ")
    assert "query_len=36" in parts and "note_len=9" in parts
    for safe in ("instrument=NIFTY", "location=india", "horizon=long_term", "months=6", "currency=INR"):
        assert safe in parts
    for amount in ("portfolio_value", "portfolio_inr", "target_return", "target_return_pct", "value_now",
                   "goal_value", "ann_vol_pct"):
        assert amount in parts  # key only
    for leaked in ("2500000", "1000000", "0.12", "50000", "900000", "18.5", "owe", "free text", "skip"):
        assert leaked not in out


@pytest.mark.parametrize("bad", ["../NIFTY", "..", "NIFTY/../../etc", "NI FTY", "a" * 33, "%2e%2e"])
def test_instrument_path_like_ids_are_invalid_input(bad):
    for name in ("market.overview", "market.ask"):
        args = {"instrument": bad} if name == "market.overview" else {"instrument": bad, "query": "hi"}
        res = _run(_raw(identity_for(None, "jarvis"), name, args))
        assert res.isError and res.structuredContent["error"]["code"] == "invalid_input", (name, bad)


def test_loader_refuses_unknown_or_path_ids():
    from rita.services.market_analysis_service import get_indicator_df, is_known_instrument

    assert not is_known_instrument("../NIFTY") and not is_known_instrument("")
    with pytest.raises(FileNotFoundError):
        get_indicator_df("../NIFTY")
    with patch("rita.core.data_understanding.find_instrument_csv") as find:
        with pytest.raises(FileNotFoundError):
            get_indicator_df("NOT_A_REAL_TICKER")
    find.assert_not_called()


def test_jwt_gate_fails_closed_for_non_http_scopes():
    from rita.interfaces.mcp_auth import McpJwtGate

    seen, sent = [], []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    async def receive():
        return {"type": "websocket.connect"}

    async def send(msg):
        sent.append(msg)

    gate = McpJwtGate(inner, transport="http")
    asyncio.run(gate({"type": "websocket", "headers": [(b"authorization", b"Bearer x")]}, receive, send))
    assert seen == [] and sent == [{"type": "websocket.close", "code": 1008}]
    asyncio.run(gate({"type": "something-else"}, receive, send))
    assert seen == []
    asyncio.run(gate({"type": "lifespan"}, receive, send))
    assert seen == ["lifespan"]


# ── stdio surface ──────────────────────────────────────────────────────────────

def test_stdio_lists_only_userless_tools_and_aliases():
    async def go():
        with identity_scope(McpIdentity(transport="stdio", caller="external")):
            async with create_connected_server_and_client_session(mt.server) as s:
                return (await s.list_tools()).tools
    assert {t.name for t in _run(go())} == STDIO_TOOLS


def test_user_tool_over_stdio_is_forbidden():
    res = _run(_raw(McpIdentity(transport="stdio", caller="external"), "portfolio.get_holdings"))
    assert res.isError and res.structuredContent["error"]["code"] == "forbidden"


# ── legacy aliases: same Markdown as before F44 ────────────────────────────────

def _old_market_overview(instrument: str) -> str:
    """Pre-F44 mcp_tools._handle_market_overview, verbatim."""
    from rita.core.technical_analyzer import get_market_summary, get_sentiment_score
    from rita.services.market_analysis_service import get_indicator_df

    instrument = instrument.upper()
    df = get_indicator_df(instrument)
    summary = get_market_summary(df)
    scored = get_sentiment_score(summary)
    signals = scored["signals"]
    lines = [
        f"**{instrument} — Market Overview**",
        "",
        f"Sentiment:   **{scored['overall_sentiment']}** (score {scored['total_score']:+d}/6)",
        f"Trend:       {summary['trend']} (score {summary['trend_score']:+.3f})",
        f"RSI-14:      {summary['rsi_14']:.1f} — {summary['rsi_signal']}",
        f"ATR-14:      {summary['atr_14']:,.2f}  "
        f"(volatility at {summary['atr_percentile'] * 100:.0f}th percentile)",
        f"Bollinger:   {summary['bb_position']}  (bb%B {summary['bb_pct_b']:.2f})",
        f"EMA-50:      {summary['ema_50']:,.2f}   |   EMA-200: {summary['ema_200']:,.2f}",
        f"Close:       {summary['close']:,.2f} as of {summary['date']}",
        "",
        "**Signal breakdown:**",
        f"  Trend      {signals['trend']['value']:22s} ({signals['trend']['score']:+d})",
        f"  MACD       {signals['macd']['value']:22s} ({signals['macd']['score']:+d})",
        f"  RSI        {signals['rsi']['value']:22s} ({signals['rsi']['score']:+d})",
        f"  Bollinger  {signals['bollinger']['value']:22s} ({signals['bollinger']['score']:+d})",
        f"  Volatility {signals['volatility']['value']:22s} ({signals['volatility']['score']:+d})",
    ]
    return "\n".join(lines)


def _old_monitor(summary, recent, intents) -> str:
    """Pre-F44 mcp_tools._handle_monitor, verbatim (inputs injected)."""
    lines = [
        "**RITA Chat Monitor**",
        "",
        f"Total queries:     {summary.get('total_queries', 0)}",
        f"Avg latency:       {float(summary.get('avg_latency_ms', 0)):.1f} ms",
        f"Low confidence:    {float(summary.get('low_conf_pct', 0)):.1f}%",
        f"Queries today:     {summary.get('queries_today', 0)}",
        "",
        "**Intent distribution (top 5):**",
    ]
    for entry in (intents or [])[:5]:
        lines.append(f"  {entry.get('intent_name', '?'):28s} {entry.get('count', 0)} calls")
    lines += ["", "**Recent queries:**"]
    for r in (recent or []):
        ts = str(r.get("timestamp", ""))[:16]
        conf = float(r.get("confidence", 0))
        qtext = str(r.get("query_text", ""))[:60]
        lines.append(f"  [{ts}] {r.get('intent_name', '?'):22s} conf={conf:.2f}  {qtext}")
    return "\n".join(lines)


_STDIO = McpIdentity(transport="stdio", caller="external")


def test_legacy_market_overview_markdown_unchanged():
    from rita.core.data_understanding import find_instrument_csv

    try:
        find_instrument_csv("NIFTY")
    except FileNotFoundError:
        pytest.skip("no NIFTY price CSV in this checkout")
    res = _run(_raw(_STDIO, "rita_market_overview", {"instrument": "NIFTY"}))
    assert not res.isError and res.structuredContent is None
    assert res.content[0].text == _old_market_overview("NIFTY")


def test_legacy_monitor_markdown_unchanged_on_stdio():
    summary = {"total_queries": 47, "avg_latency_ms": 183.4, "low_conf_pct": 12.8, "queries_today": 9}
    intents = [{"intent_name": "market_sentiment", "count": 11}, {"intent_name": "invest_now", "count": 8}]
    recent = [{"timestamp": "2026-05-05T09:14:00", "intent_name": "invest_now", "confidence": "0.89",
               "query_text": "Should I invest in Nifty now?"}]
    with patch("rita.core.chat_monitor.get_summary", return_value=summary), \
         patch("rita.core.chat_monitor.get_recent_queries", return_value=recent), \
         patch("rita.core.chat_monitor.get_intent_distribution", return_value=intents), \
         patch.object(mt, "_log_call") as logged:
        res = _run(_raw(_STDIO, "rita_monitor"))
    assert res.content[0].text == _old_monitor(summary, recent, intents)
    # recent-query text is never written to mcp_calls
    assert "Should I invest" not in logged.call_args.kwargs["result_summary"]


def test_legacy_ask_rita_markdown_unchanged():
    import pandas as pd

    df = pd.DataFrame({"Close": [1.0]})
    res_ok = _fake_classify()
    with patch("rita.services.market_analysis_service.get_indicator_df", return_value=df), \
         patch("rita.core.classifier.classify", return_value=res_ok), \
         patch("rita.core.classifier.dispatch", return_value="Market sentiment: **X**."):
        res = _run(_raw(_STDIO, "ask_rita", {"query": "What is the sentiment?", "instrument": "NIFTY"}))
    expected = (f"**Instrument:** NIFTY\n**Intent:** {res_ok.intent.name} (confidence 0.87)"
                "\n\nMarket sentiment: **X**.")
    assert res.content[0].text == expected

    from rita.core.classifier import IntentResult
    low = IntentResult(intent=res_ok.intent, confidence=0.21, low_confidence=True)
    with patch("rita.services.market_analysis_service.get_indicator_df", return_value=df), \
         patch("rita.core.classifier.classify", return_value=low):
        res = _run(_raw(_STDIO, "ask_rita", {"query": "weather in Mumbai"}))
    assert res.content[0].text == (
        "**Instrument:** NIFTY\n**Intent:** uncertain (confidence 0.21 — below 0.42 threshold)"
        "\n\nRITA could not confidently match your question to a known intent. "
        "Try rephrasing, or ask about: market sentiment, RSI, volatility, "
        "return estimates (1m/3m/1y/3y), stress scenarios, or strategy allocation."
    )


def test_legacy_input_schemas_unchanged():
    ask = mt.REGISTRY["ask_rita"].input_json_schema()
    assert ask["required"] == ["query"]
    assert set(ask["properties"]) == {"query", "instrument", "portfolio_inr", "target_return_pct",
                                      "time_horizon_days"}
    assert mt.REGISTRY["rita_market_overview"].input_json_schema()["properties"]["instrument"]["enum"] == [
        "NIFTY", "BANKNIFTY", "ASML", "NVIDIA"]


# ── in-memory client: sync bridge, per-request identity, event loop ────────────

def test_sync_service_calls_whatineed_for_its_user(tool_db):
    _seed_users(tool_db)

    def portfolio_service_step(user):  # what a sync service would do
        with McpRequestClient(identity_for(user, "module:portfolio")) as mcp:
            first = mcp.call("whatineed.get_plan")
            second = mcp.call("whatineed.get_plan", {"location": "europe"})  # same session reused
            return first.structured, second.structured

    a1, a2 = portfolio_service_step(_user("alice"))
    assert a1["result"]["retire_age"] == 60 == a2["result"]["retire_age"]


def test_two_concurrent_requests_get_their_own_users(tool_db, calls):
    _seed_users(tool_db)
    barrier = threading.Barrier(2)
    out: dict[str, list[int]] = {}
    errors: list[BaseException] = []

    def request(uid: str):
        try:
            with McpRequestClient(identity_for(_user(uid), "jarvis")) as mcp:
                barrier.wait(timeout=30)
                ages = [mcp.call("whatineed.get_plan").structured["result"]["retire_age"] for _ in range(3)]
            out[uid] = ages
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=request, args=(u,)) for u in ("alice", "bob")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not errors, errors
    assert out == {"alice": [60, 60, 60], "bob": [63, 63, 63]}
    by_user = {(c["user_id"], c["transport"]) for c in calls}
    assert by_user == {("alice", "memory"), ("bob", "memory")}


@pytest.fixture
def slow_tool():
    def handler(_inp, _ctx):
        time.sleep(0.4)
        return "slow done"
    spec = ToolSpec(name="test.slow", description="test", input_model=NoArgsIn, handler=handler,
                    auth=frozenset({"none"}))
    mt.REGISTRY[spec.name] = spec
    try:
        yield spec
    finally:
        mt.REGISTRY.pop(spec.name, None)


def test_sync_bridge_does_not_block_event_loop(slow_tool, calls):
    """A sync caller in a worker thread + a slow (sync) tool: the event loop keeps ticking."""
    import anyio

    async def main():
        ticks = 0
        stop = asyncio.Event()

        async def ticker():
            nonlocal ticks
            while not stop.is_set():
                ticks += 1
                await asyncio.sleep(0.01)

        def sync_caller():
            with McpRequestClient(identity_for(None, "jarvis")) as mcp:
                return mcp.call("test.slow").text

        t = asyncio.create_task(ticker())
        text = await anyio.to_thread.run_sync(sync_caller)
        # and the async client: the slow handler runs in a worker thread, not on this loop
        before = ticks
        async with memory_client(identity_for(None, "jarvis")) as c:
            r = await c.call("test.slow")
        during_async = ticks - before
        stop.set()
        await t
        return text, r.text, ticks, during_async

    text, text2, ticks, during_async = asyncio.run(main())
    assert text == "slow done" == text2
    assert ticks > 20 and during_async > 10


def test_sync_client_refuses_the_event_loop_thread():
    async def main():
        with McpRequestClient(identity_for(None, "jarvis")):
            pass
    with pytest.raises(RuntimeError, match="worker thread"):
        asyncio.run(main())


def test_identity_for_validates_caller():
    assert identity_for(None, "module:fno").caller == "module:fno"
    for bad in ("assistant", "module:", "Module:X", ""):
        with pytest.raises(ValueError):
            identity_for(None, bad)
