"""Experience router — Jarvis page reads (F44 P4 A4–A6).

ADR-001 Tier 1 (Experience): read-only composition over the in-memory MCP client
(``Depends(mcp_client_dependency("jarvis"))`` — one session per request, the signed-in user).
No ``db.commit`` here or in ``JarvisPageService``; the only side effect is the ``mcp_calls`` log.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from rita.auth import get_current_user
from rita.database import get_db
from rita.interfaces.mcp_client import McpRequestClient, mcp_client_dependency
from rita.models.user import UserModel
from rita.schemas.jarvis import InstrumentPageOut, Location, PortfolioPageOut, StateOut
from rita.services.jarvis_page_service import JarvisPageService, PageError

router = APIRouter(prefix="/api/v1/experience/jarvis", tags=["experience:jarvis"])

_mcp = mcp_client_dependency("jarvis")


@router.get("/state", response_model=StateOut)
def jarvis_state(location: Location = Query(...), user: UserModel = Depends(get_current_user),
                 db: Session = Depends(get_db), mcp: McpRequestClient = Depends(_mcp)) -> StateOut:
    """A4: goal, journey, the open session's last messages, chips and the model's view today."""
    return JarvisPageService(db, mcp, user).state(location)


@router.get("/portfolio", response_model=PortfolioPageOut)
def jarvis_portfolio(location: Location = Query(...), user: UserModel = Depends(get_current_user),
                     db: Session = Depends(get_db), mcp: McpRequestClient = Depends(_mcp)) -> PortfolioPageOut:
    """A5: this plan year's return against the goal path, the instrument grid and the engines."""
    return JarvisPageService(db, mcp, user).portfolio(location)


@router.get("/instrument", response_model=InstrumentPageOut)
def jarvis_instrument(location: Location = Query(...),
                      instrument: str = Query(..., pattern=r"^[A-Za-z0-9_-]{1,32}$"),
                      user: UserModel = Depends(get_current_user), db: Session = Depends(get_db),
                      mcp: McpRequestClient = Depends(_mcp)) -> InstrumentPageOut:
    """A6: per-engine prices, markers, levels, series, rationale and performance for one instrument."""
    try:
        return JarvisPageService(db, mcp, user).instrument(location, instrument)
    except PageError as exc:
        if exc.code == "not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc
