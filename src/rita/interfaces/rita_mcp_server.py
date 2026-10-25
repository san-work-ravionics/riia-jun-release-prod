"""
RITA MCP Server — stdio transport for Claude Desktop (local use)

Local process, no user: exposes only the tools that need no user (catalogue Auth ``none``:
``portfolio.optimal_allocation``, ``market.overview``, ``market.ask``) plus the legacy aliases
(``ask_rita``, ``rita_market_overview``, ``rita_monitor`` — unchanged Markdown).  A user tool called
here returns ``forbidden``.  Calls are logged to ``mcp_calls`` with ``transport=stdio``.

For production/remote access use streamable HTTP at /mcp with a RITA JWT (see mcp_http_app.py).

Installation (local):
    pip install -e .[interfaces]

Run (for testing in the terminal):
    cd riia-jun-release
    python -m rita.interfaces.rita_mcp_server

Claude Desktop config (local, stdio):
    {
      "mcpServers": {
        "rita": {
          "command": "/path/to/python",
          "args": ["-m", "rita.interfaces.rita_mcp_server"],
          "cwd": "/path/to/riia-jun-release"
        }
      }
    }

Claude Desktop config (production, streamable HTTP via mcp-remote):
    {
      "mcpServers": {
        "rita": {
          "command": "npx",
          "args": ["mcp-remote", "https://riia.ravionics.nl/mcp",
                   "--header", "Authorization: Bearer ${RITA_JWT}"],
          "env": { "RITA_JWT": "<RITA JWT>" }
        }
      }
    }
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# ── Pin working directory to riia-jun-release/ ────────────────────────────────
#    Claude Desktop spawns MCP servers with cwd=C:\WINDOWS\system32, so any
#    relative path in get_settings() (e.g. "data/output") resolves wrongly.
#    __file__ is always absolute, so we derive the project root from it.
#    rita_mcp_server.py → interfaces/ → rita/ → src/ → riia-jun-release/
_project_root = Path(__file__).resolve().parent.parent.parent.parent
os.chdir(_project_root)

# ── Ensure src/ is on sys.path when invoked as __main__ ───────────────────────
_src = _project_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

# ── Redirect ALL logging output to stderr ─────────────────────────────────────
#    MCP uses stdout exclusively for JSON-RPC framing. Any non-JSON bytes on
#    stdout (structlog lines, warnings, print() calls) cause:
#      "Unexpected non-whitespace character after JSON at position N"
#    on the Claude Desktop side. Force every logging sink to stderr BEFORE
#    any rita.* import, because those modules create module-level loggers.
import logging  # noqa: E402
import structlog  # noqa: E402

logging.basicConfig(level=logging.WARNING, stream=sys.stderr, force=True)
structlog.configure(
    processors=[structlog.dev.ConsoleRenderer()],
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
)

from mcp.server.stdio import stdio_server  # noqa: E402

# Import the shared server instance (tools + handlers defined in mcp_tools.py)
from rita.interfaces.mcp_auth import McpIdentity, identity_scope  # noqa: E402
from rita.interfaces.mcp_tools import server  # noqa: E402

STDIO_IDENTITY = McpIdentity(transport="stdio", caller="external")


async def _main() -> None:
    # Every call served by this process runs as the stdio identity (no user): the dispatch then
    # offers only the stdio tools and logs transport=stdio.
    with identity_scope(STDIO_IDENTITY):
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )


if __name__ == "__main__":
    asyncio.run(_main())
