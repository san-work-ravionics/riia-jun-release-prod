"""RITA MCP — streamable HTTP transport at ``/mcp`` with the RITA JWT (F44 P1, ADR-007 §4–§5).

Stateless, JSON responses (no long-lived streams, so nginx needs no streaming config).
``Authorization: Bearer <RITA JWT>`` is checked by ``McpJwtGate`` before any MCP message is
processed — 401 ``WWW-Authenticate: Bearer`` otherwise.  The resolved user is put on the request
and the tool dispatch (``mcp_tools.dispatch``) reads it from the MCP request context.

Mounted in main.py:
    app.add_route("/mcp", mcp_endpoint, methods=["GET", "POST", "DELETE"], include_in_schema=False)
and the session manager runs inside the app lifespan:
    async with mcp_http_app.lifespan(): ...

Claude Desktop via mcp-remote:
    { "command": "npx",
      "args": ["mcp-remote", "https://riia.ravionics.nl/mcp", "--header", "Authorization: Bearer ${RITA_JWT}"],
      "env": { "RITA_JWT": "<token>" } }
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from rita.interfaces.mcp_auth import McpJwtGate
from rita.interfaces.mcp_tools import server

log = structlog.get_logger(__name__)


class McpHttpApp:
    """ASGI app over the SDK session manager; a fresh manager per app lifespan (the SDK allows
    ``run()`` once per manager instance, and tests start the app lifespan many times)."""

    def __init__(self) -> None:
        self._manager: StreamableHTTPSessionManager | None = None

    @property
    def running(self) -> bool:
        return self._manager is not None

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        manager = StreamableHTTPSessionManager(app=server, json_response=True, stateless=True)
        async with manager.run():
            self._manager = manager
            log.info("mcp.http_started", path="/mcp")
            try:
                yield
            finally:
                self._manager = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        manager = self._manager
        if manager is None:
            await JSONResponse({"detail": "MCP server not started"}, status_code=503)(scope, receive, send)
            return
        await manager.handle_request(scope, receive, send)


mcp_http_app = McpHttpApp()

# What main.py mounts at /mcp: JWT gate first, then the MCP session manager.
mcp_endpoint = McpJwtGate(mcp_http_app, transport="http")
