"""Thin HTTP client for `fno-margin-fetch` (local-dev-only Zerodha/Kite middleware).

F39 Phase 2 addendum. This client is deliberately "best-effort": it never raises.
Both failure modes are caught in the same path and treated identically by the caller:
  (a) connection failure / timeout (fno-margin-fetch not running at all)
  (b) a non-2xx / error response (fno-margin-fetch running but e.g. the Kite access
      token has expired — a known recurring re-auth issue)
Either failure returns None; the route layer (`api/experience/fno_kite_live.py`) maps
None to `available=False, source="fallback"`. No Kite credentials live here or
anywhere else in this codebase — fno-margin-fetch holds its own local config.

TBC — confirm, don't fabricate: the exact endpoint path and field names
`fno-margin-fetch` itself expects/returns are undocumented from this workspace. The
`/quote` path and `lot_size`/`ltp`/`bid`/`ask` field names below are a reasonable
placeholder for the Exposure-step (quote + lot-size) leg only — confirm the real shape
against the live `fno-margin-fetch` API before relying on this in production. The
margin-calc leg (Phase 3 What-if) is explicitly out of scope here (same addendum TBC).
"""
from __future__ import annotations

from typing import Any, Optional

import httpx
import structlog

from rita.config import get_settings

log = structlog.get_logger()

_TIMEOUT_SECONDS = 1.8


def fetch_kite_quote(
    instrument_id: str,
    *,
    strike: Optional[float] = None,
    option_type: Optional[str] = None,
    quantity: Optional[int] = None,
    transaction_type: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Best-effort call to `fno-margin-fetch` for a live quote/lot-size.

    Returns the parsed JSON dict on a 2xx response, or None on ANY failure —
    connection refused, timeout, non-2xx status, or unparseable body. Never raises.
    """
    base_url = get_settings().integrations.fno_margin_fetch_base_url.rstrip("/")
    params: dict[str, Any] = {"instrument_id": instrument_id}
    for key, val in (
        ("strike", strike),
        ("option_type", option_type),
        ("quantity", quantity),
        ("transaction_type", transaction_type),
    ):
        if val is not None:
            params[key] = val

    try:
        resp = httpx.get(f"{base_url}/quote", params=params, timeout=_TIMEOUT_SECONDS)
    except (httpx.TimeoutException, httpx.ConnectError, httpx.RequestError) as exc:
        # Failure mode (a): connection refused / timeout — fno-margin-fetch not running.
        log.info(
            "kite_middleware.connect_failed",
            instrument_id=instrument_id,
            error=str(exc),
        )
        return None

    if not (200 <= resp.status_code < 300):
        # Failure mode (b): non-2xx — e.g. expired Kite token, 401/500 from the
        # middleware. Caught explicitly here, not just connection exceptions.
        log.warning(
            "kite_middleware.non_2xx",
            instrument_id=instrument_id,
            status_code=resp.status_code,
        )
        return None

    try:
        return resp.json()
    except ValueError as exc:
        log.warning(
            "kite_middleware.bad_json",
            instrument_id=instrument_id,
            error=str(exc),
        )
        return None
