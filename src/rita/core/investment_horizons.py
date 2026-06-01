"""Investment horizon screening thresholds.

Edit this file to recalibrate rules without touching application code.
All values are consumed by:
    src/rita/api/experience/rita.py → geography_overview()

Each horizon key is also sent verbatim to the JS layer as elements of
GeoInstrument.horizons, so keep them stable identifiers.
"""
from __future__ import annotations

# ── Thresholds ─────────────────────────────────────────────────────────────────
#
# return_field   — which computed metric to compare against min_return_pct.
#                  Must be one of: return_1y_pct | return_5y_pct | return_15y_pct
# min_return_pct — minimum annualised return (%) for an instrument to qualify.
# lookback_td    — look-back window in trading days used to compute that metric.
#                  Instruments with fewer cached rows than this are skipped.
# years          — number of years (used in CAGR formula: value^(1/years) − 1).
#                  Set to 1 for return_1y_pct (simple return, no CAGR).

INVESTMENT_HORIZONS: dict[str, dict] = {
    "short_term": {
        "label":          "Short Term",
        "description":    "> 15 % total return in the last 1 year",
        "return_field":   "return_1y_pct",
        "min_return_pct": 15.0,
        "lookback_td":    253,    # ~1 trading year
        "years":          1,      # simple return (not CAGR)
    },
    "medium_term": {
        "label":          "Medium Term",
        "description":    "> 12 % annualised CAGR over the last 5 years",
        "return_field":   "return_5y_pct",
        "min_return_pct": 12.0,
        "lookback_td":    1260,   # ~5 trading years
        "years":          5,
    },
    "long_term": {
        "label":          "Long Term",
        "description":    "> 8 % annualised CAGR over the last 15 years",
        "return_field":   "return_15y_pct",
        "min_return_pct": 8.0,
        "lookback_td":    3780,   # ~15 trading years
        "years":          15,
    },
}
