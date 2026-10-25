"""
System router — MCP call log.

GET /api/v1/mcp-calls?limit=100

Returns the most recent MCP tool invocations stored in the mcp_calls table.
Consumed by mcp.js → loadMcp() in the RITA dashboard (and ds/mcp.js, ds/model-mcp.js) via
shared/api.js api() — 401 → ensureDevToken(true) → retry once on localhost.
F44 P1: rows also carry transport, caller, user_id (nullable).

Auth (F44 P1 code review): a signed-in user is required. Users with ``can_access_ops`` see every
row; everyone else sees only rows with no user (stdio / anonymous calls) and their own rows.
Data access through MCPCallRepository (ADR-002).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.database import get_db
from rita.models.user import UserModel
from rita.repositories.mcp_call import MCPCallRepository

router = APIRouter(prefix="/api/v1/mcp-calls", tags=["system:mcp"])


@router.get("")
def list_mcp_calls(
    limit: int = Query(100, ge=1, le=500),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list:
    rows = MCPCallRepository(db).get_recent_visible_to(
        str(current_user.id),
        all_users=bool(getattr(current_user, "can_access_ops", False)),
        limit=limit,
    )
    return [
        {
            "call_id":        r.call_id,
            "timestamp":      str(r.timestamp),
            "tool_name":      r.tool_name,
            "status":         r.status,
            "duration_ms":    r.duration_ms,
            "args_summary":   r.args_summary or "",
            "result_summary": r.result_summary or "",
            "transport":      r.transport,   # F44 P1 — null for rows before P1
            "caller":         r.caller,
            "user_id":        r.user_id,
        }
        for r in rows
    ]
