"""Workflow router — Jarvis chat (F44 P4 A1–A3).

ADR-001 Tier 2 (Business Process): loads the chat model, opens sessions, and runs one message
(classify → tool plan over the in-memory MCP client → journey / session / message writes).
Calls ``JarvisChatService`` only.  A1–A3 use ``McpRequestClient(identity_for(user, "jarvis"))`` —
one in-memory MCP session per request, run as the signed-in user.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.database import get_db
from rita.interfaces.mcp_client import McpRequestClient, identity_for
from rita.models.user import UserModel
from rita.schemas.jarvis import MessageIn, MessageOut, SessionIn, SessionOut, WarmupOut
from rita.services.jarvis_chat_service import JarvisChatError, JarvisChatService, warmup

router = APIRouter(prefix="/api/v1/workflow/jarvis", tags=["workflow:jarvis"])


def _http(exc: JarvisChatError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if exc.code == "not_found" else status.HTTP_503_SERVICE_UNAVAILABLE
    return HTTPException(status_code=code, detail=exc.message)


@router.post("/warmup", response_model=WarmupOut)
def jarvis_warmup(_user: UserModel = Depends(get_current_user)) -> WarmupOut:
    """A1: load MiniLM (shared with RITA chat) and build the journey intent index."""
    try:
        return warmup()
    except JarvisChatError as exc:
        raise _http(exc) from exc


@router.post("/session", response_model=SessionOut)
def jarvis_session(body: SessionIn, user: UserModel = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> SessionOut:
    """A2: reuse the user's open session for the location (idle ≤ ``jarvis.session_idle_minutes``)
    or open a new one."""
    with McpRequestClient(identity_for(user, "jarvis")) as mcp:
        return JarvisChatService(db, mcp, user).open_session(body.location)


@router.post("/message", response_model=MessageOut)
def jarvis_message(body: MessageIn, user: UserModel = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> MessageOut:
    """A3: one chat turn.  404 when the session is missing or owned by another user."""
    try:
        with McpRequestClient(identity_for(user, "jarvis")) as mcp:
            return JarvisChatService(db, mcp, user).message(body)
    except JarvisChatError as exc:
        raise _http(exc) from exc
