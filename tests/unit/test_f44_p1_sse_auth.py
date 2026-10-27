"""F44 P1 → P4 — the SSE transport is removed (ADR-007 note, Finding 2).

``GET /mcp/sse`` and ``POST /mcp/messages/`` were the deprecated SSE pair (P1 JWT-gated them).  P4
deletes ``interfaces/mcp_sse_app.py`` and its route + mount: both paths are now 404 with or without
a token, ``/health`` no longer advertises ``sse``, and ``/mcp`` (streamable HTTP) stays gated.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rita.auth import create_access_token
from rita.main import app
from rita.interfaces.mcp_auth import TRANSPORTS


@pytest.fixture(scope="module")
def raw_client():
    return TestClient(app)


def _bearer() -> dict:
    return {"Authorization": f"Bearer {create_access_token('rita-dev')}"}


@pytest.mark.parametrize("headers", [{}, None])
def test_sse_route_is_gone(raw_client, headers):
    h = _bearer() if headers is None else headers
    assert raw_client.get("/mcp/sse", headers=h).status_code == 404


@pytest.mark.parametrize("headers", [{}, None])
def test_messages_mount_is_gone(raw_client, headers):
    h = _bearer() if headers is None else headers
    r = raw_client.post("/mcp/messages/?session_id=0123456789abcdef0123456789abcdef", headers=h, json={})
    assert r.status_code == 404


def test_no_sse_route_or_module():
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/mcp/sse" not in paths and "/mcp/messages" not in paths
    with pytest.raises(ImportError):
        __import__("rita.interfaces.mcp_sse_app")


def test_sse_not_a_transport():
    assert "sse" not in TRANSPORTS


def test_mcp_http_still_gated(raw_client):
    r = raw_client.post("/mcp", json={})
    assert r.status_code == 401 and r.headers.get("www-authenticate") == "Bearer"
