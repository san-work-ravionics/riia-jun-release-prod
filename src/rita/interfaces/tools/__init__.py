"""MCP tool definitions, one module per namespace (F44 P1, ADR-007 §1).

Rules (checked by tests/unit/test_f44_p1_mcp_tools.py):
- a tool module imports services / core / schemas only — never ``rita.api.*`` (routers) or
  ``rita.repositories.*``;
- no tool input has a ``user_id`` — the user comes from the call identity;
- each handler opens its own DB session via ``ctx.session()``.
"""
from __future__ import annotations

from rita.interfaces.tools import fno, legacy, market, portfolio, whatineed
from rita.interfaces.tools._base import ToolContext, ToolError, ToolSpec, set_session_factory

__all__ = ["ToolContext", "ToolError", "ToolSpec", "all_tools", "set_session_factory"]


def all_tools() -> list[ToolSpec]:
    """Every registered tool: namespaced P1 tools, then the legacy aliases."""
    return [*whatineed.TOOLS, *portfolio.TOOLS, *fno.TOOLS, *market.TOOLS, *legacy.TOOLS]
