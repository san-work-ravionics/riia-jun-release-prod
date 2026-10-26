"""Country → geography bucket rule — the one copy (F44 P2 review #9a).

Used by the RITA geography overview (``api/experience/rita.py``: region buckets India / US / EU /
Other) and by ``services/user_portfolio_service.py`` (instrument → portfolio location), so the two
cannot drift.  Pure: no I/O.
"""
from __future__ import annotations

EU_COUNTRY_CODES = frozenset({"NL", "DE", "FR", "GB", "BE", "CH", "SE", "ES", "IT", "AT", "FI", "DK", "IE", "PL", "PT"})
EU_COUNTRY_NAMES = frozenset({
    "netherlands", "germany", "france", "united kingdom", "belgium", "switzerland", "sweden",
    "spain", "italy", "austria", "finland", "denmark", "ireland", "poland", "portugal",
})

# geography bucket → portfolio location (``retirement_plan.locations`` keys); "Other" has none
REGION_LOCATION = {"India": "india", "US": "us", "EU": "europe"}


def country_to_region(country_code: str | None) -> str:
    """Map a country_code string to a geography bucket: "India" | "US" | "EU" | "Other".

    Accepts both ISO-2 codes ('US', 'IN') and full names ('United States', 'India') because
    yfinance returns full names which get stored as-is.
    """
    raw = (country_code or "").strip()
    cc = raw.upper()
    name = raw.lower()
    if cc in ("IN",) or name == "india":
        return "India"
    if cc in ("US", "USA") or name in ("united states", "united states of america"):
        return "US"
    if cc in EU_COUNTRY_CODES or name in EU_COUNTRY_NAMES:
        return "EU"
    return "Other"


def country_to_location(country_code: str | None) -> str | None:
    """Portfolio location for a country (``None`` for the "Other" bucket)."""
    return REGION_LOCATION.get(country_to_region(country_code))
