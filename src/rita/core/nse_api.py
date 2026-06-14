"""NSE India option chain client.

Public entry point:
    fetch_nse_equity_option_chain(instrument_id) -> dict | None

Returns near-month calls and puts with real strikes and LTP from NSE.
Falls back silently (returns None) on any connectivity or parse failure.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Internal instrument_id → NSE option chain symbol
_NSE_SYMBOL: dict[str, str] = {
    "MM":        "M&M",
    "RELIANCE":  "RELIANCE",
    "SBIN":      "SBIN",
    "TCS":       "TCS",
    "INFY":      "INFY",
    "HDFCBANK":  "HDFCBANK",
    "WIPRO":     "WIPRO",
    "BAJFINANCE":"BAJFINANCE",
    "AXISBANK":  "AXISBANK",
    "ICICIBANK": "ICICIBANK",
    "KOTAKBANK": "KOTAKBANK",
    "SUNPHARMA": "SUNPHARMA",
    "TATASTEEL": "TATASTEEL",
    "LT":        "LT",
    "ONGC":      "ONGC",
    "NTPC":      "NTPC",
}


def fetch_nse_equity_option_chain(instrument_id: str) -> dict[str, Any] | None:
    """Fetch the near-month equity option chain for an NSE F&O stock.

    Returns:
        {
            'spot':   float,
            'expiry': str,         # e.g. '30-Jun-2026'
            'calls':  [{'strike': float, 'ltp': float, 'iv': float, 'oi': int}, ...],
            'puts':   [{'strike': float, 'ltp': float, 'iv': float, 'oi': int}, ...],
        }
        or None on any failure (network, parse, no data).

    Strikes are from the actual NSE contract listing — not computed.
    LTP (last traded price) is the most recent market price.
    """
    try:
        from jugaad_data.nse import NSELive  # lazy import — pip install jugaad-data
    except ImportError:
        log.warning("nse_api.nse_client_not_installed")
        return None

    uid = instrument_id.upper()
    symbol = _NSE_SYMBOL.get(uid, uid)

    try:
        nse = NSELive()
        payload = nse.equities_option_chain(symbol)
    except Exception as exc:
        log.warning("nse_api.fetch_failed", instrument=uid, error=str(exc))
        return None

    records = payload.get("records", {})
    expiry_dates = records.get("expiryDates", [])
    if not expiry_dates:
        log.warning("nse_api.no_expiries", instrument=uid)
        return None

    near_expiry = expiry_dates[0]
    spot = float(records.get("underlyingValue") or 0)
    chain = records.get("data", [])

    calls: list[dict] = []
    puts:  list[dict] = []

    for item in chain:
        # NSE chain item uses 'expiryDates' (not 'expiryDate') at top level
        if item.get("expiryDates") != near_expiry:
            continue
        strike = float(item["strikePrice"])

        ce = item.get("CE") or {}
        if ce.get("lastPrice", 0) > 0:
            calls.append({
                "strike": strike,
                "ltp":    float(ce["lastPrice"]),
                "iv":     float(ce.get("impliedVolatility") or 0),
                "oi":     int(ce.get("openInterest") or 0),
            })

        pe = item.get("PE") or {}
        if pe.get("lastPrice", 0) > 0:
            puts.append({
                "strike": strike,
                "ltp":    float(pe["lastPrice"]),
                "iv":     float(pe.get("impliedVolatility") or 0),
                "oi":     int(pe.get("openInterest") or 0),
            })

    if not calls or not puts:
        log.warning("nse_api.empty_chain", instrument=uid, expiry=near_expiry)
        return None

    return {
        "spot":   spot,
        "expiry": near_expiry,
        "calls":  sorted(calls, key=lambda x: x["strike"]),
        "puts":   sorted(puts,  key=lambda x: x["strike"]),
    }
