"""
RITA MCP Server — SSE transport for production EC2.

Mounted at /mcp in main.py:
    from rita.interfaces.mcp_sse_app import sse_transport, handle_sse
    app.add_api_route("/mcp/sse", handle_sse, methods=["GET"], include_in_schema=False)
    app.mount("/mcp/messages", sse_transport.handle_post_message)

Claude Desktop connects via mcp-remote:
    { "command": "npx", "args": ["mcp-remote", "http://<EC2_IP>/mcp/sse"] }
"""
from __future__ import annotations

from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.responses import Response

from rita.interfaces.mcp_tools import server

sse_transport = SseServerTransport("/mcp/messages/")


async def handle_sse(request: Request) -> Response:
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await server.run(
            streams[0], streams[1], server.create_initialization_options()
        )
    return Response()
