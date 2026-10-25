"""F44 P1 QA — MCP bus: gap tests on top of the Engineer's 82 ``test_f44_p1_*`` tests.

QA run 20261025-1150. Covers what the existing files do not:

- happy path for one namespaced tool (``portfolio.get_holdings``) through the **sync** in-memory
  client, checked against the real ``mcp_calls`` row written to a temp DB;
- Architect edge cases: a tool error inside a sync in-memory call (coded ``McpCallError`` whose
  ``call_id`` is the logged row; the session still works afterwards); two concurrent **async**
  sessions on one event loop keep their own users; an HTTP client cannot claim ``system`` or another
  user through ``_meta`` / headers; a ``rita-dev`` token under production settings is the anonymous
  view on ``/api/v1/mcp-calls``;
- property tests (seeded random — ``hypothesis`` is not installed in the shared env):
  (a) ``GET /api/v1/mcp-calls`` option B never returns ``user_id`` / ``args_summary`` /
      ``result_summary`` to an anonymous viewer, and a non-ops user never sees another user's
      personal fields;
  (b) no ``tool_name`` that is not registered is ever stored (in-memory and HTTP);
  (c) ``/mcp`` (and the deprecated SSE pair) without a valid JWT → 401, before any dispatch;
- design-contract checks: tool set + Auth per the Spec_MCP_Server P1 catalogue, ``mcp_calls``
  columns, ``/mcp`` methods, exact ``mcp-calls`` response keys, ``/health`` mcp block.

No test writes to the dev ``rita_output/rita.db``: tools + the logger use the per-test ``tool_db``
file DB (``set_session_factory``), the JWT gate's user lookup is pointed at it too, and HTTP routes
use the conftest in-memory ``db_session``.
"""
from __future__ import annotations

import asyncio
import base64
import json
import random
import string
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jsonschema
import pytest
from jose import jwt
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import rita.interfaces.mcp_tools as mt
from rita.auth import create_access_token
from rita.config import get_settings
from rita.database import Base
from rita.interfaces.mcp_auth import TRANSPORTS, McpIdentity, identity_scope
from rita.interfaces.mcp_client import McpCallError, McpRequestClient, identity_for, memory_client
from rita.interfaces.tools import set_session_factory
from rita.models.mcp_call import MCPCallModel
from rita.models.user import UserModel
from rita.schemas.user_portfolio import HoldingItem

_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
_INIT = {"protocolVersion": "2025-06-18", "capabilities": {},
         "clientInfo": {"name": "pytest-qa", "version": "1"}}

# Design contract (Architect P1 design + Spec_MCP_Server § F44 tool catalogue, P1 rows).
CONTRACT_AUTH = {
    "whatineed.get_plan":           ({"user"}, None),
    "portfolio.get_holdings":       ({"user", "system"}, None),
    "portfolio.optimal_allocation": ({"none"}, None),
    "fno.position_value":           ({"user"}, None),
    "fno.get_hedge_plan":           ({"user"}, None),
    "market.overview":              ({"none"}, None),
    "market.ask":                   ({"none"}, None),
    "market.monitor":               ({"user"}, "can_access_ops"),
    # legacy aliases (rita_monitor needs ops over the network — recorded Engineer deviation)
    "ask_rita":                     ({"none"}, None),
    "rita_market_overview":         ({"none"}, None),
    "rita_monitor":                 ({"user"}, "can_access_ops"),
}
CONTRACT_MCP_CALLS_COLUMNS = {
    "call_id", "timestamp", "tool_name", "status", "duration_ms", "args_summary", "result_summary",
    "recorded_at", "transport", "caller", "user_id",
}
CONTRACT_MCP_CALLS_RESPONSE_KEYS = {
    "call_id", "timestamp", "tool_name", "status", "duration_ms", "args_summary", "result_summary",
    "transport", "caller", "user_id",
}
_PERSONAL = ("user_id", "args_summary", "result_summary")


# ── fixtures / helpers ─────────────────────────────────────────────────────────

@pytest.fixture
def tool_db(tmp_path):
    """File SQLite DB for tool sessions **and** the mcp_calls logger (set_session_factory sets both)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'qa_tools.db'}", connect_args={"check_same_thread": False})
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


def _seed(maker):
    """alice: plan ret 60 + saved portfolio; bob: plan ret 63, no portfolio, no hedge plan."""
    from rita.services.retirement_plan_service import RetirementPlanService, default_plan
    from rita.services.user_portfolio_service import UserPortfolioService

    db = maker()
    try:
        db.add_all([UserModel(id="alice"), UserModel(id="bob")])
        db.commit()
        base = default_plan("europe").inputs
        RetirementPlanService(db).save("alice", base.model_copy(update={"ret": 60}), "europe")
        RetirementPlanService(db).save("bob", base.model_copy(update={"ret": 63}), "europe")
        UserPortfolioService(db).save(
            "alice",
            [HoldingItem(instrument_id="NIFTY", allocation_pct=70, shares=5, cash_eur=10.0),
             HoldingItem(instrument_id="ASML", allocation_pct=30, shares=1, cash_eur=2.5)],
            name="QA PF", total_value_eur=20_000,
        )
    finally:
        db.close()


def _rows(maker) -> list[MCPCallModel]:
    db = maker()
    try:
        return db.query(MCPCallModel).all()
    finally:
        db.close()


def _rpc(client, token: str | None, method: str, params: dict | None = None, rid: int = 1,
         extra_headers: dict | None = None):
    headers = dict(_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers.update(extra_headers or {})
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}},
                       headers=headers)


def _token(claims: dict, *, secret: str | None = None, alg: str | None = None) -> str:
    s = get_settings()
    return jwt.encode(claims, secret or s.security.jwt_secret.get_secret_value(),
                      algorithm=alg or s.security.jwt_algorithm)


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=30)


def _b64(obj: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def _assert_401(resp):
    assert resp.status_code == 401, (resp.status_code, resp.text[:200])
    assert resp.headers.get("www-authenticate") == "Bearer"
    assert "detail" in resp.json()


# ── happy path: one namespaced tool through the in-memory client ───────────────

def test_happy_path_portfolio_get_holdings_via_sync_client(tool_db):
    _seed(tool_db)
    with McpRequestClient(identity_for(UserModel(id="alice"), "module:fno")) as mcp:
        r = mcp.call("portfolio.get_holdings")

    spec = mt.REGISTRY["portfolio.get_holdings"]
    jsonschema.validate(r.structured, spec.output_json_schema())
    out = spec.output_model.model_validate(r.structured)
    assert (out.name, out.currency, out.location, out.total_value) == ("QA PF", "EUR", None, 20_000)
    assert [(h.instrument_id, h.allocation_pct, h.shares, h.cash) for h in out.holdings] == [
        ("NIFTY", 70, 5, 10.0), ("ASML", 30, 1, 2.5)]
    assert r.text == "Portfolio 'QA PF': 2 holdings, total 20,000 EUR."

    rows = _rows(tool_db)
    assert len(rows) == 1
    row = rows[0]
    assert row.call_id == r.call_id
    assert (row.tool_name, row.status, row.transport, row.caller, row.user_id) == (
        "portfolio.get_holdings", "ok", "memory", "module:fno", "alice")
    assert (row.args_summary, row.result_summary) == ("", "holdings=2")
    # nothing personal (name / amounts) in the summaries
    assert "QA PF" not in row.result_summary and "20" not in row.result_summary.replace("holdings=2", "")


# ── Architect edge cases ───────────────────────────────────────────────────────

def test_edge_tool_error_inside_sync_in_memory_call_is_coded_logged_and_session_survives(tool_db):
    """Edge: tool error inside an in-memory call → structured error, logged, caller gets the code
    (never a 500 swallowed as text); the request's session keeps working."""
    _seed(tool_db)
    with McpRequestClient(identity_for(UserModel(id="bob"), "jarvis")) as mcp:
        with patch("rita.services.hedge_plan_service.HedgePlanService.get_for_user",
                   side_effect=RuntimeError("db down")):
            with pytest.raises(McpCallError) as boom:
                mcp.call("fno.get_hedge_plan")
        with pytest.raises(McpCallError) as missing:
            mcp.call("fno.get_hedge_plan")  # bob has no saved hedge plan
        with pytest.raises(McpCallError) as bad:
            mcp.call("whatineed.get_plan", {"location": "mars"})
        ok = mcp.call("whatineed.get_plan")  # same session still usable

    assert (boom.value.code, boom.value.tool) == ("unavailable", "fno.get_hedge_plan")
    assert "db down" not in boom.value.message  # exception text is not leaked to the caller
    assert missing.value.code == "not_found"
    assert bad.value.code == "invalid_input"
    assert ok.structured["result"]["retire_age"] == 63

    by_id = {r.call_id: r for r in _rows(tool_db)}
    assert len(by_id) == 4
    assert (by_id[boom.value.call_id].status, by_id[boom.value.call_id].result_summary) == (
        "error", "unavailable: RuntimeError")
    assert by_id[missing.value.call_id].result_summary.startswith("not_found")
    assert by_id[bad.value.call_id].result_summary.startswith("invalid_input")
    assert (by_id[ok.call_id].status, by_id[ok.call_id].user_id) == ("ok", "bob")


def test_edge_concurrent_async_sessions_on_one_loop_keep_their_users(tool_db, calls):
    """Edge: concurrent in-memory calls from two requests — no shared identity leakage, also when
    both sessions run as tasks on the same event loop (the sync-bridge test uses two threads)."""
    _seed(tool_db)

    async def request(uid: str, gate: asyncio.Barrier) -> list[int]:
        async with memory_client(identity_for(UserModel(id=uid), "jarvis")) as c:
            await gate.wait()
            ages = []
            for _ in range(4):
                ages.append((await c.call("whatineed.get_plan")).structured["result"]["retire_age"])
                await asyncio.sleep(0)
            return ages

    async def main():
        gate = asyncio.Barrier(3)
        tasks = [asyncio.create_task(request(u, gate)) for u in ("alice", "bob", "alice")]
        return await asyncio.gather(*tasks)

    got = asyncio.run(main())
    assert got == [[60] * 4, [63] * 4, [60] * 4]
    assert sorted(c["user_id"] for c in calls) == ["alice"] * 8 + ["bob"] * 4
    assert {c["transport"] for c in calls} == {"memory"}
    # the context identity does not outlive the sessions
    from rita.interfaces.mcp_auth import current_context_identity
    assert current_context_identity() is None


def test_edge_http_client_cannot_claim_system_or_another_user(client, tool_db, calls):
    """HTTP identity comes only from the JWT gate: ``_meta`` and custom headers are ignored."""
    tok = create_access_token("rita-dev")
    r = _rpc(client, tok, "tools/call",
             {"name": "whatineed.get_plan", "arguments": {},
              "_meta": {"caller": "system", "user_id": "alice", "transport": "memory"}},
             extra_headers={"X-MCP-Caller": "system", "X-User-Id": "alice"})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["isError"] is False
    assert (calls[-1]["transport"], calls[-1]["caller"], calls[-1]["user_id"]) == ("http", "external", "rita-dev")


def test_edge_rita_dev_token_under_production_is_anonymous_on_mcp_calls(client, db_session):
    now = datetime.now(timezone.utc)
    db_session.add(MCPCallModel(call_id="c1", timestamp=now, tool_name="whatineed.get_plan", status="ok",
                                duration_ms=1.0, args_summary="location=europe", result_summary="saved=True",
                                recorded_at=now, transport="memory", caller="jarvis", user_id="alice"))
    db_session.commit()
    prod = get_settings().model_copy(update={"env": "production"})
    with patch("rita.auth.get_settings", return_value=prod):
        resp = client.get("/api/v1/mcp-calls", headers={"Authorization": f"Bearer {create_access_token('rita-dev')}"})
    assert resp.status_code == 200
    (row,) = resp.json()
    assert all(row[k] is None for k in _PERSONAL)


# ── property (a): mcp-calls option B never leaks personal fields ───────────────

_POOL = ("alice", "bob@example.com", "carol@corp.nl", "dave")
_OPS = "ops-admin"


def _seed_random_calls(db_session, rng: random.Random, n: int = 80) -> dict[str, str | None]:
    owners: dict[str, str | None] = {}
    now = datetime.now(timezone.utc)
    for i in range(n):
        owner = rng.choice((*_POOL, None, None))
        tag = owner or "anon"
        cid = f"row-{i:03d}"
        owners[cid] = owner
        db_session.add(MCPCallModel(
            call_id=cid, timestamp=now - timedelta(seconds=i), tool_name=rng.choice(sorted(mt.REGISTRY)),
            status=rng.choice(("ok", "error")), duration_ms=rng.uniform(0.1, 50),
            args_summary=f"argsecret[{tag}]#{i}", result_summary=f"ressecret[{tag}]#{i}",
            recorded_at=now, transport=rng.choice(TRANSPORTS),
            caller=rng.choice(("jarvis", "external", "module:portfolio")), user_id=owner,
        ))
    db_session.add_all([UserModel(id=u) for u in _POOL] + [UserModel(id=_OPS, can_access_ops=True)])
    db_session.commit()
    return owners


def _view(client, header: str | None) -> list[dict]:
    resp = client.get("/api/v1/mcp-calls?limit=500", headers={"Authorization": header} if header else {})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.parametrize("seed", [44, 1150, 20261025])
def test_property_mcp_calls_option_b_never_leaks_personal_fields(client, db_session, seed):
    rng = random.Random(seed)
    owners = _seed_random_calls(db_session, rng)
    expired = _token({"sub": "alice", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)})
    anonymous = [None, "Bearer garbage", "Basic YWxpY2U6eA==", f"Bearer {expired}",
                 f"Bearer {create_access_token('mallory')}",
                 f"Bearer {_token({'sub': 'alice', 'exp': _future()}, secret='not-the-secret')}"]

    # anonymous: no row ever carries a personal field, and no user id / secret appears anywhere
    for header in anonymous:
        rows = _view(client, header)
        assert len(rows) == len(owners)
        for row in rows:
            assert set(row) == CONTRACT_MCP_CALLS_RESPONSE_KEYS
            assert all(row[k] is None for k in _PERSONAL), (header, row["call_id"])
        dumped = json.dumps(rows)
        assert "secret[" not in dumped
        assert not any(u in dumped for u in _POOL)

    # each non-ops user: own + userless rows full, every other user's row anonymised
    for viewer in rng.sample(_POOL, len(_POOL)):
        rows = _view(client, f"Bearer {create_access_token(viewer)}")
        assert len(rows) == len(owners)
        for row in rows:
            owner = owners[row["call_id"]]
            if owner is None or owner == viewer:
                tag = owner or "anon"
                assert row["user_id"] == owner
                assert row["args_summary"].startswith(f"argsecret[{tag}]")
                assert row["result_summary"].startswith(f"ressecret[{tag}]")
            else:
                assert all(row[k] is None for k in _PERSONAL), (viewer, row["call_id"])
        dumped = json.dumps(rows)
        for other in _POOL:
            if other != viewer:
                assert other not in dumped and f"secret[{other}]" not in dumped, (viewer, other)

    # ops: every row in full
    rows = _view(client, f"Bearer {create_access_token(_OPS)}")
    for row in rows:
        assert row["user_id"] == owners[row["call_id"]]
        assert row["args_summary"] and row["result_summary"]


# ── property (b): no unregistered tool_name is ever stored ────────────────────

def _random_names(rng: random.Random, n: int = 40) -> list[str]:
    registered = sorted(mt.REGISTRY)
    mutations = [
        str.upper, str.title, lambda s: s + " ", lambda s: " " + s, lambda s: s.replace(".", "_"),
        lambda s: s.replace(".", "/"), lambda s: s + "​", lambda s: s.replace("a", "а", 1),
        lambda s: s[:-1], lambda s: s + rng.choice(string.ascii_letters), lambda s: "../" + s,
        lambda s: s + "<script>alert(1)</script>",
    ]
    names = [m(rng.choice(registered)) for m in mutations for _ in range(2)]
    alphabet = string.ascii_letters + string.digits + string.punctuation + " "
    names += ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 120))) for _ in range(n)]
    names += ["", "unknown", "alice@example.com", "A" * 2000, "journey.get_state", "whatineed.get_goal"]
    names = [x for x in names if x not in mt.REGISTRY]
    return list(dict.fromkeys(names))


@pytest.mark.parametrize("seed", [7, 44])
def test_property_unregistered_tool_names_never_stored_in_memory(tool_db, seed):
    rng = random.Random(seed)
    unknown = _random_names(rng)
    registered = sorted(mt.REGISTRY)
    sequence = [(n, False) for n in unknown] + [(n, True) for n in registered]
    rng.shuffle(sequence)

    async def go():
        with identity_scope(McpIdentity(transport="memory", caller="jarvis", user_id="alice")):
            async with create_connected_server_and_client_session(mt.server) as s:
                out = []
                for name, is_registered in sequence:
                    # registered: an unknown instrument fails fast (invalid_input / forbidden) — no
                    # solver, classifier or price-file run; unknown: free text that must not be logged.
                    args = {"instrument": "NOPE_XYZ"} if is_registered else {"query": "<b>q</b>"}
                    out.append(await s.call_tool(name, args))
                return out

    with patch("rita.services.optimal_allocation_service.optimize_allocation", side_effect=RuntimeError("x")):
        results = asyncio.run(go())

    for (name, is_registered), res in zip(sequence, results):
        if not is_registered:
            assert res.isError and res.structuredContent["error"]["code"] == "not_found", repr(name)

    rows = _rows(tool_db)
    assert len(rows) == len(sequence)  # one row per call
    stored = [r.tool_name for r in rows]
    assert set(stored) <= set(mt.REGISTRY) | {mt.UNKNOWN_TOOL}
    assert stored.count(mt.UNKNOWN_TOOL) == len(unknown)
    assert sorted(n for n in stored if n != mt.UNKNOWN_TOOL) == registered
    for r in rows:
        if r.tool_name == mt.UNKNOWN_TOOL:
            assert r.args_summary.startswith("name_len=") and r.result_summary == "not_found: unknown tool"
        assert "<" not in f"{r.tool_name}{r.args_summary}{r.result_summary}"


def test_property_unregistered_tool_names_never_stored_over_http(client, tool_db):
    rng = random.Random(1150)
    names = _random_names(rng, n=10)
    tok = create_access_token("rita-dev")
    for i, name in enumerate(names):
        r = _rpc(client, tok, "tools/call", {"name": name, "arguments": {}}, rid=i + 1)
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        assert res["isError"] is True and res["structuredContent"]["error"]["code"] == "not_found"
    rows = _rows(tool_db)
    assert len(rows) == len(names)
    assert {r.tool_name for r in rows} == {mt.UNKNOWN_TOOL}
    assert {(r.transport, r.caller, r.user_id) for r in rows} == {("http", "external", "rita-dev")}


# ── property (c): /mcp without a valid JWT → 401 ───────────────────────────────

def _bad_auth_headers(rng: random.Random) -> list[str | None]:
    secret_alg = get_settings().security.jwt_algorithm
    other_alg = "HS512" if secret_alg != "HS512" else "HS384"
    s = get_settings().security.jwt_secret.get_secret_value()
    good_claims = {"sub": "rita-dev", "exp": _future()}
    fixed = [
        None, "", "Bearer", "Bearer ", "Bearer     ", "Basic cml0YS1kZXY6cml0YS1kZXY=", "Token abc",
        "bearer garbage", "Bearer not.a.jwt", "Bearer a.b.c",
        f"Bearer {_token(good_claims, secret='wrong-secret')}",                       # wrong key
        f"Bearer {_token(good_claims, alg=other_alg)}",                              # wrong algorithm
        f"Bearer {_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64({'sub': 'rita-dev'})}.",  # alg=none
        f"Bearer {_token({'exp': _future()})}",                                       # no sub
        f"Bearer {_token({'sub': 'rita-dev', 'exp': datetime.now(timezone.utc) - timedelta(seconds=5)})}",
        f"Bearer {create_access_token('mallory')}",                                   # unknown user
        f"Bearer {create_access_token('rita-dev')} extra",                            # trailing junk
        f"Bearer {create_access_token('rita-dev')[:-4]}",                             # truncated sig
        f"Bearer {s}",                                                                # the raw secret
    ]
    alphabet = string.ascii_letters + string.digits + "-_.=+/"
    randoms = [f"Bearer {''.join(rng.choice(alphabet) for _ in range(rng.randint(1, 300)))}" for _ in range(25)]
    return fixed + randoms


_GATED = [("POST", "/mcp"), ("GET", "/mcp"), ("DELETE", "/mcp"),
          ("POST", "/mcp/messages/?session_id=0123456789abcdef0123456789abcdef"), ("GET", "/mcp/sse")]


def test_property_mcp_without_valid_jwt_is_401_before_dispatch(client, tool_db, calls):
    rng = random.Random(20261025)
    with patch("rita.interfaces.mcp_auth._session_factory", side_effect=lambda: tool_db()):
        for header in _bad_auth_headers(rng):
            for method, path in _GATED:
                headers = dict(_HEADERS)
                if header is not None:
                    headers["Authorization"] = header
                body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "whatineed.get_plan", "arguments": {}}}
                resp = client.request(method, path, headers=headers,
                                      json=body if method == "POST" else None)
                assert resp.status_code == 401, (method, path, header and header[:60], resp.status_code)
                assert resp.headers.get("www-authenticate") == "Bearer"
    assert calls == []          # no MCP processing, no dispatch, no log row
    assert _rows(tool_db) == []

    # control: the same request with a valid token gets through
    ok = _rpc(client, create_access_token("rita-dev"), "initialize", _INIT)
    assert ok.status_code == 200, ok.text


# Users table present but empty (StaticPool: one shared in-memory DB, so the lookup really runs and
# answers "User not found" rather than failing on a missing table).
_EMPTY_ENGINE = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                              poolclass=StaticPool)
Base.metadata.create_all(_EMPTY_ENGINE)


def test_property_rita_dev_token_rejected_on_every_gated_path_under_production(client, calls):
    prod = get_settings().model_copy(update={"env": "production"})
    tok = create_access_token("rita-dev")
    with patch("rita.auth.get_settings", return_value=prod), \
         patch("rita.interfaces.mcp_auth._session_factory",
               side_effect=lambda: sessionmaker(bind=_EMPTY_ENGINE)()):
        for method, path in _GATED:
            resp = client.request(method, path, headers={**_HEADERS, "Authorization": f"Bearer {tok}"},
                                  json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                        "params": _INIT} if method == "POST" else None)
            _assert_401(resp)
    assert calls == []


# ── design contract ────────────────────────────────────────────────────────────

def test_contract_tool_set_and_auth_match_catalogue():
    assert set(mt.REGISTRY) == set(CONTRACT_AUTH)
    for name, (auth, flag) in CONTRACT_AUTH.items():
        spec = mt.REGISTRY[name]
        assert set(spec.auth) == auth, name
        assert spec.requires_flag == flag, name
        # stdio = Auth "none" tools + the legacy aliases only
        assert spec.stdio == ("none" in auth or spec.legacy), name
    namespaced = {n for n in mt.REGISTRY if "." in n}
    assert {n.split(".")[0] for n in namespaced} == {"whatineed", "portfolio", "fno", "market"}
    assert all(mt.REGISTRY[n].output_model is not None for n in namespaced)


def test_contract_mcp_calls_columns_and_transports():
    assert set(MCPCallModel.__table__.columns.keys()) == CONTRACT_MCP_CALLS_COLUMNS
    for col in ("transport", "caller", "user_id"):
        assert MCPCallModel.__table__.columns[col].nullable is True
    assert TRANSPORTS == ("memory", "http", "stdio", "sse")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    assert any(ix["column_names"] == ["user_id"] for ix in inspect(engine).get_indexes("mcp_calls"))
    engine.dispose()


def test_contract_mcp_routes_methods():
    from rita.main import app

    mounted = {getattr(r, "path", None): r for r in app.routes}
    assert mounted["/mcp"].methods >= {"GET", "POST", "DELETE"}
    assert "GET" in mounted["/mcp/sse"].methods
    assert "/mcp/messages" in mounted  # Mount (JWT-gated ASGI app)


def test_contract_mcp_calls_response_shape_and_health(client, db_session):
    now = datetime.now(timezone.utc)
    db_session.add(MCPCallModel(call_id="k1", timestamp=now, tool_name="market.overview", status="ok",
                                duration_ms=1.0, args_summary="instrument=NIFTY", result_summary="ok",
                                recorded_at=now, transport="http", caller="external", user_id=None))
    db_session.commit()
    (row,) = client.get("/api/v1/mcp-calls").json()
    assert set(row) == CONTRACT_MCP_CALLS_RESPONSE_KEYS
    assert client.get("/health").json()["mcp"] == {
        "tools_registered": len(CONTRACT_AUTH), "auth": "on",
        "transports": ["http", "memory", "sse"], "sse": "deprecated"}
