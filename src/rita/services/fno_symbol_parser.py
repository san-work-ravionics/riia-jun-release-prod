"""Pure Zerodha F&O tradingsymbol parser (F42 Phase 2).  No I/O, no lot sizes.

Patterns (upper-cased, trimmed symbol):
  monthly option  NIFTY26OCT24500CE   -> expiry month known, day NOT guessed
  weekly option   NIFTY2610724500CE   -> month code 1-9 or O/N/D, 2-digit day => full date
                  NIFTY26O0724500CE
  future          NIFTY26OCTFUT

parse_status: ``ok`` = pattern matched; ``fallback`` = matched and an underlying alias was
applied; ``unparsed`` = nothing matched (never raises, never rejects the row).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}
_MON = "|".join(_MONTHS)
_WEEKLY_MONTH = {**{str(i): i for i in range(1, 10)}, "O": 10, "N": 11, "D": 12}

_MONTHLY = re.compile(
    rf"^(?P<u>[A-Z&\-]+?)(?P<yy>\d{{2}})(?P<mon>{_MON})(?P<k>\d+(?:\.\d+)?)(?P<t>CE|PE)$")
_WEEKLY = re.compile(
    r"^(?P<u>[A-Z&\-]+?)(?P<yy>\d{2})(?P<m>[1-9OND])(?P<dd>\d{2})"
    r"(?P<k>\d+(?:\.\d+)?)(?P<t>CE|PE)$")
_FUT = re.compile(rf"^(?P<u>[A-Z&\-]+?)(?P<yy>\d{{2}})(?P<mon>{_MON})FUT$")
_LEAD = re.compile(r"^[A-Z]+")


@dataclass(frozen=True)
class SymbolInfo:
    underlying: Optional[str]
    instrument_type: str  # CE | PE | FUT | UNKNOWN
    strike: Optional[Decimal]
    opt_expiry: Optional[date]  # only known for weekly symbols; monthly -> None
    expiry_ym: Optional[str]  # YYYY-MM
    parse_status: str  # ok | fallback | unparsed


def _ym(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def parse_symbol(symbol: str, aliases: Optional[dict[str, str]] = None) -> SymbolInfo:
    """Parse a tradingsymbol; never raises."""
    s = (symbol or "").strip().upper()
    amap = {k.strip().upper(): v.strip().upper() for k, v in (aliases or {}).items()}

    def _und(u: str) -> tuple[str, str]:
        if u in amap:
            return amap[u], "fallback"
        return u, "ok"

    m = _MONTHLY.match(s)
    if m:
        u, st = _und(m["u"])
        return SymbolInfo(u, m["t"], Decimal(m["k"]), None,
                          _ym(2000 + int(m["yy"]), _MONTHS[m["mon"]]), st)
    m = _FUT.match(s)
    if m:
        u, st = _und(m["u"])
        return SymbolInfo(u, "FUT", None, None,
                          _ym(2000 + int(m["yy"]), _MONTHS[m["mon"]]), st)
    m = _WEEKLY.match(s)
    if m:
        u, st = _und(m["u"])
        year, month = 2000 + int(m["yy"]), _WEEKLY_MONTH[m["m"]]
        try:
            exp: Optional[date] = date(year, month, int(m["dd"]))
        except ValueError:
            exp = None
        return SymbolInfo(u, m["t"], Decimal(m["k"]), exp, _ym(year, month), st)

    lead = _LEAD.match(s)
    return SymbolInfo(lead.group(0) if lead else None, "UNKNOWN", None, None, None, "unparsed")
