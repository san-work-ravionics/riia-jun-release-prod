"""F44 P1 — JWT gate on the (deprecated) SSE transport: GET /mcp/sse + POST /mcp/messages/.

ADR-007 §6: both routes return 401 ``WWW-Authenticate: Bearer`` without a valid RITA JWT and work
unchanged with one.  The token check is ``rita.auth.resolve_token_user`` (shared with
``get_current_user``): expired tokens and the ``rita-dev`` subject outside development are refused.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from rita.auth import create_access_token
from rita.config import get_settings
from rita.main import app
from rita.models.user import UserModel


@pytest.fixture(scope="module")
def raw_client():
    # No lifespan needed for the SSE routes.
    return TestClient(app)


def _expired_token(sub: str = "rita-dev") -> str:
    s = get_settings()
    return jwt.encode(
        {"sub": sub, "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        s.security.jwt_secret.get_secret_value(), algorithm=s.security.jwt_algorithm,
    )


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _assert_401(resp):
    assert resp.status_code == 401, resp.text
    assert resp.headers.get("www-authenticate") == "Bearer"
    assert "detail" in resp.json()


# ── GET /mcp/sse ───────────────────────────────────────────────────────────────

def test_sse_no_token_401(raw_client):
    _assert_401(raw_client.get("/mcp/sse"))


def test_sse_garbage_token_401(raw_client):
    _assert_401(raw_client.get("/mcp/sse", headers=_bearer("this.is.garbage")))


def test_sse_wrong_scheme_401(raw_client):
    _assert_401(raw_client.get("/mcp/sse", headers={"Authorization": "Basic abc"}))


def test_sse_expired_token_401(raw_client):
    _assert_401(raw_client.get("/mcp/sse", headers=_bearer(_expired_token())))


def test_sse_rita_dev_in_production_401(raw_client):
    prod = get_settings().model_copy(update={"env": "production"})
    with patch("rita.auth.get_settings", return_value=prod):
        _assert_401(raw_client.get("/mcp/sse", headers=_bearer(create_access_token("rita-dev"))))


def test_sse_valid_token_reaches_transport(raw_client):
    """With a valid token the request reaches connect_sse + server.run (patched — no stream)."""
    entered = {}

    @asynccontextmanager
    async def fake_connect(scope, receive, send):
        entered["yes"] = True
        yield (object(), object())

    with patch("rita.interfaces.mcp_sse_app.sse_transport.connect_sse", fake_connect), \
         patch("rita.interfaces.mcp_sse_app.server.run", new=AsyncMock(return_value=None)) as run:
        resp = raw_client.get("/mcp/sse", headers=_bearer(create_access_token("rita-dev")))
    assert resp.status_code == 200
    assert entered.get("yes") is True
    run.assert_awaited_once()


def test_sse_real_user_token(raw_client, db_session):
    db_session.add(UserModel(id="alice@example.com"))
    db_session.commit()

    @asynccontextmanager
    async def fake_connect(scope, receive, send):
        yield (object(), object())

    with patch("rita.interfaces.mcp_auth._session_factory", return_value=db_session), \
         patch("rita.interfaces.mcp_sse_app.sse_transport.connect_sse", fake_connect), \
         patch("rita.interfaces.mcp_sse_app.server.run", new=AsyncMock(return_value=None)):
        ok = raw_client.get("/mcp/sse", headers=_bearer(create_access_token("alice@example.com")))
        unknown = raw_client.get("/mcp/sse", headers=_bearer(create_access_token("nobody@example.com")))
    assert ok.status_code == 200
    _assert_401(unknown)


# ── POST /mcp/messages/ ────────────────────────────────────────────────────────

def test_messages_no_token_401(raw_client):
    _assert_401(raw_client.post("/mcp/messages/?session_id=abc", json={}))


def test_messages_expired_token_401(raw_client):
    _assert_401(raw_client.post("/mcp/messages/?session_id=abc", json={},
                                headers=_bearer(_expired_token())))


def test_messages_valid_token_passes_gate(raw_client):
    """Past the gate the SDK answers (400 without a session_id / 404 unknown session) — not 401."""
    tok = _bearer(create_access_token("rita-dev"))
    missing = raw_client.post("/mcp/messages/", json={}, headers=tok)
    assert missing.status_code == 400
    unknown = raw_client.post(
        "/mcp/messages/?session_id=0123456789abcdef0123456789abcdef", json={}, headers=tok,
    )
    assert unknown.status_code == 404


def test_get_current_user_unchanged_for_routes(raw_client):
    """Routes still use get_current_user: same 401/403 behaviour as before the extraction."""
    resp = raw_client.get("/api/v1/experience/fno/hedge-plan")
    assert resp.status_code in (401, 403)
    resp = raw_client.get("/api/v1/experience/fno/hedge-plan", headers=_bearer(_expired_token()))
    assert resp.status_code == 401
