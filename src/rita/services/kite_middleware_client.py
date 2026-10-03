"""Thin HTTP client for `fno-margin-fetch` (local-dev-only Zerodha/Kite middleware).

F39 Phase 2 addendum, corrected in Phase 3 against the real fno-margin-fetch routes
(`~/work/fno-margin-fetch/fno-margin-fetch/src/main.py`):

  GET  /api/instruments?exchange=NFO&limit=N  -> {success, instruments:[{name, lot_size, ...}]}
  POST /api/quotes {"instruments": ["NSE:<symbol>"]}
                                              -> {success, data:{"NSE:<symbol>": {last_price, depth}}}

This client is deliberately "best-effort": it never raises. Every failure mode —
connection refused, timeout, non-2xx (e.g. 401 expired Kite token), `success:false`,
unparseable body — is caught in ONE path (`_request`) and treated identically: the leg
yields None. When no leg yields data the client returns None and the route layer
(`api/experience/fno_kite_live.py`) maps that to `available=False, source="fallback"`.

Margin: fno-margin-fetch exposes no per-order/per-hedge margin endpoint (only the
account-level `GET /api/margins`), so margin is never returned here — callers keep
the BSM estimate. Nothing is fabricated. No Kite credentials live in this codebase.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx
import structlog

from rita.config import get_settings

log = structlog.get_logger()

_TIMEOUT_SECONDS = 1.8
# NFO instrument master is large; request the whole list (default server limit is 100).
_INSTRUMENTS_LIMIT = 1_000_000
_LOT_CACHE_TTL_SECONDS = 3600.0

# Kite quote keys for index underlyings differ from their NFO contract names.
_INDEX_QUOTE_SYMBOL = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK"}

# instrument_id -> (expires_at_monotonic, lot_size)
_lot_cache: dict[str, tuple[float, int]] = {}


def _reset_cache() -> None:
    """Clear the lot-size cache (tests)."""
    _lot_cache.clear()


def _request(method: str, url: str, **kwargs: Any) -> Optional[dict[str, Any]]:
    """Single failure path: returns the parsed body, or None on ANY failure."""
    try:
        resp = httpx.request(method, url, timeout=_TIMEOUT_SECONDS, **kwargs)
    except httpx.RequestError as exc:  # connect error, timeout, etc.
        log.info("kite_middleware.request_failed", url=url, error=str(exc))
        return None
    if not (200 <= resp.status_code < 300):
        log.warning("kite_middleware.non_2xx", url=url, status_code=resp.status_code)
        return None
    try:
        body = resp.json()
    except ValueError as exc:
        log.warning("kite_middleware.bad_json", url=url, error=str(exc))
        return None
    if not isinstance(body, dict) or body.get("success") is not True:
        log.info("kite_middleware.success_false", url=url)
        return None
    return body


def _lot_size(base_url: str, instrument_id: str) -> Optional[int]:
    """Lot size from the NFO instrument master; None unless every contract agrees."""
    cached = _lot_cache.get(instrument_id)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    body = _request(
        "GET",
        f"{base_url}/api/instruments",
        params={"exchange": "NFO", "limit": _INSTRUMENTS_LIMIT},
    )
    if body is None:
        return None
    sizes = {
        inst.get("lot_size")
        for inst in (body.get("instruments") or [])
        if isinstance(inst, dict) and inst.get("name") == instrument_id
    }
    if len(sizes) != 1:  # none found, or ambiguous across contracts
        return None
    size = next(iter(sizes))
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        return None
    _lot_cache[instrument_id] = (time.monotonic() + _LOT_CACHE_TTL_SECONDS, size)
    return size


def _quote(base_url: str, instrument_id: str) -> Optional[dict[str, Optional[float]]]:
    key = f"NSE:{_INDEX_QUOTE_SYMBOL.get(instrument_id, instrument_id)}"
    body = _request("POST", f"{base_url}/api/quotes", json={"instruments": [key]})
    if body is None:
        return None
    q = (body.get("data") or {}).get(key)
    if not isinstance(q, dict):
        return None
    depth = q.get("depth") or {}
    buy = (depth.get("buy") or [{}])[0] if isinstance(depth, dict) else {}
    sell = (depth.get("sell") or [{}])[0] if isinstance(depth, dict) else {}
    return {
        "ltp": q.get("last_price"),
        "bid": buy.get("price") if isinstance(buy, dict) else None,
        "ask": sell.get("price") if isinstance(sell, dict) else None,
    }


def fetch_kite_quote(
    instrument_id: str,
    *,
    strike: Optional[float] = None,
    option_type: Optional[str] = None,
    quantity: Optional[int] = None,
    transaction_type: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Best-effort lot-size + quote overlay from `fno-margin-fetch`.

    Returns {"lot_size", "ltp", "bid", "ask"} (any value may be None) when at least one
    leg succeeded, or None when nothing could be fetched. Never raises. The order
    parameters (strike/option_type/quantity/transaction_type) are accepted for the
    What-if call shape but unused: no per-order margin endpoint exists, so no margin
    keys are ever returned.
    """
    try:
        base_url = get_settings().integrations.fno_margin_fetch_base_url.rstrip("/")
        lot = _lot_size(base_url, instrument_id)
        quote = _quote(base_url, instrument_id)
    except Exception as exc:  # defensive: the contract is "never raise"
        log.warning("kite_middleware.unexpected", instrument_id=instrument_id, error=str(exc))
        return None
    if lot is None and quote is None:
        return None
    return {
        "lot_size": lot,
        "ltp": quote["ltp"] if quote else None,
        "bid": quote["bid"] if quote else None,
        "ask": quote["ask"] if quote else None,
    }
