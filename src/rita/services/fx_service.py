"""FX service (F44 P2) — daily FX rates for multi-currency portfolios.

Rates come **only** from ``market_data_cache`` through ``MarketDataCacheRepository`` (rows
``FX_EURINR`` / ``FX_EURUSD``, close = units of quote per 1 EUR).  Those rows are written by
``services/data_refresh.refresh_fx`` during the ``/refresh-all-instruments-data`` skill run —
this module never makes a network call (org.md §3).  A missing rate is ``None``: callers hide
the converted amount ("FX rate unavailable"); there is no static fallback.

Every currency is reached through EUR: ``rate(base, quote) = eur_to(quote) / eur_to(base)``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from rita.repositories.market_data import MarketDataCacheRepository

SUPPORTED_CURRENCIES: tuple[str, ...] = ("EUR", "INR", "USD")
PIVOT = "EUR"
FX_UNDERLYING_PREFIX = "FX_"
# market_data_cache underlying → Yahoo Finance ticker (used by the refresh skill only)
FX_YF_TICKERS: dict[str, str] = {
    "FX_EURINR": "EURINR=X",
    "FX_EURUSD": "EURUSD=X",
}
SOURCE = "market_data_cache"


def fx_underlying(quote: str) -> str:
    """Cache underlying holding EUR→``quote`` (e.g. ``FX_EURINR``)."""
    return f"{FX_UNDERLYING_PREFIX}{PIVOT}{quote.upper()}"


@dataclass(frozen=True)
class FxRate:
    base: str
    quote: str
    rate: float
    as_of: date | None   # None only for base == quote
    source: str


class FxService:
    def __init__(self, db: Session) -> None:
        self._repo = MarketDataCacheRepository(db)

    def _eur_to(self, ccy: str, as_of: date | None) -> tuple[float, date | None] | None:
        if ccy == PIVOT:
            return 1.0, None
        und = fx_underlying(ccy)
        row = self._repo.find_latest(und) if as_of is None else self._repo.find_latest_on_or_before(und, as_of)
        if row is None or not row.close or row.close <= 0:
            return None
        return float(row.close), row.date

    def rate(self, base: str, quote: str, as_of: date | None = None) -> FxRate | None:
        """Units of ``quote`` per 1 ``base`` from the latest cached rate (on/before ``as_of``)."""
        base, quote = base.upper(), quote.upper()
        if base not in SUPPORTED_CURRENCIES or quote not in SUPPORTED_CURRENCIES:
            raise ValueError(f"unsupported currency pair {base}/{quote}")
        if base == quote:
            return FxRate(base, quote, 1.0, None, "identity")
        b = self._eur_to(base, as_of)
        q = self._eur_to(quote, as_of)
        if b is None or q is None:
            return None
        dates = [d for d in (b[1], q[1]) if d is not None]
        return FxRate(base, quote, q[0] / b[0], min(dates) if dates else None, SOURCE)

    def convert(self, amount: float | None, base: str, quote: str) -> float | None:
        """``amount`` in ``base`` → ``quote``; None when the amount or the rate is missing."""
        if amount is None:
            return None
        r = self.rate(base, quote)
        return None if r is None else amount * r.rate

    def eur_per_unit(self) -> dict[str, float]:
        """EUR value of 1 unit of each supported currency that has a cached rate (EUR always)."""
        out: dict[str, float] = {}
        for ccy in SUPPORTED_CURRENCIES:
            r = self.rate(ccy, PIVOT)
            if r is not None:
                out[ccy] = r.rate
        return out
