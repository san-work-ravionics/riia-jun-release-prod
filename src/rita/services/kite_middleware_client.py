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
from datetime import date
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


# NFO option master: underlying name -> [{expiry: date, strike: float, symbol: str}] (PE only).
_pe_cache: tuple[float, dict[str, list[dict[str, Any]]]] | None = None
_pe_fail_until: float = 0.0
_PE_FAIL_BACKOFF_SECONDS = 60.0

# Our instrument ids that differ from the Kite NFO underlying name.
_NFO_NAME_ALIAS = {"MM": "M&M", "TATAMOTOR": "TATAMOTORS"}
# Target tenor for "monthly cost": nearest listed expiry at least this many days out.
_MIN_DAYS_TO_EXPIRY = 20


def _reset_cache() -> None:
    """Clear the lot-size / option-master caches (tests)."""
    global _pe_cache, _pe_fail_until
    _lot_cache.clear()
    _pe_cache = None
    _pe_fail_until = 0.0


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


# ── Real put premium (hedge cost) ──────────────────────────────────────────────

def _pe_contracts(base_url: str) -> Optional[dict[str, list[dict[str, Any]]]]:
    """PE contracts from the NFO instrument master grouped by underlying; None on failure.

    Cached for an hour; a failed fetch is remembered for a minute so a down middleware
    does not cost one timeout per holding.
    """
    global _pe_cache, _pe_fail_until
    now = time.monotonic()
    if _pe_cache and _pe_cache[0] > now:
        return _pe_cache[1]
    if now < _pe_fail_until:
        return None
    body = _request("GET", f"{base_url}/api/instruments",
                    params={"exchange": "NFO", "limit": _INSTRUMENTS_LIMIT})
    if body is None:
        _pe_fail_until = now + _PE_FAIL_BACKOFF_SECONDS
        return None
    out: dict[str, list[dict[str, Any]]] = {}
    for inst in body.get("instruments") or []:
        if not isinstance(inst, dict) or inst.get("instrument_type") != "PE":
            continue
        try:
            exp = date.fromisoformat(str(inst["expiry"])[:10])
            strike = float(inst["strike"])
        except (KeyError, TypeError, ValueError):
            continue
        out.setdefault(inst.get("name"), []).append(
            {"expiry": exp, "strike": strike, "symbol": inst.get("tradingsymbol")}
        )
    _pe_cache = (now + _LOT_CACHE_TTL_SECONDS, out)
    return out


def _pick_expiry(contracts: list[dict[str, Any]], today: date) -> Optional[date]:
    """Nearest expiry >= _MIN_DAYS_TO_EXPIRY out (so it is a ~monthly tenor); else the farthest."""
    expiries = sorted({c["expiry"] for c in contracts if c["expiry"] > today})
    if not expiries:
        return None
    for e in expiries:
        if (e - today).days >= _MIN_DAYS_TO_EXPIRY:
            return e
    return expiries[-1]


def _nearest(contracts: list[dict[str, Any]], expiry: date, target: float) -> Optional[dict[str, Any]]:
    legs = [c for c in contracts if c["expiry"] == expiry and c.get("symbol")]
    return min(legs, key=lambda c: abs(c["strike"] - target)) if legs else None


def _px(q: Optional[dict[str, Any]], side: str) -> Optional[float]:
    """Executable price: best ask when buying (side='sell' depth), best bid when selling; else LTP."""
    if not isinstance(q, dict):
        return None
    depth = q.get("depth") or {}
    book = (depth.get(side) or [{}]) if isinstance(depth, dict) else [{}]
    p = book[0].get("price") if book and isinstance(book[0], dict) else None
    if isinstance(p, (int, float)) and p > 0:
        return float(p)
    ltp = q.get("last_price")
    return float(ltp) if isinstance(ltp, (int, float)) and ltp > 0 else None


def fetch_put_premium(
    instrument_id: str,
    strike_pct: float,
    spread_width_pct: Optional[float] = None,
    today: Optional[date] = None,
) -> Optional[dict[str, Any]]:
    """Real put-hedge cost from Kite option quotes, as % of spot per share (lot size cancels).

    strike_pct is the OTM distance (negative, e.g. -7.5). Picks the nearest listed PE strike
    to spot*(1+strike_pct/100) on the nearest ~monthly expiry. With spread_width_pct it prices a
    put spread: buy that strike at the ask, sell the strike spread_width_pct lower at the bid.
    Returns {cost_pct, expiry, detail, spot} or None when anything is unavailable (never raises;
    callers keep their model estimate).
    """
    try:
        base_url = get_settings().integrations.fno_margin_fetch_base_url.rstrip("/")
        pes = _pe_contracts(base_url)
        if pes is None:
            return None
        name = _NFO_NAME_ALIAS.get(instrument_id, instrument_id)
        contracts = pes.get(name)
        if not contracts:
            return None
        today = today or date.today()
        expiry = _pick_expiry(contracts, today)
        if expiry is None:
            return None
        spot_key = f"NSE:{_INDEX_QUOTE_SYMBOL.get(instrument_id, name)}"
        # Spot first, so the strike target is known before the option legs are chosen.
        spot_body = _request("POST", f"{base_url}/api/quotes", json={"instruments": [spot_key]})
        spot_q = ((spot_body or {}).get("data") or {}).get(spot_key)
        spot = spot_q.get("last_price") if isinstance(spot_q, dict) else None
        spot = float(spot) if isinstance(spot, (int, float)) and spot > 0 else None
        if not spot:
            return None
        buy_leg = _nearest(contracts, expiry, spot * (1.0 + strike_pct / 100.0))
        sell_leg = (
            _nearest(contracts, expiry, spot * (1.0 + (strike_pct - spread_width_pct) / 100.0))
            if spread_width_pct else None
        )
        if buy_leg is None or (spread_width_pct and (sell_leg is None or sell_leg["strike"] >= buy_leg["strike"])):
            return None
        keys = [f"NFO:{buy_leg['symbol']}"] + ([f"NFO:{sell_leg['symbol']}"] if sell_leg else [])
        body = _request("POST", f"{base_url}/api/quotes", json={"instruments": keys})
        data = (body or {}).get("data") or {}
        buy_px = _px(data.get(keys[0]), "sell")
        if buy_px is None:
            return None
        net = buy_px
        detail = f"Zerodha {buy_leg['symbol']} @ {buy_px:g}"
        if sell_leg:
            sell_px = _px(data.get(keys[1]), "buy")
            if sell_px is None:
                return None
            net = buy_px - sell_px
            detail += f" − {sell_leg['symbol']} @ {sell_px:g}"
        return {"cost_pct": round(net / spot * 100.0, 3), "expiry": expiry.isoformat(),
                "detail": f"{detail} (expiry {expiry.isoformat()})", "spot": spot}
    except Exception as exc:  # defensive: the contract is "never raise"
        log.warning("kite_middleware.put_premium_unexpected", instrument_id=instrument_id, error=str(exc))
        return None
