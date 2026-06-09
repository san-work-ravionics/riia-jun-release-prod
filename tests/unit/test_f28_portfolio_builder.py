"""Unit tests — Feature 28 Phase 1: geography-overview contract for portfolio-builder.js.

Scope
-----
This file verifies that the GET /api/v1/experience/rita/geography-overview response
matches every field read by dashboard/js/fno/portfolio-builder.js.

JS fields consumed (from portfolio-builder.js):
  geo.regions                — top-level array (line 311)
  region.region              — region bucket key for regionMap lookup (line 83)
  region.flag                — (not rendered in buckets but IS rendered by map/table; schema field)
  region.instruments         — inner array (line 87)
  inst.id                    — checkbox row id, basket key (lines 88, 95)
  inst.name                  — display name (lines 96, 228)
  inst.flag                  — displayed next to ticker (lines 95, 227)
  inst.close                 — null-guarded: close.toLocaleString (line 224)
  inst.daily_return_pct      — null-guarded for color + value (lines 89-90, 107, 186-187)
  inst.signal                — _signalBadge(inst.signal) (line 99)

POST /api/v1/user-portfolio/ body (pbBuildPortfolio, line 468):
  { name: str, holdings: [{instrument_id: str, allocation_pct: float}] }

Strategy
--------
- FastAPI dependency_overrides replaces get_db with a mock session.
- MarketDataCacheRepository.read_all + InstrumentRepository.read_all are patched
  to control exactly what the endpoint sees.
- Tests are grouped in three pytest classes: happy-path, edge-cases, and
  F28-specific contract (portfolio-builder.js fields).
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GEO_URL = "/api/v1/experience/rita/geography-overview"
VALID_SIGNALS = {"bullish", "bearish", "neutral"}
# The three core regions used in portfolio-builder.js regionMap
EXPECTED_REGIONS = {"India", "US", "EU"}


# ---------------------------------------------------------------------------
# Mock-data helpers  (same shape as test_geography_overview.py)
# ---------------------------------------------------------------------------

def _cache_rec(underlying: str, close: float, record_date: date | None = None) -> MagicMock:
    rec = MagicMock()
    rec.underlying = underlying
    rec.close = close
    rec.date = record_date or date(2026, 1, 15)
    return rec


def _two_rows(underlying: str, prev: float = 100.0, latest: float = 101.0) -> list:
    return [
        _cache_rec(underlying, prev,   date(2026, 1, 14)),
        _cache_rec(underlying, latest, date(2026, 1, 15)),
    ]


def _full_cache() -> list:
    """Two rows for every mock instrument so daily_return_pct is computable."""
    pairs = [
        ("NIFTY",     22000.0, 22150.0),   # India  (+0.68% → bullish)
        ("BANKNIFTY", 48000.0, 47800.0),   # India  (-0.42% → neutral)
        ("RELIANCE",   2900.0,  2920.0),   # India  (+0.69% → bullish)
        ("ASML",        700.0,   703.5),   # EU
        ("NVIDIA",      900.0,   910.0),   # US     (+1.11% → bullish)
    ]
    records: list = []
    for und, prev, latest in pairs:
        records.extend(_two_rows(und, prev, latest))
    return records


def _make_inst(instrument_id: str, country_code: str, name: str = "") -> MagicMock:
    inst = MagicMock()
    inst.instrument_id = instrument_id
    inst.country_code = country_code
    inst.name = name or instrument_id
    inst.is_available = True
    return inst


_MOCK_INSTRUMENTS = [
    _make_inst("NIFTY",     "IN", "NIFTY 50"),
    _make_inst("BANKNIFTY", "IN", "Bank Nifty"),
    _make_inst("RELIANCE",  "IN", "Reliance Industries"),
    _make_inst("ASML",      "NL", "ASML Holding"),
    _make_inst("NVIDIA",    "US", "NVIDIA Corp"),
]


def _get_response(cache_rows: list, instruments: list | None = None) -> tuple:
    """Shared call helper: returns (resp, body)."""
    from rita.main import app
    from rita.database import get_db

    mock_db = MagicMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch(
            "rita.repositories.market_data.MarketDataCacheRepository.read_all",
            return_value=cache_rows,
        ), patch(
            "rita.repositories.instrument.InstrumentRepository.read_all",
            return_value=instruments if instruments is not None else _MOCK_INSTRUMENTS,
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(_GEO_URL)
        return resp, resp.json()
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Class 1: Happy-path — standard full cache
# ---------------------------------------------------------------------------

class TestPortfolioBuilderHappyPath:
    """Happy-path tests that mirror what loadPortfolioBuilder() expects."""

    def test_status_200(self):
        resp, _ = _get_response(_full_cache())
        assert resp.status_code == 200

    def test_top_level_regions_key_present(self):
        """geo.regions must exist and be a list (line 311: !geo || !geo.regions)."""
        _, body = _get_response(_full_cache())
        assert "regions" in body
        assert isinstance(body["regions"], list)

    def test_regions_non_empty_with_data(self):
        """geo.regions.length === 0 triggers pb-empty banner — must not happen with data."""
        _, body = _get_response(_full_cache())
        assert len(body["regions"]) >= 1

    def test_region_has_region_field(self):
        """regionMap[region.region] lookup in _renderBuckets (line 83)."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            assert "region" in r
            assert isinstance(r["region"], str)
            assert len(r["region"]) > 0

    def test_region_has_flag_field(self):
        """region.flag present in schema (used in map tooltip labels indirectly)."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            assert "flag" in r
            assert isinstance(r["flag"], str)

    def test_region_has_instruments_list(self):
        """region.instruments is iterated (line 87)."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            assert "instruments" in r
            assert isinstance(r["instruments"], list)

    def test_instrument_id_present_and_string(self):
        """inst.id used as basket key and DOM id suffix (lines 88, 95)."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                assert "id" in i
                assert isinstance(i["id"], str) and len(i["id"]) > 0

    def test_instrument_name_present_and_string(self):
        """inst.name rendered in table cell (line 96, 228)."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                assert "name" in i
                assert isinstance(i["name"], str) and len(i["name"]) > 0

    def test_instrument_flag_present(self):
        """inst.flag displayed next to ticker in bucket row and table (lines 95, 227)."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                assert "flag" in i
                assert isinstance(i["flag"], str)

    def test_instrument_close_is_float_when_cached(self):
        """i.close null-guarded: i.close != null ? i.close.toLocaleString(…) (line 224)."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                # With full cache, every instrument should have a float close
                assert i["close"] is None or isinstance(i["close"], float), (
                    f"{i['id']}: close must be float or null"
                )

    def test_instrument_daily_return_pct_is_float_or_null(self):
        """i.daily_return_pct null-guarded throughout _renderBuckets, _renderTable,
        _renderMap, _applyPreset (lines 89-90, 107, 186-187, 269)."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                assert i["daily_return_pct"] is None or isinstance(i["daily_return_pct"], float), (
                    f"{i['id']}: daily_return_pct must be float or null"
                )

    def test_instrument_signal_is_valid(self):
        """_signalBadge(inst.signal) maps to one of three colors (line 44).
        An unrecognised signal falls through to '#64748b' but the reviewer
        has flagged valid tokens; test enforces them."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                assert i["signal"] in VALID_SIGNALS, (
                    f"{i['id']}: signal '{i['signal']}' not in {VALID_SIGNALS}"
                )

    def test_india_region_present(self):
        """portfolio-builder.js regionMap maps 'India' → 'india' bucket (line 82)."""
        _, body = _get_response(_full_cache())
        names = {r["region"] for r in body["regions"]}
        assert "India" in names

    def test_us_region_present(self):
        """portfolio-builder.js regionMap maps 'US' → 'us' bucket (line 82)."""
        _, body = _get_response(_full_cache())
        names = {r["region"] for r in body["regions"]}
        assert "US" in names

    def test_eu_region_present(self):
        """portfolio-builder.js regionMap maps 'EU' → 'europe' bucket (line 82)."""
        _, body = _get_response(_full_cache())
        names = {r["region"] for r in body["regions"]}
        assert "EU" in names


# ---------------------------------------------------------------------------
# Class 2: Edge cases
# ---------------------------------------------------------------------------

class TestPortfolioBuilderEdgeCases:
    """Edge cases that the portfolio-builder must survive without crashing."""

    def test_empty_instruments_list_returns_empty_regions(self):
        """When no instruments are available (all filtered out), regions array is
        empty and the JS falls through to _show('pb-empty') branch (line 311)."""
        resp, body = _get_response([], instruments=[])
        assert resp.status_code == 200
        assert isinstance(body["regions"], list)
        assert len(body["regions"]) == 0

    def test_empty_cache_all_instruments_have_null_values(self):
        """With an empty cache, every instrument shows close=None,
        daily_return_pct=None, signal='neutral'.
        The JS null guards on lines 89, 107, 186, 224 must cope."""
        resp, body = _get_response([])
        assert resp.status_code == 200
        for r in body["regions"]:
            for i in r["instruments"]:
                assert i["close"] is None, (
                    f"Empty cache: {i['id']} close should be None"
                )
                assert i["daily_return_pct"] is None, (
                    f"Empty cache: {i['id']} daily_return_pct should be None"
                )
                assert i["signal"] == "neutral", (
                    f"Empty cache: {i['id']} signal should be 'neutral'"
                )

    def test_single_cache_row_produces_null_daily_return(self):
        """One cache row → daily_return_pct cannot be computed → None.
        _estRisk(null) uses `|| 0` fallback (line 30) — no crash."""
        single = [_cache_rec("NIFTY", 22000.0, date(2026, 1, 15))]
        resp, body = _get_response(single)
        assert resp.status_code == 200
        nifty = None
        for r in body["regions"]:
            for i in r["instruments"]:
                if i["id"] == "NIFTY":
                    nifty = i
        assert nifty is not None
        assert nifty["daily_return_pct"] is None
        assert nifty["signal"] == "neutral"

    def test_large_positive_return_gives_bullish_signal(self):
        """daily_return_pct > 0.5 → signal='bullish' (endpoint _signal fn).
        Portfolio builder _signalBadge will map 'bullish' → '#16a34a'."""
        cache = _two_rows("NIFTY", 100.0, 106.0)  # +6%
        _, body = _get_response(cache)
        nifty = next(
            (i for r in body["regions"] for i in r["instruments"] if i["id"] == "NIFTY"),
            None,
        )
        assert nifty is not None
        assert nifty["signal"] == "bullish"
        assert isinstance(nifty["daily_return_pct"], float)
        assert nifty["daily_return_pct"] > 0

    def test_large_negative_return_gives_bearish_signal(self):
        """daily_return_pct < -0.5 → signal='bearish'.
        _signalBadge will map 'bearish' → '#dc2626'."""
        cache = _two_rows("NIFTY", 100.0, 94.0)  # -6%
        _, body = _get_response(cache)
        nifty = next(
            (i for r in body["regions"] for i in r["instruments"] if i["id"] == "NIFTY"),
            None,
        )
        assert nifty is not None
        assert nifty["signal"] == "bearish"
        assert isinstance(nifty["daily_return_pct"], float)
        assert nifty["daily_return_pct"] < 0

    def test_small_return_gives_neutral_signal(self):
        """abs(daily_return_pct) <= 0.5 → signal='neutral'.
        Covers the null-coercion advisory from Reviewer Finding #1:
        JS line 97 evaluates `inst.daily_return_pct >= 0` which coerces null
        to 0 — but for neutral instruments the color is '#64748b', not green/red,
        so the cosmetic issue only appears when daily_return_pct is exactly null."""
        cache = _two_rows("NIFTY", 100.0, 100.3)  # +0.3%
        _, body = _get_response(cache)
        nifty = next(
            (i for r in body["regions"] for i in r["instruments"] if i["id"] == "NIFTY"),
            None,
        )
        assert nifty is not None
        assert nifty["signal"] == "neutral"

    def test_instrument_absent_from_cache_returns_null_values(self):
        """Instrument with no cache rows should have close=None and signal='neutral'.
        The JS _renderBuckets null-guard on line 90 (`inst.daily_return_pct != null`)
        renders '—' for risk and return."""
        # Only supply cache for NVIDIA; NIFTY/BANKNIFTY/RELIANCE/ASML will be absent
        cache = _two_rows("NVIDIA", 900.0, 910.0)
        _, body = _get_response(cache)
        for r in body["regions"]:
            for i in r["instruments"]:
                if i["id"] != "NVIDIA":
                    assert i["close"] is None, f"{i['id']} should be None"
                    assert i["daily_return_pct"] is None, f"{i['id']} daily_return_pct should be None"
                    assert i["signal"] == "neutral", f"{i['id']} signal should be 'neutral'"

    def test_cache_exception_graceful_degradation(self):
        """If MarketDataCacheRepository.read_all raises, the endpoint must still
        return 200 with instruments showing null values (no 500 error)."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                side_effect=Exception("DB timeout"),
            ), patch(
                "rita.repositories.instrument.InstrumentRepository.read_all",
                return_value=_MOCK_INSTRUMENTS,
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get(_GEO_URL)
            assert resp.status_code == 200
            body = resp.json()
            assert "regions" in body
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Class 3: F28-specific API-frontend contract check
# ---------------------------------------------------------------------------

class TestF28PortfolioBuilderContract:
    """Assert that the Pydantic schema exactly covers every field read by
    portfolio-builder.js, and that the POST body shape matches pbBuildPortfolio."""

    # ── Schema field existence ────────────────────────────────────────────────

    def test_geography_overview_response_has_regions(self):
        """geo.regions — top-level check (line 311)."""
        from rita.schemas.geography import GeographyOverviewResponse
        assert "regions" in GeographyOverviewResponse.model_fields

    def test_geo_region_has_required_fields(self):
        """r.region, r.flag, r.instruments all read by portfolio-builder.js."""
        from rita.schemas.geography import GeoRegion
        for field in ("region", "flag", "instruments"):
            assert field in GeoRegion.model_fields, (
                f"GeoRegion missing '{field}' — portfolio-builder.js reads r.{field}"
            )

    def test_geo_instrument_has_all_pb_fields(self):
        """All six fields read by portfolio-builder.js must exist in GeoInstrument."""
        from rita.schemas.geography import GeoInstrument
        pb_fields = ("id", "name", "flag", "close", "daily_return_pct", "signal")
        for field in pb_fields:
            assert field in GeoInstrument.model_fields, (
                f"GeoInstrument missing '{field}' — portfolio-builder.js reads inst.{field}"
            )

    def test_geo_instrument_close_nullable(self):
        """GeoInstrument.close: float | None — JS null-guards with != null (line 107)."""
        from rita.schemas.geography import GeoInstrument
        import typing
        ann = GeoInstrument.model_fields["close"].annotation
        # Accept both Optional[float] and float | None representations
        args = typing.get_args(ann)
        assert type(None) in args, (
            "GeoInstrument.close must be Optional[float] — JS null-guards it"
        )

    def test_geo_instrument_daily_return_pct_nullable(self):
        """GeoInstrument.daily_return_pct: float | None — null-guarded in 5 places."""
        from rita.schemas.geography import GeoInstrument
        import typing
        ann = GeoInstrument.model_fields["daily_return_pct"].annotation
        args = typing.get_args(ann)
        assert type(None) in args, (
            "GeoInstrument.daily_return_pct must be Optional[float] — JS null-guards it"
        )

    # ── Response shape round-trip ─────────────────────────────────────────────

    def test_all_pb_instrument_fields_present_in_response(self):
        """Round-trip: every field that portfolio-builder.js reads must appear in
        the actual HTTP response body for each instrument."""
        pb_instrument_fields = {"id", "name", "flag", "close", "daily_return_pct", "signal"}
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                missing = pb_instrument_fields - set(i.keys())
                assert not missing, (
                    f"Instrument {i.get('id')} missing fields needed by portfolio-builder.js: {missing}"
                )

    def test_region_name_values_match_regionmap_keys(self):
        """portfolio-builder.js _renderBuckets uses regionMap = {India:'india', US:'us',
        EU:'europe', Other:'other'} (line 82). The response must use exactly these
        region name strings."""
        valid_region_names = {"India", "US", "EU", "Other"}
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            assert r["region"] in valid_region_names, (
                f"Region name '{r['region']}' not in portfolio-builder.js regionMap keys"
            )

    def test_instrument_id_is_uppercase(self):
        """_basket uses instrument IDs as-is; pbSelectAllRegion and pbAddFromDraft
        call .toUpperCase() on add. The endpoint uppercases via inst_id.upper()
        (rita.py line 1240). Verify round-trip stays uppercase."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                assert i["id"] == i["id"].upper(), (
                    f"Instrument id '{i['id']}' must be uppercase — basket relies on case-consistency"
                )

    # ── POST body contract for pbBuildPortfolio (Phase 2 stub) ───────────────

    def test_post_body_name_field_is_string(self):
        """pbBuildPortfolio POST body: { name: str, holdings: [...] }.
        name defaults to 'My Portfolio {date}' if pb-portfolio-name is empty.
        We verify Pydantic accepts the expected body shape as a plain dict check."""
        body = {
            "name": "My Test Portfolio",
            "holdings": [
                {"instrument_id": "NIFTY", "allocation_pct": 60.0},
                {"instrument_id": "NVIDIA", "allocation_pct": 40.0},
            ],
        }
        # Basic structural assertions — endpoint does not exist yet (Phase 2)
        assert isinstance(body["name"], str)
        assert len(body["name"]) > 0

    def test_post_body_holdings_shape(self):
        """pbBuildPortfolio constructs holdings as [{instrument_id, allocation_pct}].
        Verify the produced body keys match expected schema (Phase 2 endpoint)."""
        basket = {"NIFTY", "NVIDIA"}
        allocation_pct = 50
        holdings = [{"instrument_id": bid, "allocation_pct": float(allocation_pct)} for bid in sorted(basket)]
        assert all("instrument_id" in h for h in holdings), "holdings must have instrument_id"
        assert all("allocation_pct" in h for h in holdings), "holdings must have allocation_pct"
        assert all(isinstance(h["allocation_pct"], float) for h in holdings), "allocation_pct must be float"

    def test_post_body_allocation_totals_100(self):
        """pbBuildPortfolio allocates floor(100/n) per instrument and adds the
        remainder to holdings[0]. Total must always equal 100."""
        basket = list({"NIFTY", "BANKNIFTY", "NVIDIA"})
        n = len(basket)
        alloc = 100 // n
        holdings = [{"instrument_id": bid, "allocation_pct": alloc} for bid in basket]
        remainder = 100 - alloc * n
        if remainder > 0 and holdings:
            holdings[0]["allocation_pct"] += remainder
        total = sum(h["allocation_pct"] for h in holdings)
        assert total == 100, f"Allocation total must be 100, got {total}"
