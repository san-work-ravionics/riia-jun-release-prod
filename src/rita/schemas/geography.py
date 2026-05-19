from __future__ import annotations

from pydantic import BaseModel


class GeoInstrument(BaseModel):
    id: str
    name: str
    flag: str
    close: float | None
    daily_return_pct: float | None
    signal: str  # "bullish" | "bearish" | "neutral"


class GeoRegion(BaseModel):
    region: str
    flag: str
    instruments: list[GeoInstrument]


class GeographyOverviewResponse(BaseModel):
    regions: list[GeoRegion]
