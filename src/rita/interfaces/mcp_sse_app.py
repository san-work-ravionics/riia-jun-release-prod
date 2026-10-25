"""
RITA MCP Server — SSE transport (DEPRECATED since F44 P1; removed in F44 P4).

Use streamable HTTP at ``/mcp`` instead (``mcp_http_app.py``).  Kept for one release so an existing
``mcp-remote …/mcp/sse`` config keeps working — **with a token** (ADR-007 §6).

Mounted in main.py:
    app.add_api_route("/mcp/sse", handle_sse, methods=["GET"], include_in_schema=False)
    app.mount("/mcp/messages", sse_messages_app)

Both routes need ``Authorization: Bearer <RITA JWT>`` — 401 ``WWW-Authenticate: Bearer`` without.

Claude Desktop via mcp-remote:
    { "command": "npx",
      "args": ["mcp-remote", "https://<host>/mcp/sse", "--header", "Authorization: Bearer ${RITA_JWT}"] }
"""
from __future__ import annotations

import structlog
from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.responses import Response

from rita.interfaces.mcp_auth import McpJwtGate, authenticate_request
from rita.interfaces.mcp_tools import server

log = structlog.get_logger(__name__)

sse_transport = SseServerTransport("/mcp/messages/")

# POST /mcp/messages/ — every JSON-RPC message (incl. initialize) is gated on its own token.
sse_messages_app = McpJwtGate(sse_transport.handle_post_message, transport="sse")


async def handle_sse(request: Request) -> Response:
    identity = await authenticate_request(request, transport="sse")
    if isinstance(identity, Response):
        return identity
    log.warning("mcp.sse_deprecated", user_id=identity.user_id,
                detail="SSE transport is deprecated; use streamable HTTP at /mcp")
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await server.run(
            streams[0], streams[1], server.create_initialization_options()
        )
    return Response()
