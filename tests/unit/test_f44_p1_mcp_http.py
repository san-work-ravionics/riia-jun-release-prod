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


def _seed_calls(db_session):
    now = datetime.now(timezone.utc)
    rows = [
        ("c-alice", "alice", now), ("c-bob", "bob@example.com", now - timedelta(minutes=1)),
        ("c-anon", None, now - timedelta(minutes=2)),
    ]
    for cid, uid, ts in rows:
        db_session.add(MCPCallModel(call_id=cid, timestamp=ts, tool_name="whatineed.get_plan", status="ok",
                                    duration_ms=2.0, args_summary="", result_summary="saved=True",
                                    recorded_at=ts, transport="memory" if uid else "stdio",
                                    caller="jarvis" if uid else "external", user_id=uid))
    db_session.add(MCPCallModel(call_id="c-old", timestamp=now - timedelta(days=1), tool_name="ask_rita",
                                status="ok", duration_ms=1.0, recorded_at=now))  # pre-P1 row: no user
    db_session.commit()


_ANON_KEYS = ("user_id", "args_summary", "result_summary")
_KEPT_KEYS = ("call_id", "timestamp", "tool_name", "status", "duration_ms", "transport", "caller")


def _seed_users(db_session):
    db_session.add(UserModel(id="alice"))
    db_session.add(UserModel(id="ops-admin", can_access_ops=True))
    db_session.commit()


def _get_calls(client, token: str | None = None, limit: int = 10):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = client.get(f"/api/v1/mcp-calls?limit={limit}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _assert_anonymised(row):
    for key in _ANON_KEYS:
        assert row[key] is None, (row["call_id"], key)
    for key in _KEPT_KEYS:
        assert key in row


def _assert_full(row):
    assert row["args_summary"] is not None and row["result_summary"] is not None, row["call_id"]


def test_mcp_calls_anonymous_view_without_token(client, db_session):
    """Option B (user 2026-10-25): no token → 200, every row anonymised — no user, args or result."""
    _seed_calls(db_session)
    rows = _get_calls(client)
    assert [r["call_id"] for r in rows] == ["c-alice", "c-bob", "c-anon", "c-old"]
    for r in rows:
        _assert_anonymised(r)
    by_id = {r["call_id"]: r for r in rows}
    assert (by_id["c-alice"]["transport"], by_id["c-alice"]["caller"]) == ("memory", "jarvis")
    dumped = json.dumps(rows)
    assert "bob@example.com" not in dumped and "alice" not in dumped.replace("c-alice", "")
    assert "saved=True" not in dumped


def test_mcp_calls_invalid_or_expired_token_is_anonymous_not_401(client, db_session):
    _seed_calls(db_session)
    _seed_users(db_session)
    for token in ("not.a.jwt", _expired("alice"), create_access_token("mallory")):  # mallory: no users row
        rows = _get_calls(client, token)
        assert len(rows) == 4
        for r in rows:
            _assert_anonymised(r)


def test_mcp_calls_non_ops_sees_own_and_userless_in_full_others_anonymised(client, db_session):
    _seed_calls(db_session)
    _seed_users(db_session)
    rows = _get_calls(client, create_access_token("alice"))
    by_id = {r["call_id"]: r for r in rows}
    assert set(by_id) == {"c-alice", "c-bob", "c-anon", "c-old"}
    assert by_id["c-alice"]["user_id"] == "alice" and by_id["c-alice"]["result_summary"] == "saved=True"
    for cid in ("c-alice", "c-anon", "c-old"):
        _assert_full(by_id[cid])
    assert by_id["c-anon"]["user_id"] is None and by_id["c-anon"]["result_summary"] == "saved=True"
    _assert_anonymised(by_id["c-bob"])
    assert by_id["c-bob"]["tool_name"] == "whatineed.get_plan" and by_id["c-bob"]["caller"] == "jarvis"
    assert "bob@example.com" not in json.dumps(rows)


def test_mcp_calls_ops_sees_all_rows_with_new_fields(client, db_session):
    _seed_calls(db_session)
    _seed_users(db_session)
    tok = create_access_token("ops-admin")
    rows = _get_calls(client, tok)
    by_id = {r["call_id"]: r for r in rows}
    assert [r["call_id"] for r in rows] == ["c-alice", "c-bob", "c-anon", "c-old"]  # newest first
    for r in rows:
        _assert_full(r)
    assert by_id["c-bob"]["user_id"] == "bob@example.com"
    assert (by_id["c-alice"]["transport"], by_id["c-alice"]["caller"], by_id["c-alice"]["user_id"]) == (
        "memory", "jarvis", "alice")
    assert by_id["c-old"]["transport"] is None and by_id["c-old"]["user_id"] is None
    assert len(_get_calls(client, tok, limit=2)) == 2


def test_mcp_calls_repository_viewer_rule(db_session):
    from rita.repositories.mcp_call import MCPCallRepository

    _seed_calls(db_session)
    repo = MCPCallRepository(db_session)
    full = lambda uid, ops: {r.call_id for r, f in repo.get_recent_for_viewer(uid, all_users=ops) if f}  # noqa: E731
    assert full(None, False) == set()
    assert full("alice", False) == {"c-alice", "c-anon", "c-old"}
    assert full("ops-admin", True) == {"c-alice", "c-bob", "c-anon", "c-old"}


def test_mcp_calls_js_consumers_send_the_jwt():
    """Every dashboard consumer goes through shared/api.js api() — the JWT is sent when there is one
    (full view for own rows); signed out the route answers the anonymous view, so no 401 / redirect."""
    js = _ROOT / "dashboard" / "js"
    for rel in ("rita/mcp.js", "ds/mcp.js", "ds/model-mcp.js", "ops/overview.js", "ops/observability.js"):
        src = (js / rel).read_text(encoding="utf-8")
        line = next(ln for ln in src.splitlines() if "/api/v1/mcp-calls" in ln)
        assert "api('/api/v1/mcp-calls" in line and "apiFetch(" not in line, rel
    for rel in ("rita/api.js", "ds/api.js", "ops/api.js"):
        assert "from '../shared/api.js'" in (js / rel).read_text(encoding="utf-8"), rel
    ds_export = (js / "ds" / "export.js").read_text(encoding="utf-8")
    assert "const data=await api(path);" in ds_export and "await fetch(path)" not in ds_export
    rita_html = (_ROOT / "dashboard" / "rita.html").read_text(encoding="utf-8")
    assert 'href="/api/v1/mcp-calls"' not in rita_html
    assert "downloadJSON('/api/v1/mcp-calls','mcp_calls.json')" in rita_html
    assert "window.downloadJSON" in (js / "rita" / "main.js").read_text(encoding="utf-8")


def test_mcp_calls_renderers_escape_every_row_field():
    """Review #10: every renderer that puts mcp-calls row fields into innerHTML escapes them;
    count-only consumers use textContent."""
    js = _ROOT / "dashboard" / "js"
    esc_def = "function _esc(v) {\n  return String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')"
    rita = (js / "rita" / "mcp.js").read_text(encoding="utf-8")
    assert esc_def in rita
    for field in ("r.timestamp", "r.tool_name", "r.args_summary", "r.result_summary"):
        assert f"${{_esc({field} || '—')}}" in rita, field
    assert "${badge(_esc(r.status))}" in rita and "${_esc(fmtMs(r.duration_ms))}" in rita
    obs = (js / "ops" / "observability.js").read_text(encoding="utf-8")
    assert esc_def in obs
    assert "${_esc(r.tool_name ?? '—')}" in obs and "badge(_esc(r.status ?? 'ok')" in obs
    assert "${_esc((r.called_at || '').slice(0, 16))}" in obs
    for rel, expr in (("ds/mcp.js", "calls.slice(0, 100).map(_escRow)"), ("ds/model-mcp.js", "rows.slice(0, 50).map(_escRow)")):
        src = (js / rel).read_text(encoding="utf-8")
        assert esc_def in src and "function _escRow(r)" in src and f"mkTbl({expr}," in src, rel
    # no un-escaped row field interpolation left in the table renderers
    import re
    for rel in ("rita/mcp.js", "ops/observability.js"):
        src = (js / rel).read_text(encoding="utf-8")
        assert not re.search(r"\$\{r\.(tool_name|args_summary|result_summary|timestamp|status|caller|user_id)", src), rel
    assert "getElementById('kpi-mcp').textContent = mcp ? mcp.length" in (js / "ops" / "overview.js").read_text(encoding="utf-8")
    mobile = (_ROOT / "mobileapp" / "ops.html").read_text(encoding="utf-8")
    assert "getElementById('s0-mcp').textContent = mcp ? mcp.length" in mobile


def test_ops_pages_require_login_at_page_load():
    """User 2026-10-25: Ops requires login. Desktop + mobile Ops gate on auth_token at load (the
    ds.html gate: production → Google sign-in via post_login_redirect; localhost → ensureDevToken)."""
    gate = ("if (!t || expired) {\n    sessionStorage.removeItem('auth_token');\n"
            "    sessionStorage.setItem('post_login_redirect', window.location.href);\n"
            "    window.location.href = '/auth/google/login';")
    ds_html = (_ROOT / "dashboard" / "ds.html").read_text(encoding="utf-8")
    assert gate in ds_html  # the existing pattern being reused
    ops_html = (_ROOT / "dashboard" / "ops.html").read_text(encoding="utf-8")
    assert gate in ops_html
    assert ops_html.index(gate) < ops_html.index('src="./js/ops/main.js"')
    assert ops_html.index(gate) < ops_html.index("<title>")  # in <head>, before the page renders
    ops_main = (_ROOT / "dashboard" / "js" / "ops" / "main.js").read_text(encoding="utf-8")
    assert "import { ensureDevToken } from '../shared/dev-auth.js';" in ops_main
    boot = ops_main[ops_main.index("document.addEventListener('DOMContentLoaded'"):]
    assert boot.index("await ensureDevToken();") < boot.index("loadOverview();")

    mobile = (_ROOT / "mobileapp" / "ops.html").read_text(encoding="utf-8")
    assert gate in mobile and mobile.index(gate) < mobile.index("<title>")
    assert "rita_token" not in mobile  # canonical key only (engineer.md §9 FC-AUTH-KEY)
    assert "return sessionStorage.getItem('auth_token') || '';" in mobile
    fetch_fn = mobile[mobile.index("async function apiFetch(path, _retried)"):]
    fetch_fn = fetch_fn[:fetch_fn.index("\n}\n")]
    assert "headers['Authorization'] = 'Bearer ' + token;" in fetch_fn
    assert "if (!_retried && await ensureDevToken(true)) return apiFetch(path, true);" in fetch_fn
    assert "window.location.href = '/auth/google/login';" in fetch_fn
    init = mobile[mobile.index("async function initData()"):]
    assert init.index("await ensureDevToken();") < init.index("loadStatus()")
    assert "apiFetch('/api/v1/mcp-calls')" in mobile


# ── the real stdio process ─────────────────────────────────────────────────────

def test_stdio_process_lists_userless_tools_and_answers_alias(tmp_path):
    """Spawn ``python -m rita.interfaces.rita_mcp_server`` and talk MCP over stdio."""
    import asyncio

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from rita.core.data_understanding import find_instrument_csv

    try:
        find_instrument_csv("NIFTY")
    except FileNotFoundError:
        pytest.skip("no NIFTY price CSV in this checkout")

    # F44 P1 review #9: the subprocess logs its calls into a temp DB, never the dev rita_output/rita.db.
    log_db = tmp_path / "stdio_mcp_calls.db"
    log_engine = create_engine(f"sqlite:///{log_db}")
    Base.metadata.create_all(log_engine)
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "rita.interfaces.rita_mcp_server"],
        env={**os.environ, "PYTHONPATH": str(_ROOT / "src"), "DATABASE_URL": f"sqlite:///{log_db}"},
        cwd=str(_ROOT),
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
    with log_engine.connect() as conn:  # the override took effect: both calls logged in the temp DB
        logged = [tuple(r) for r in conn.exec_driver_sql(
            "SELECT tool_name, transport, user_id FROM mcp_calls ORDER BY timestamp")]
    log_engine.dispose()
    assert logged == [("rita_market_overview", "stdio", None), ("portfolio.get_holdings", "stdio", None)]
