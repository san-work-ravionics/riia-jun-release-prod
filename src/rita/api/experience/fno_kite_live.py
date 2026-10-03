"""Experience Layer — Kite-live overlay for the Exposure step (F39 Phase 2 addendum).

ADR-001 Tier 3 (Experience Layer) — composes a read-only UI payload from an external
source (fno-margin-fetch), per the tier-decision-tree's "composes a read-only UI
payload from multiple sources -> Experience tier" clause.

GET /api/v1/experience/fno/kite-live?instrument_id=<id>[&strike=&option_type=&quantity=&transaction_type=]

`instrument_id` is required. The optional params (`strike`, `option_type`, `quantity`,
`transaction_type`) are only sent by the What-if step (Phase 3) when pricing a specific
hedge's margin; the Exposure step (Phase 2) calls this with `instrument_id` only.

Always returns HTTP 200. Failure (fno-margin-fetch not running, or running with an
expired Kite token) is represented in-payload (`available: false, source: "fallback"`),
never as a 4xx/5xx or exception to the caller. Read-only — no db.commit().
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query

from rita.auth import get_current_user
from rita.models.user import UserModel
from rita.schemas.kite_live import KiteLiveMargin, KiteLiveQuote, KiteLiveResponse
from rita.services.kite_middleware_client import fetch_kite_quote

router = APIRouter(prefix="/api/v1/experience/fno", tags=["experience:fno-kite-live"])


@router.get("/kite-live", response_model=KiteLiveResponse)
def get_kite_live(
    instrument_id: str = Query(...),
    strike: Optional[float] = Query(default=None),
    option_type: Optional[str] = Query(default=None),
    quantity: Optional[int] = Query(default=None),
    transaction_type: Optional[str] = Query(default=None),
    current_user: UserModel = Depends(get_current_user),
) -> KiteLiveResponse:
    """Best-effort live Kite quote/lot-size overlay. Never raises; always 200."""
    raw = fetch_kite_quote(
        instrument_id,
        strike=strike,
        option_type=option_type,
        quantity=quantity,
        transaction_type=transaction_type,
    )

    if raw is None:
        return KiteLiveResponse(
            instrument_id=instrument_id,
            available=False,
            source="fallback",
            lot_size=None,
            quote=None,
            margin=None,
            fetched_at=None,
        )

    quote: Optional[KiteLiveQuote] = None
    if any(raw.get(k) is not None for k in ("ltp", "bid", "ask")):
        quote = KiteLiveQuote(ltp=raw.get("ltp"), bid=raw.get("bid"), ask=raw.get("ask"))

    margin: Optional[KiteLiveMargin] = None
    # fno-margin-fetch has no per-order margin endpoint, so the client returns none;
    # kept so a future middleware margin leg needs no route change.
    if any(raw.get(k) is not None for k in ("required", "span", "exposure")):
        margin = KiteLiveMargin(
            required=raw.get("required"),
            span=raw.get("span"),
            exposure=raw.get("exposure"),
        )

    return KiteLiveResponse(
        instrument_id=instrument_id,
        available=True,
        source="kite",
        lot_size=raw.get("lot_size"),
        quote=quote,
        margin=margin,
        fetched_at=datetime.now(timezone.utc),
    )
