"""F44 P3 — the four goal-driven MCP tools (``whatineed.get_goal``, ``portfolio.select_for_goal``,
``portfolio.required_return``, ``portfolio.model_runs``).

DoD items covered: 4 tools with output schemas and coded errors; no ``user_id`` input; user +
system auth, JWT over HTTP, none on stdio; the three portfolio tools never call
``ctx.require_user()``; allow-list logging (``year_start`` value; rates / counts bare keys;
``result_summary`` never carries a return); registry and ``/health`` = 16; no network.
"""
from __future__ import annotations

import asyncio
import json
import socket
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import rita.interfaces.mcp_tools as mt
import rita.services.goal_selection_service as svc_mod
from rita.auth import create_access_token
from rita.database import Base
from rita.interfaces.mcp_auth import McpIdentity, identity_scope
from rita.interfaces.tools import ToolContext, set_session_factory
from rita.models.instrument import InstrumentModel
from rita.models.user import UserModel
from rita.repositories.model_artifact import ModelArtifactRepository
from rita.repositories.model_run_cache import ModelRunCacheRepository

from .f44_p3_helpers import FakeArtifacts, PolicyModel, indicator_frame

P3_TOOLS = {"whatineed.get_goal", "portfolio.select_for_goal", "portfolio.required_return",
            "portfolio.model_runs"}
SYSTEM = McpIdentity(transport="memory", caller="system")
ALICE = McpIdentity(transport="memory", caller="jarvis", user_id="alice")
STDIO = McpIdentity(transport="stdio", caller="external")


@pytest.fixture
def tool_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tools.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    db = maker()
    db.add(UserModel(id="alice"))
    for inst, cc in (("E1", "NL"), ("E2", "NL"), ("E3", "NL"), ("U1", "US")):
        db.add(InstrumentModel(instrument_id=inst, name=inst, exchange="X", country_code=cc,
                               is_available=True, created_at=datetime.now(timezone.utc)))
    db.commit()
    db.close()
    set_session_factory(maker)
    try:
        yield maker
    finally:
        set_session_factory(None)
        engine.dispose()


@pytest.fixture
def fake_models(tmp_path, monkeypatch):
    fa = FakeArtifacts()
    fa.frames = {i: indicator_frame(seed=n, drift=0.0003 + 0.0002 * n, end="2026-06-30")
                 for n, i in enumerate(("E1", "E2", "E3"))}
    fa.models = {"E1": PolicyModel(), "E2": PolicyModel()}
    monkeypatch.setattr(ModelArtifactRepository, "from_settings", classmethod(lambda cls: fa))
    monkeypatch.setattr(ModelRunCacheRepository, "from_settings",
                        classmethod(lambda cls: ModelRunCacheRepository(tmp_path / "cache")))
    svc_mod.clear_memo()
    yield fa
    svc_mod.clear_memo()


@pytest.fixture
def calls():
    rows: list[dict] = []
    with patch.object(mt, "_log_call", side_effect=lambda **kw: rows.append(kw)):
        yield rows


async def _raw(identity, name, args=None):
    with identity_scope(identity):
        async with create_connected_server_and_client_session(mt.server) as s:
            return await s.call_tool(name, args or {})


def _call(identity, name, args=None):
    return asyncio.run(_raw(identity, name, args))


def _err(res):
    assert res.isError, res
    return res.structuredContent["error"]["code"]


# ── catalogue ──────────────────────────────────────────────────────────────────

def test_registry_has_16_tools_with_schemas_and_no_user_id():
    assert P3_TOOLS <= set(mt.REGISTRY) and mt.tools_registered() == 16
    for name in P3_TOOLS:
        spec = mt.REGISTRY[name]
        assert spec.output_json_schema() is not None and not spec.stdio
        assert spec.auth == frozenset({"user", "system"})
        assert "user_id" not in json.dumps(spec.input_json_schema())


def test_year_start_is_allow_listed_and_rates_are_not():
    assert "year_start" in mt.SAFE_ARG_KEYS
    for k in ("target_return", "goal_return", "ytd_return", "reselections_used"):
        assert k not in mt.SAFE_ARG_KEYS


@pytest.mark.parametrize("name,args", [
    ("portfolio.select_for_goal", {"location": "europe", "target_return": 0.07, "user_id": "x"}),
    ("portfolio.select_for_goal", {"location": "mars", "target_return": 0.07}),
    ("portfolio.select_for_goal", {"location": "europe", "target_return": 3.0}),
    ("portfolio.required_return", {"location": "europe", "goal_return": 0.07, "ytd_return": -1.0,
                                   "as_of": "2026-06-30", "year_start": "2026-01-01"}),
    ("portfolio.model_runs", {"location": "europe", "user_id": "alice"}),
    ("whatineed.get_goal", {"location": "atlantis"}),
])
def test_bad_input_is_invalid_input(tool_db, name, args):
    assert _err(_call(ALICE, name, args)) == "invalid_input"


# ── auth ───────────────────────────────────────────────────────────────────────

def test_get_goal_needs_a_user(tool_db):
    assert _err(_call(SYSTEM, "whatineed.get_goal", {})) == "forbidden"
    res = _call(ALICE, "whatineed.get_goal", {"location": "europe"})
    assert not res.isError and res.structuredContent["saved"] is False
    assert res.structuredContent["goal_return"] is None


def test_portfolio_tools_answer_the_system_identity_without_require_user(tool_db, fake_models):
    def refuse(self):
        raise AssertionError("portfolio goal tools must not call require_user")

    with patch.object(ToolContext, "require_user", refuse):
        sel = _call(SYSTEM, "portfolio.select_for_goal", {"location": "europe", "target_return": 0.03})
        req = _call(SYSTEM, "portfolio.required_return", {
            "location": "europe", "goal_return": 0.07, "ytd_return": 0.2,
            "as_of": "2026-06-30", "year_start": "2026-01-01"})
        runs = _call(SYSTEM, "portfolio.model_runs", {"location": "europe"})
    assert not sel.isError and sel.structuredContent["lineage"] == "f34p25"
    assert sel.structuredContent["method"]["weights"].endswith("(not a model)")
    assert req.structuredContent["status"] == "on_track"
    assert [i["instrument_id"] for i in runs.structuredContent["instruments"]] == ["E1", "E2"]
    assert runs.structuredContent["excluded"] == [
        {"instrument_id": "E3", "reason": "no_model", "detail": "no f34p25 model"}]


def test_anonymous_caller_is_forbidden(tool_db):
    anon = McpIdentity(transport="memory", caller="external")
    for name in P3_TOOLS:
        assert _err(_call(anon, name, {"location": "europe"})) in ("forbidden",)


def test_not_on_stdio():
    async def go():
        with identity_scope(STDIO):
            async with create_connected_server_and_client_session(mt.server) as s:
                return {t.name for t in (await s.list_tools()).tools}
    assert not (asyncio.run(go()) & P3_TOOLS)
    assert _err(_call(STDIO, "portfolio.model_runs", {"location": "europe"})) == "forbidden"


def test_model_runs_over_http_needs_a_jwt(client, tool_db, fake_models):
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "portfolio.model_runs", "arguments": {"location": "europe"}}}
    r = client.post("/mcp", json=body, headers=headers)
    assert r.status_code == 401
    headers["Authorization"] = f"Bearer {create_access_token('rita-dev')}"   # local dev user
    r = client.post("/mcp", json=body, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["isError"] is False


# ── error codes ────────────────────────────────────────────────────────────────

def test_no_eligible_instrument_is_not_found(tool_db, fake_models):
    res = _call(ALICE, "portfolio.select_for_goal", {"location": "us", "target_return": 0.05})
    assert _err(res) == "not_found" and "U1:no_model" in res.structuredContent["error"]["message"]


def test_compute_failure_is_unavailable(tool_db, fake_models, monkeypatch):
    monkeypatch.setattr(svc_mod, "select", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert _err(_call(ALICE, "portfolio.select_for_goal",
                      {"location": "europe", "target_return": 0.05})) == "unavailable"


def test_as_of_mismatch_is_invalid_input(tool_db, fake_models):
    res = _call(ALICE, "portfolio.select_for_goal",
                {"location": "europe", "target_return": 0.05, "as_of": "2026-01-02"})
    assert _err(res) == "invalid_input"


# ── logging ────────────────────────────────────────────────────────────────────

def test_logging_never_holds_rates_or_amounts(tool_db, fake_models, calls):
    _call(ALICE, "portfolio.required_return", {
        "location": "europe", "goal_return": 0.07675, "ytd_return": 0.123,
        "as_of": "2026-06-30", "year_start": "2026-01-01", "reselections_used": 1})
    _call(ALICE, "portfolio.select_for_goal", {"location": "europe", "target_return": 0.0456})
    req, sel = calls
    assert req["args_summary"] == ("location=europe, goal_return, ytd_return, as_of=2026-06-30, "
                                   "year_start=2026-01-01, reselections_used")
    assert req["result_summary"] == "status=on_track reason=on_track"
    assert sel["args_summary"] == "location=europe, target_return"
    for row in (req, sel):
        for leak in ("0.07675", "0.123", "0.0456", "7.67", "12.3", "4.56"):
            assert leak not in row["args_summary"] + row["result_summary"]


# ── no network ─────────────────────────────────────────────────────────────────

def test_no_network_on_any_p3_tool(tool_db, fake_models, monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("network access")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    for name, args in (
        ("whatineed.get_goal", {"location": "europe"}),
        ("portfolio.select_for_goal", {"location": "europe", "target_return": 0.05}),
        ("portfolio.required_return", {"location": "europe", "goal_return": 0.07,
                                       "ytd_return": -0.02, "as_of": "2026-06-30",
                                       "year_start": "2026-01-01"}),
        ("portfolio.model_runs", {"location": "europe"}),
    ):
        res = _call(ALICE, name, args)
        assert not res.isError, (name, res.structuredContent)


def test_health_reports_16_tools(client):
    assert client.get("/health").json()["mcp"]["tools_registered"] == 16


def test_required_return_at_year_start_is_the_goal(tool_db, fake_models):
    res = _call(ALICE, "portfolio.required_return", {
        "location": "europe", "goal_return": 0.07, "ytd_return": 0.0,
        "as_of": "2025-12-31", "year_start": "2026-01-01"})
    out = res.structuredContent
    assert out["required_return"] == pytest.approx(0.07) and out["status"] == "on_track"
    assert out["remaining_fraction"] == out["year_fraction"] == 1.0
