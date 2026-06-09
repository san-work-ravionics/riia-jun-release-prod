from __future__ import annotations

from pydantic import BaseModel


class GeoInstrument(BaseModel):
    id: str
    name: str
    flag: str
    close: float | None
    daily_return_pct: float | None
    signal: str                           # "bullish" | "bearish" | "neutral"
    return_1y_pct:  float | None = None   # Phase 2: (close_latest/close_1y_ago − 1) × 100
    return_5y_pct:  float | None = None   # Phase 3: CAGR over ~5 trading years
    return_15y_pct: float | None = None   # Phase 3: CAGR over ~15 trading years
    risk_score: int | None = None         # Phase 2: annualised-vol bucket 1–5
    sector: str | None = None             # Phase 2: static lookup (no DB column yet)
    horizons: list[str] = []              # Phase 3: horizon keys from investment_horizons.py


class GeoRegion(BaseModel):
    region: str
    flag: str
    instruments: list[GeoInstrument]


class GeographyOverviewResponse(BaseModel):
    regions: list[GeoRegion]
