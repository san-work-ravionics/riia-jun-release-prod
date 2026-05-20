"""Unit tests for GET /api/v1/experience/rita/geography-overview.

Strategy
--------
- FastAPI dependency_overrides replaces ``get_db`` with a mock session so no
  real DB is needed.
- ``MarketDataCacheRepository.read_all`` is patched via unittest.mock.patch to
  control what the cache returns without touching the filesystem.
- Three test classes cover: core endpoint behaviour, edge cases, and the
  API-frontend contract against loadGeoPanels() in market-signals.js.

ENDPOINT URL
------------
Router prefix="/api/v1", path="/experience/rita/geography-overview"
→ full URL: /api/v1/experience/rita/geography-overview

JS CONTRACT (from market-signals.js loadGeoPanels(), lines 208-237)
-------------------------------------------------------------------
Fields read from response:
  data.regions               — array, checked for existence + length
  r.flag                     — region flag (h4 template literal)
  r.region                   — region name (h4 template literal)
  r.instruments              — array, iterated
  i.name                     — table cell
  i.close                    — null-guarded: i.close != null ? i.close.toFixed(2) : '—'
  i.daily_return_pct         — null-guarded: i.daily_return_pct != null ? ... : '—'
  i.signal                   — badge class: badge-${i.signal}

NOTE: i.flag (instrument-level flag) is NOT read by the JS; it exists in the
Pydantic schema and endpoint but the frontend ignores it.  Contract check
below tests only the fields the JS actually consumes.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GEO_URL = "/api/v1/experience/rita/geography-overview"

VALID_SIGNALS = {"bullish", "bearish", "neutral"}

# Instruments defined in _GEO_REGIONS (endpoint constant) — used for
# cross-checking that all three regions are always present.
EXPECTED_REGIONS = {"US", "EU", "India"}


def _make_cache_record(
    underlying: str,
    close: float,
    record_date: date | None = None,
) -> MagicMock:
    """Return a minimal fake MarketDataCache ORM record."""
    rec = MagicMock()
    rec.underlying = underlying
    rec.close = close
    rec.date = record_date or date(2026, 1, 15)
    return rec


def _cache_with_two_rows(
    underlying: str,
    prev_close: float = 100.0,
    latest_close: float = 101.0,
) -> list:
    """Two sorted records so daily_return_pct can be computed."""
    return [
        _make_cache_record(underlying, prev_close, date(2026, 1, 14)),
        _make_cache_record(underlying, latest_close, date(2026, 1, 15)),
    ]


def _full_cache() -> list:
    """Cache with two rows for every instrument in _MOCK_INSTRUMENTS."""
    pairs = [
        # India
        ("NIFTY",     22000.0, 22150.0),
        ("BANKNIFTY", 48000.0, 47800.0),
        ("RELIANCE",   2900.0,  2920.0),
        # EU
        ("ASML",        700.0,   703.5),
        ("AEX",         880.0,   878.0),
        # US
        ("NVIDIA",      900.0,   910.0),
        ("DJI",       39000.0, 39200.0),
    ]
    records = []
    for und, prev, latest in pairs:
        records.extend(_cache_with_two_rows(und, prev, latest))
    return records


def _make_instrument(instrument_id: str, country_code: str, name: str = "") -> MagicMock:
    inst = MagicMock()
    inst.instrument_id = instrument_id
    inst.country_code = country_code
    inst.name = name or instrument_id
    inst.is_available = True
    return inst


# Covers all three regions using the actual seed instruments.
_MOCK_INSTRUMENTS = [
    _make_instrument("NIFTY",     "IN", "NIFTY 50"),
    _make_instrument("BANKNIFTY", "IN", "Bank Nifty"),
    _make_instrument("RELIANCE",  "IN", "Reliance Industries"),
    _make_instrument("ASML",      "NL", "ASML Holding"),
    _make_instrument("AEX",       "NL", "AEX Index"),
    _make_instrument("NVIDIA",    "US", "NVIDIA"),
    _make_instrument("DJI",       "US", "Dow Jones"),
]


def _override(app, dep, mock_value):
    app.dependency_overrides[dep] = lambda: mock_value


def _clear(app, *deps):
    for dep in deps:
        app.dependency_overrides.pop(dep, None)


def _get_response(patch_return_value: list) -> tuple:
    """Shared helper: boot TestClient, hit the endpoint, return (resp, body)."""
    from rita.main import app
    from rita.database import get_db

    mock_db = MagicMock()
    _override(app, get_db, mock_db)
    try:
        with patch(
            "rita.repositories.market_data.MarketDataCacheRepository.read_all",
            return_value=patch_return_value,
        ), patch(
            "rita.repositories.instrument.InstrumentRepository.read_all",
            return_value=_MOCK_INSTRUMENTS,
        ):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(_GEO_URL)
        return resp, resp.json()
    finally:
        _clear(app, get_db)


# ---------------------------------------------------------------------------
# Class 1: Core endpoint behaviour
# ---------------------------------------------------------------------------

class TestGeographyOverviewEndpoint:
    """Happy-path tests with a fully populated cache."""

    def test_returns_200(self):
        resp, _ = _get_response(_full_cache())
        assert resp.status_code == 200

    def test_returns_three_regions(self):
        """Response must contain exactly 3 regions: US, EU, India."""
        _, body = _get_response(_full_cache())
        regions = body["regions"]
        assert len(regions) == 3, f"Expected 3 regions, got {len(regions)}: {[r['region'] for r in regions]}"

    def test_region_names_are_us_eu_india(self):
        """The three region names must be US, EU, India (exact strings)."""
        _, body = _get_response(_full_cache())
        names = {r["region"] for r in body["regions"]}
        assert names == EXPECTED_REGIONS, f"Region names mismatch: {names}"

    def test_instruments_per_region(self):
        """Each region must have at least 1 instrument in the response."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            assert len(r["instruments"]) >= 1, (
                f"Region '{r['region']}' has no instruments"
            )

    def test_instrument_fields_present(self):
        """Every instrument object must contain id, name, close, daily_return_pct, signal."""
        required = {"id", "name", "close", "daily_return_pct", "signal"}
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                missing = required - set(i.keys())
                assert not missing, (
                    f"Instrument {i.get('id')} in region {r['region']} "
                    f"missing fields: {missing}"
                )

    def test_valid_signal_values(self):
        """All signal values must be one of 'bullish', 'bearish', 'neutral'."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                assert i["signal"] in VALID_SIGNALS, (
                    f"Instrument {i['id']} has invalid signal '{i['signal']}'"
                )

    def test_close_is_numeric_when_cache_has_data(self):
        """close must be a float (not None) for instruments present in cache."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                assert isinstance(i["close"], float), (
                    f"Instrument {i['id']} close should be float, got {type(i['close'])}"
                )

    def test_daily_return_pct_is_numeric_when_two_rows_available(self):
        """daily_return_pct must be a float when at least 2 rows exist in cache."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                assert isinstance(i["daily_return_pct"], float), (
                    f"Instrument {i['id']} daily_return_pct should be float, "
                    f"got {type(i['daily_return_pct'])}"
                )


# ---------------------------------------------------------------------------
# Class 2: Edge cases
# ---------------------------------------------------------------------------

class TestGeographyOverviewEdgeCases:
    """Edge cases: missing instruments, null values, empty cache."""

    def test_instrument_not_in_cache_returns_neutral(self):
        """When an instrument has no cache rows its signal must be 'neutral'
        and close / daily_return_pct must be None."""
        # Provide data for only AAPL; all other instruments are absent
        single_instrument_cache = _cache_with_two_rows("AAPL", 150.0, 151.5)
        _, body = _get_response(single_instrument_cache)

        for r in body["regions"]:
            for i in r["instruments"]:
                if i["id"] != "AAPL":
                    assert i["signal"] == "neutral", (
                        f"Instrument {i['id']} not in cache should have signal='neutral', "
                        f"got '{i['signal']}'"
                    )
                    assert i["close"] is None, (
                        f"Instrument {i['id']} not in cache should have close=None"
                    )
                    assert i["daily_return_pct"] is None, (
                        f"Instrument {i['id']} not in cache should have daily_return_pct=None"
                    )

    def test_daily_return_null_handled(self):
        """Instrument with daily_return_pct=None (only one cache row) must not
        crash the endpoint and must return signal='neutral'."""
        # One row → can't compute daily return
        single_row = [_make_cache_record("NIFTY", 22000.0, date(2026, 1, 15))]
        resp, body = _get_response(single_row)

        assert resp.status_code == 200
        # Find NIFTY in response
        nifty_inst = None
        for r in body["regions"]:
            for i in r["instruments"]:
                if i["id"] == "NIFTY":
                    nifty_inst = i
                    break

        assert nifty_inst is not None, "NIFTY should always appear in India region"
        assert nifty_inst["daily_return_pct"] is None, (
            "Single-row NIFTY should have daily_return_pct=None"
        )
        assert nifty_inst["signal"] == "neutral", (
            "Null daily_return_pct should produce signal='neutral'"
        )

    def test_all_regions_present_when_cache_empty(self):
        """All 3 regions must still be returned even when cache is entirely empty.
        Every instrument should show with null values."""
        resp, body = _get_response([])

        assert resp.status_code == 200
        region_names = {r["region"] for r in body["regions"]}
        assert region_names == EXPECTED_REGIONS, (
            f"Expected all 3 regions with empty cache, got: {region_names}"
        )

        # All instruments must be present with null close + neutral signal
        for r in body["regions"]:
            assert len(r["instruments"]) >= 1
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

    def test_positive_return_produces_bullish_signal(self):
        """daily_return_pct > 0.5 must produce signal='bullish'."""
        # prev=100, latest=105 → return = +5% → bullish
        cache = _cache_with_two_rows("NIFTY", 100.0, 105.0)
        _, body = _get_response(cache)

        nifty_inst = None
        for r in body["regions"]:
            for i in r["instruments"]:
                if i["id"] == "NIFTY":
                    nifty_inst = i
                    break

        assert nifty_inst is not None
        assert nifty_inst["signal"] == "bullish", (
            f"Expected 'bullish' for +5% return, got '{nifty_inst['signal']}'"
        )

    def test_negative_return_produces_bearish_signal(self):
        """daily_return_pct < -0.5 must produce signal='bearish'."""
        # prev=100, latest=95 → return = -5% → bearish
        cache = _cache_with_two_rows("NIFTY", 100.0, 95.0)
        _, body = _get_response(cache)

        nifty_inst = None
        for r in body["regions"]:
            for i in r["instruments"]:
                if i["id"] == "NIFTY":
                    nifty_inst = i
                    break

        assert nifty_inst is not None
        assert nifty_inst["signal"] == "bearish", (
            f"Expected 'bearish' for -5% return, got '{nifty_inst['signal']}'"
        )

    def test_small_return_within_threshold_produces_neutral(self):
        """daily_return_pct between -0.5 and +0.5 must produce signal='neutral'."""
        # prev=100, latest=100.3 → return = +0.3% → neutral
        cache = _cache_with_two_rows("NIFTY", 100.0, 100.3)
        _, body = _get_response(cache)

        nifty_inst = None
        for r in body["regions"]:
            for i in r["instruments"]:
                if i["id"] == "NIFTY":
                    nifty_inst = i
                    break

        assert nifty_inst is not None
        assert nifty_inst["signal"] == "neutral", (
            f"Expected 'neutral' for +0.3% return, got '{nifty_inst['signal']}'"
        )

    def test_no_crash_when_cache_raises_exception(self):
        """If MarketDataCacheRepository.read_all raises, the endpoint must
        return 200 with all regions present and instruments showing null values
        (graceful degradation)."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                side_effect=Exception("DB unavailable"),
            ), patch(
                "rita.repositories.instrument.InstrumentRepository.read_all",
                return_value=_MOCK_INSTRUMENTS,
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get(_GEO_URL)
            assert resp.status_code == 200
            body = resp.json()
            region_names = {r["region"] for r in body["regions"]}
            assert region_names == EXPECTED_REGIONS
        finally:
            _clear(app, get_db)


# ---------------------------------------------------------------------------
# Class 3: API-frontend contract check
# ---------------------------------------------------------------------------

class TestGeographyContractCheck:
    """Verify that the Pydantic schema fields match what loadGeoPanels() in
    market-signals.js reads from the API response.

    JS reads (market-signals.js, lines 208-237):
        data.regions                 → array guard + iteration
        r.flag                       → h4 template literal (region flag)
        r.region                     → h4 template literal (region name)
        r.instruments                → inner iteration
        i.name                       → table <td>
        i.close                      → null-guarded float display
        i.daily_return_pct           → null-guarded float display
        i.signal                     → CSS badge class

    NOTE: i.flag (instrument-level) exists in the schema but is NOT read by the JS.
    The contract test below checks only the fields the JS actually consumes.
    """

    def test_schema_fields_match_js_contract(self):
        """Assert all Pydantic model fields required by loadGeoPanels() are present."""
        from rita.schemas.geography import GeographyOverviewResponse, GeoRegion, GeoInstrument

        # GeographyOverviewResponse must have 'regions'
        response_fields = GeographyOverviewResponse.model_fields
        assert "regions" in response_fields, (
            "JS reads data.regions — 'regions' missing from GeographyOverviewResponse"
        )

        # GeoRegion must have: region, flag, instruments
        region_fields = GeoRegion.model_fields
        for field in ("region", "flag", "instruments"):
            assert field in region_fields, (
                f"JS reads r.{field} — '{field}' missing from GeoRegion"
            )

        # GeoInstrument must have: id, name, close, daily_return_pct, signal
        # (i.flag is in schema but JS does not use it — still valid to have it)
        instrument_fields = GeoInstrument.model_fields
        for field in ("id", "name", "close", "daily_return_pct", "signal"):
            assert field in instrument_fields, (
                f"JS reads i.{field} — '{field}' missing from GeoInstrument"
            )

    def test_response_regions_is_list(self):
        """data.regions must be a JSON array (JS calls .map on it)."""
        _, body = _get_response(_full_cache())
        assert isinstance(body["regions"], list), (
            "JS calls data.regions.map() — must be an array"
        )

    def test_region_has_flag_field(self):
        """r.flag is used in JS h4 template — must be present on every region."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            assert "flag" in r, f"Region {r.get('region')} missing 'flag' field"
            assert isinstance(r["flag"], str)

    def test_region_has_region_field(self):
        """r.region is used in JS h4 template — must be present on every region."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            assert "region" in r, f"Region object missing 'region' field: {r}"
            assert isinstance(r["region"], str)

    def test_region_has_instruments_array(self):
        """r.instruments is iterated in JS — must be a list on every region."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            assert "instruments" in r, f"Region {r['region']} missing 'instruments'"
            assert isinstance(r["instruments"], list)

    def test_instrument_name_is_string(self):
        """i.name is inserted into a table cell — must be a non-empty string."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                assert isinstance(i["name"], str) and len(i["name"]) > 0, (
                    f"Instrument {i['id']} name must be a non-empty string"
                )

    def test_instrument_close_is_null_or_float(self):
        """i.close is null-guarded in JS (i.close != null ? i.close.toFixed(2) : '—')
        — must be either null or a float, never an unexpected type."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                assert i["close"] is None or isinstance(i["close"], float), (
                    f"Instrument {i['id']} close must be float or null, "
                    f"got {type(i['close'])}"
                )

    def test_instrument_daily_return_pct_is_null_or_float(self):
        """i.daily_return_pct is null-guarded in JS — must be null or float."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                assert i["daily_return_pct"] is None or isinstance(i["daily_return_pct"], float), (
                    f"Instrument {i['id']} daily_return_pct must be float or null, "
                    f"got {type(i['daily_return_pct'])}"
                )

    def test_instrument_signal_is_valid_css_class_token(self):
        """i.signal is used as badge-${i.signal} CSS class — must be
        one of the three valid tokens JS handles."""
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                assert i["signal"] in VALID_SIGNALS, (
                    f"Instrument {i['id']} signal '{i['signal']}' would produce an "
                    f"unhandled CSS class badge-{i['signal']}"
                )

    def test_js_does_not_use_instrument_flag_noted_in_schema(self):
        """i.flag exists in schema (GeoInstrument) but loadGeoPanels() does NOT
        read it from the response.  This test documents the discrepancy so a
        future refactor can decide whether to expose or remove i.flag.
        The field is present in the response but harmless."""
        from rita.schemas.geography import GeoInstrument
        # i.flag IS in schema
        assert "flag" in GeoInstrument.model_fields, (
            "GeoInstrument.flag field unexpectedly removed from schema"
        )
        # JS contract test: verify response still works without JS consuming it
        _, body = _get_response(_full_cache())
        for r in body["regions"]:
            for i in r["instruments"]:
                # flag will be present in response (same value as r.flag)
                assert "flag" in i, "i.flag missing from response"
