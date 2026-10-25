"""F44 P1 — streamable HTTP at /mcp with the RITA JWT, /health mcp block, /api/v1/mcp-calls fields,
and the real stdio server process (ADR-007 §4–§7).

- ``initialize`` + ``tools/list`` + ``tools/call`` work with a JWT (stateless, JSON responses)
- 401 ``WWW-Authenticate: Bearer`` without a token / with an expired token / with ``rita-dev``
  under production settings — before any MCP processing; an expired token mid-session → 401
- the user is the token's user (``whatineed.get_plan`` per user; logged ``transport=http``)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import rita.interfaces.mcp_tools as mt
from rita.auth import create_access_token
from rita.config import get_settings
from rita.database import Base
from rita.interfaces.tools import set_session_factory
from rita.models.mcp_call import MCPCallModel
from rita.models.user import UserModel

_ROOT = Path(__file__).resolve().parents[2]
_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _expired(sub: str = "rita-dev") -> str:
    s = get_settings()
    return jwt.encode({"sub": sub, "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
                      s.security.jwt_secret.get_secret_value(), algorithm=s.security.jwt_algorithm)


def _rpc(client, token: str | None, method: str, params: dict | None = None, rid: int = 1):
    headers = dict(_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    return client.post("/mcp", json=body, headers=headers)


_INIT = {"protocolVersion": "2025-06-18", "capabilities": {},
         "clientInfo": {"name": "pytest", "version": "1"}}


@pytest.fixture
def tool_db(tmp_path):
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
    rows: list[dict] = []
    with patch.object(mt, "_log_call", side_effect=lambda **kw: rows.append(kw)):
        yield rows


def _assert_401(resp):
    assert resp.status_code == 401, resp.text
    assert resp.headers.get("www-authenticate") == "Bearer"
    assert "detail" in resp.json()


# ── auth ───────────────────────────────────────────────────────────────────────

def test_mcp_401_without_token(client, calls):
    _assert_401(_rpc(client, None, "initialize", _INIT))
    assert calls == []  # rejected before any MCP processing


def test_mcp_401_garbage_and_expired(client, calls):
    _assert_401(_rpc(client, "not.a.jwt", "initialize", _INIT))
    _assert_401(_rpc(client, _expired(), "initialize", _INIT))
    assert calls == []


def test_mcp_401_rita_dev_under_production(client):
    prod = get_settings().model_copy(update={"env": "production"})
    with patch("rita.auth.get_settings", return_value=prod):
        _assert_401(_rpc(client, create_access_token("rita-dev"), "initialize", _INIT))


def test_mcp_get_and_delete_also_gated(client):
    _assert_401(client.get("/mcp", headers={"Accept": "text/event-stream"}))
    _assert_401(client.delete("/mcp"))


# ── initialize + tools/list + tools/call ───────────────────────────────────────

def test_mcp_initialize_list_call_with_jwt(client, tool_db, calls):
    tok = create_access_token("rita-dev")
    init = _rpc(client, tok, "initialize", _INIT)
    assert init.status_code == 200, init.text
    assert init.json()["result"]["serverInfo"]["name"] == "rita"

    listed = _rpc(client, tok, "tools/list", rid=2)
    assert listed.status_code == 200, listed.text
    names = {t["name"] for t in listed.json()["result"]["tools"]}
    assert {"whatineed.get_plan", "market.overview", "ask_rita"} <= names
    for t in listed.json()["result"]["tools"]:
        assert "user_id" not in json.dumps(t["inputSchema"])

    called = _rpc(client, tok, "tools/call", {"name": "whatineed.get_plan", "arguments": {}}, rid=3)
    assert called.status_code == 200, called.text
    result = called.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["saved"] is False  # rita-dev has no saved plan → preset
    assert result["_meta"]["mcp_call_id"] == calls[-1]["call_id"]
    assert (calls[-1]["transport"], calls[-1]["caller"], calls[-1]["user_id"]) == ("http", "external", "rita-dev")


def test_mcp_user_comes_from_token(client, tool_db, calls):
    from rita.services.retirement_plan_service import RetirementPlanService, default_plan

    db = tool_db()
    db.add(UserModel(id="carol"))
    db.commit()
    RetirementPlanService(db).save("carol", default_plan("europe").inputs.model_copy(update={"ret": 61}), "europe")
    db.close()

    with patch("rita.interfaces.mcp_auth._session_factory", side_effect=lambda: tool_db()):
        tok = create_access_token("carol")
        r = _rpc(client, tok, "tools/call", {"name": "whatineed.get_plan", "arguments": {}})
        # a user_id argument is refused, never honoured
        r2 = _rpc(client, tok, "tools/call",
                  {"name": "whatineed.get_plan", "arguments": {"user_id": "rita-dev"}}, rid=2)
        unknown = _rpc(client, create_access_token("mallory"), "tools/call",
                       {"name": "whatineed.get_plan", "arguments": {}})
    res = r.json()["result"]
    assert res["structuredContent"]["saved"] is True
    assert res["structuredContent"]["result"]["retire_age"] == 61
    assert calls[0]["user_id"] == "carol"
    err = r2.json()["result"]
    assert err["isError"] is True and err["structuredContent"]["error"]["code"] == "invalid_input"
    _assert_401(unknown)


def test_mcp_expired_token_mid_session(client, tool_db):
    tok = create_access_token("rita-dev")
    assert _rpc(client, tok, "initialize", _INIT).status_code == 200
    _assert_401(_rpc(client, _expired(), "tools/list", rid=2))


def test_mcp_tool_error_is_coded_not_500(client, tool_db):
    tok = create_access_token("rita-dev")
    r = _rpc(client, tok, "tools/call", {"name": "portfolio.get_holdings", "arguments": {}})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["isError"] is True and res["structuredContent"]["error"]["code"] == "not_found"


# ── /health + /api/v1/mcp-calls ────────────────────────────────────────────────

def test_health_mcp_block(client):
    body = client.get("/health").json()
    assert body["mcp"] == {"tools_registered": 11, "auth": "on",
                           "transports": ["http", "memory", "sse"], "sse": "deprecated"}


def test_mcp_calls_rows_carry_new_fields(client, db_session):
    now = datetime.now(timezone.utc)
    db_session.add(MCPCallModel(call_id="c-new", timestamp=now, tool_name="whatineed.get_plan", status="ok",
                                duration_ms=2.0, args_summary="", result_summary="saved=True", recorded_at=now,
                                transport="memory", caller="jarvis", user_id="alice"))
    db_session.add(MCPCallModel(call_id="c-old", timestamp=now - timedelta(days=1), tool_name="ask_rita",
                                status="ok", duration_ms=1.0, recorded_at=now))
    db_session.commit()
    rows = client.get("/api/v1/mcp-calls?limit=10").json()
    by_id = {r["call_id"]: r for r in rows}
    assert (by_id["c-new"]["transport"], by_id["c-new"]["caller"], by_id["c-new"]["user_id"]) == (
        "memory", "jarvis", "alice")
    assert by_id["c-old"]["transport"] is None and by_id["c-old"]["user_id"] is None
    for key in ("call_id", "timestamp", "tool_name", "status", "duration_ms", "args_summary", "result_summary"):
        assert key in by_id["c-old"]


# ── the real stdio process ─────────────────────────────────────────────────────

def test_stdio_process_lists_userless_tools_and_answers_alias():
    """Spawn ``python -m rita.interfaces.rita_mcp_server`` and talk MCP over stdio."""
    import asyncio

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from rita.core.data_understanding import find_instrument_csv

    try:
        find_instrument_csv("NIFTY")
    except FileNotFoundError:
        pytest.skip("no NIFTY price CSV in this checkout")

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "rita.interfaces.rita_mcp_server"],
        env={**os.environ, "PYTHONPATH": str(_ROOT / "src")}, cwd=str(_ROOT),
    )

    async def go():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = {t.name for t in (await s.list_tools()).tools}
                overview = await s.call_tool("rita_market_overview", {"instrument": "NIFTY"})
                forbidden = await s.call_tool("portfolio.get_holdings", {})
                return tools, overview, forbidden

    tools, overview, forbidden = asyncio.run(asyncio.wait_for(go(), timeout=240))
    assert tools == {"portfolio.optimal_allocation", "market.overview", "market.ask",
                     "ask_rita", "rita_market_overview", "rita_monitor"}
    assert overview.content[0].text.startswith("**NIFTY — Market Overview**")
    assert forbidden.isError and forbidden.structuredContent["error"]["code"] == "forbidden"
