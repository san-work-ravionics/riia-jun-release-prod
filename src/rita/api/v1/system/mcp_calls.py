"""
System router — MCP call log.

GET /api/v1/mcp-calls?limit=100

Returns the most recent MCP tool invocations stored in the mcp_calls table.
Consumed by mcp.js → loadMcp() in the RITA dashboard (and ds/mcp.js, ds/model-mcp.js, ops overview /
observability, mobile ops) via shared/api.js api(). F44 P1: rows also carry transport, caller, user_id.

Visibility (F44 P1 code review pass 2 — user decision 2026-10-25, option B). The token is optional;
a missing, invalid or expired token is the anonymous view (200, never 401 — signed-out pages such as
the RITA dashboard in "no sign-in" mode keep working and never redirect from this route):
  - ``can_access_ops``        → every row in full;
  - signed in, not ops       → own rows and rows with no user in full; other users' rows anonymised;
  - anonymous                → every row anonymised.
Anonymised = ``user_id``, ``args_summary`` and ``result_summary`` are null; ``call_id, timestamp,
tool_name, status, duration_ms, transport, caller`` stay. Data access through MCPCallRepository (ADR-002).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from rita.auth import get_optional_user
from rita.database import get_db
from rita.models.user import UserModel
from rita.repositories.mcp_call import MCPCallRepository

router = APIRouter(prefix="/api/v1/mcp-calls", tags=["system:mcp"])


@router.get("")
def list_mcp_calls(
    limit: int = Query(100, ge=1, le=500),
    current_user: UserModel | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> list:
    rows = MCPCallRepository(db).get_recent_for_viewer(
        str(current_user.id) if current_user is not None else None,
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
            "args_summary":   (r.args_summary or "") if full else None,
            "result_summary": (r.result_summary or "") if full else None,
            "transport":      r.transport,   # F44 P1 — null for rows before P1
            "caller":         r.caller,
            "user_id":        r.user_id if full else None,
        }
        for r, full in rows
    ]
