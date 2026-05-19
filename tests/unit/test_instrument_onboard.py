"""Unit tests for GET /api/v1/instrument/search and POST /api/v1/instrument/onboard.

Coverage
--------
Search endpoint:
  1. Happy path — returns a list of result dicts with all required fields
  2. Empty results — yfinance returns nothing; handler returns []
  3. Short query (< 2 chars) — raises HTTP 400

Onboard endpoint:
  4. Happy path — returns status "ok" with rows_fetched, rows_seeded, raw_path, input_path
  5. Duplicate instrument — raises HTTP 409
  6. yfinance unreachable — service raises HTTP 502
  7. Bad ticker (< 100 rows) — raises HTTP 400
  8. Missing required fields — raises HTTP 422

Contract verification:
  9. Search response fields — ticker, name, exchange, currency, country, quote_type
  10. Onboard response fields — status, ticker, rows_fetched, rows_seeded, raw_path, input_path

Strategy
--------
- The handler module (rita.api.v1.workflow.instrument_onboard) is injected into
  sys.modules using a stub service module so that import-time deps on yfinance and
  load_ohlcv_csv are never resolved.  All four service functions are replaced with
  MagicMock instances and overridden per-test via patch().
- A minimal FastAPI test app is created with only the instrument_onboard router so
  tests are isolated from the full app startup.
- InstrumentRepository is patched per-test to control duplicate-check outcomes.
- The DB session dependency is overridden with a MagicMock — no real DB needed.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Stub the service module before importing the handler so that import-time
# errors (load_ohlcv_csv not in data_loader, yfinance not installed) are
# avoided.  The stubs are overridden per-test via patch().
# ---------------------------------------------------------------------------

def _inject_service_stub() -> None:
    """Insert a stub rita.services.instrument_onboard into sys.modules."""
    if "rita.services.instrument_onboard" in sys.modules:
        return
    stub = types.ModuleType("rita.services.instrument_onboard")
    stub.search_tickers = MagicMock(return_value=[])
    stub.fetch_raw_data = MagicMock(return_value=(Path("/data/raw/AAPL/aapl_daily.csv"), 3800))
    stub.process_to_input = MagicMock(return_value=Path("/data/input/AAPL/aapl_daily.csv"))
    stub.seed_market_cache = MagicMock(return_value=0)
    sys.modules["rita.services.instrument_onboard"] = stub


_inject_service_stub()

# Now it is safe to import the handler module.
from rita.api.v1.workflow.instrument_onboard import router as _instrument_router  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_SEARCH_RESULT_FULL = [
    {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "exchange": "NMS",
        "currency": "USD",
        "country": "United States",
        "quote_type": "EQUITY",
    }
]

_ONBOARD_BODY = {
    "ticker": "AAPL",
    "name": "Apple Inc.",
    "exchange": "NMS",
    "currency": "USD",
    "country_code": "US",
    "lot_size": None,
}


def _make_client() -> tuple[TestClient, MagicMock]:
    """Create an isolated FastAPI TestClient with only the instrument_onboard router."""
    from rita.database import get_db

    mock_db = MagicMock()
    test_app = FastAPI()
    test_app.include_router(_instrument_router)
    test_app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(test_app, raise_server_exceptions=False), mock_db


# ---------------------------------------------------------------------------
# Search: happy path
# ---------------------------------------------------------------------------

class TestInstrumentSearchHappyPath:
    """GET /api/v1/instrument/search returns a non-empty list on a valid query."""

    def test_returns_list_of_results(self):
        with patch(
            "rita.api.v1.workflow.instrument_onboard.search_tickers",
            return_value=_SEARCH_RESULT_FULL,
        ):
            client, _ = _make_client()
            resp = client.get("/api/v1/instrument/search", params={"q": "apple"})

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["ticker"] == "AAPL"

    def test_response_contains_all_required_fields(self):
        """Contract check: JS reads ticker, name, exchange, currency, country, quote_type."""
        with patch(
            "rita.api.v1.workflow.instrument_onboard.search_tickers",
            return_value=_SEARCH_RESULT_FULL,
        ):
            client, _ = _make_client()
            resp = client.get("/api/v1/instrument/search", params={"q": "apple"})

        assert resp.status_code == 200
        item = resp.json()[0]
        required_fields = {"ticker", "name", "exchange", "currency", "country", "quote_type"}
        assert required_fields.issubset(item.keys()), (
            f"Missing fields: {required_fields - item.keys()}"
        )

    def test_field_values_are_strings(self):
        """All six contract fields must be strings (not None) for the JS to render them."""
        with patch(
            "rita.api.v1.workflow.instrument_onboard.search_tickers",
            return_value=_SEARCH_RESULT_FULL,
        ):
            client, _ = _make_client()
            resp = client.get("/api/v1/instrument/search", params={"q": "apple"})

        item = resp.json()[0]
        for field in ("ticker", "name", "exchange", "currency", "country", "quote_type"):
            assert isinstance(item[field], str), f"Field '{field}' is not a string: {item[field]!r}"


# ---------------------------------------------------------------------------
# Search: empty results
# ---------------------------------------------------------------------------

class TestInstrumentSearchEmptyResults:
    """GET /api/v1/instrument/search returns [] when yfinance has no matches."""

    def test_empty_result_returns_200_with_empty_list(self):
        with patch(
            "rita.api.v1.workflow.instrument_onboard.search_tickers",
            return_value=[],
        ):
            client, _ = _make_client()
            resp = client.get("/api/v1/instrument/search", params={"q": "zzzzz"})

        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Search: short query guard
# ---------------------------------------------------------------------------

class TestInstrumentSearchShortQuery:
    """GET /api/v1/instrument/search rejects queries shorter than 2 characters."""

    @pytest.mark.parametrize("q", ["", "a", " "])
    def test_short_query_returns_400(self, q):
        with patch(
            "rita.api.v1.workflow.instrument_onboard.search_tickers",
            return_value=[],
        ):
            client, _ = _make_client()
            resp = client.get("/api/v1/instrument/search", params={"q": q})

        assert resp.status_code == 400

    def test_short_query_error_detail_is_descriptive(self):
        with patch(
            "rita.api.v1.workflow.instrument_onboard.search_tickers",
            return_value=[],
        ):
            client, _ = _make_client()
            resp = client.get("/api/v1/instrument/search", params={"q": "x"})

        detail = resp.json().get("detail", "")
        assert "2" in detail or "characters" in detail.lower() or "q" in detail.lower()


# ---------------------------------------------------------------------------
# Onboard: happy path
# ---------------------------------------------------------------------------

class TestInstrumentOnboardHappyPath:
    """POST /api/v1/instrument/onboard returns status "ok" on a valid ticker."""

    def test_returns_200_with_status_ok(self):
        with (
            patch("rita.api.v1.workflow.instrument_onboard.InstrumentRepository") as mock_repo_cls,
            patch(
                "rita.api.v1.workflow.instrument_onboard.fetch_raw_data",
                return_value=(Path("/data/raw/AAPL/aapl_daily.csv"), 3800),
            ),
            patch(
                "rita.api.v1.workflow.instrument_onboard.process_to_input",
                return_value=Path("/data/input/AAPL/aapl_daily.csv"),
            ),
            patch(
                "rita.api.v1.workflow.instrument_onboard.seed_market_cache",
                return_value=120,
            ),
        ):
            mock_repo = MagicMock()
            mock_repo.find_by_id.return_value = None  # no duplicate
            mock_repo_cls.return_value = mock_repo

            client, _ = _make_client()
            resp = client.post("/api/v1/instrument/onboard", json=_ONBOARD_BODY)

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_response_contains_all_contract_fields(self):
        """Contract check: JS reads status, ticker, rows_fetched, rows_seeded, raw_path, input_path."""
        with (
            patch("rita.api.v1.workflow.instrument_onboard.InstrumentRepository") as mock_repo_cls,
            patch(
                "rita.api.v1.workflow.instrument_onboard.fetch_raw_data",
                return_value=(Path("/data/raw/AAPL/aapl_daily.csv"), 3800),
            ),
            patch(
                "rita.api.v1.workflow.instrument_onboard.process_to_input",
                return_value=Path("/data/input/AAPL/aapl_daily.csv"),
            ),
            patch(
                "rita.api.v1.workflow.instrument_onboard.seed_market_cache",
                return_value=120,
            ),
        ):
            mock_repo = MagicMock()
            mock_repo.find_by_id.return_value = None
            mock_repo_cls.return_value = mock_repo

            client, _ = _make_client()
            resp = client.post("/api/v1/instrument/onboard", json=_ONBOARD_BODY)

        data = resp.json()
        required_fields = {"status", "ticker", "rows_fetched", "rows_seeded", "raw_path", "input_path"}
        assert required_fields.issubset(data.keys()), (
            f"Missing fields: {required_fields - data.keys()}"
        )

    def test_ticker_is_uppercased_in_response(self):
        """Handler must uppercase the ticker before returning it."""
        body = {**_ONBOARD_BODY, "ticker": "aapl"}  # lowercase input

        with (
            patch("rita.api.v1.workflow.instrument_onboard.InstrumentRepository") as mock_repo_cls,
            patch(
                "rita.api.v1.workflow.instrument_onboard.fetch_raw_data",
                return_value=(Path("/data/raw/AAPL/aapl_daily.csv"), 3800),
            ),
            patch(
                "rita.api.v1.workflow.instrument_onboard.process_to_input",
                return_value=Path("/data/input/AAPL/aapl_daily.csv"),
            ),
            patch(
                "rita.api.v1.workflow.instrument_onboard.seed_market_cache",
                return_value=120,
            ),
        ):
            mock_repo = MagicMock()
            mock_repo.find_by_id.return_value = None
            mock_repo_cls.return_value = mock_repo

            client, _ = _make_client()
            resp = client.post("/api/v1/instrument/onboard", json=body)

        assert resp.json()["ticker"] == "AAPL"

    def test_rows_fetched_and_seeded_match_service_output(self):
        with (
            patch("rita.api.v1.workflow.instrument_onboard.InstrumentRepository") as mock_repo_cls,
            patch(
                "rita.api.v1.workflow.instrument_onboard.fetch_raw_data",
                return_value=(Path("/data/raw/AAPL/aapl_daily.csv"), 3800),
            ),
            patch(
                "rita.api.v1.workflow.instrument_onboard.process_to_input",
                return_value=Path("/data/input/AAPL/aapl_daily.csv"),
            ),
            patch(
                "rita.api.v1.workflow.instrument_onboard.seed_market_cache",
                return_value=120,
            ),
        ):
            mock_repo = MagicMock()
            mock_repo.find_by_id.return_value = None
            mock_repo_cls.return_value = mock_repo

            client, _ = _make_client()
            resp = client.post("/api/v1/instrument/onboard", json=_ONBOARD_BODY)

        data = resp.json()
        assert data["rows_fetched"] == 3800
        assert data["rows_seeded"] == 120


# ---------------------------------------------------------------------------
# Onboard: duplicate instrument — 409
# ---------------------------------------------------------------------------

class TestInstrumentOnboardDuplicate:
    """POST /api/v1/instrument/onboard returns 409 when ticker already exists."""

    def test_duplicate_ticker_returns_409(self):
        with patch("rita.api.v1.workflow.instrument_onboard.InstrumentRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.find_by_id.return_value = MagicMock()  # record exists
            mock_repo_cls.return_value = mock_repo

            client, _ = _make_client()
            resp = client.post("/api/v1/instrument/onboard", json=_ONBOARD_BODY)

        assert resp.status_code == 409

    def test_duplicate_error_detail_mentions_ticker(self):
        with patch("rita.api.v1.workflow.instrument_onboard.InstrumentRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.find_by_id.return_value = MagicMock()
            mock_repo_cls.return_value = mock_repo

            client, _ = _make_client()
            resp = client.post("/api/v1/instrument/onboard", json=_ONBOARD_BODY)

        detail = resp.json().get("detail", "")
        assert "AAPL" in detail or "already" in detail.lower() or "exists" in detail.lower()


# ---------------------------------------------------------------------------
# Onboard: yfinance unreachable — 502
# ---------------------------------------------------------------------------

class TestInstrumentOnboardYfinanceFailure:
    """POST /api/v1/instrument/onboard returns 502 when yfinance is unreachable."""

    def test_yfinance_unreachable_returns_502(self):
        from fastapi import HTTPException as _HTTPException

        with (
            patch("rita.api.v1.workflow.instrument_onboard.InstrumentRepository") as mock_repo_cls,
            patch(
                "rita.api.v1.workflow.instrument_onboard.fetch_raw_data",
                side_effect=_HTTPException(
                    status_code=502,
                    detail="Yahoo Finance is currently unreachable.",
                ),
            ),
        ):
            mock_repo = MagicMock()
            mock_repo.find_by_id.return_value = None
            mock_repo_cls.return_value = mock_repo

            client, _ = _make_client()
            resp = client.post("/api/v1/instrument/onboard", json=_ONBOARD_BODY)

        assert resp.status_code == 502

    def test_yfinance_unreachable_detail_is_descriptive(self):
        from fastapi import HTTPException as _HTTPException

        with (
            patch("rita.api.v1.workflow.instrument_onboard.InstrumentRepository") as mock_repo_cls,
            patch(
                "rita.api.v1.workflow.instrument_onboard.fetch_raw_data",
                side_effect=_HTTPException(
                    status_code=502,
                    detail="Yahoo Finance is currently unreachable.",
                ),
            ),
        ):
            mock_repo = MagicMock()
            mock_repo.find_by_id.return_value = None
            mock_repo_cls.return_value = mock_repo

            client, _ = _make_client()
            resp = client.post("/api/v1/instrument/onboard", json=_ONBOARD_BODY)

        detail = resp.json().get("detail", "")
        assert "yahoo" in detail.lower() or "unreachable" in detail.lower()


# ---------------------------------------------------------------------------
# Onboard: bad ticker (< 100 rows from yfinance) — 400
# ---------------------------------------------------------------------------

class TestInstrumentOnboardBadTicker:
    """POST /api/v1/instrument/onboard returns 400 when ticker yields < 100 rows."""

    def test_bad_ticker_returns_400(self):
        with (
            patch("rita.api.v1.workflow.instrument_onboard.InstrumentRepository") as mock_repo_cls,
            patch(
                "rita.api.v1.workflow.instrument_onboard.fetch_raw_data",
                side_effect=ValueError("Ticker 'FAKE' returned fewer than 100 rows."),
            ),
        ):
            mock_repo = MagicMock()
            mock_repo.find_by_id.return_value = None
            mock_repo_cls.return_value = mock_repo

            client, _ = _make_client()
            resp = client.post("/api/v1/instrument/onboard", json={**_ONBOARD_BODY, "ticker": "FAKE"})

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Onboard: missing required fields — 422
# ---------------------------------------------------------------------------

class TestInstrumentOnboardMissingFields:
    """POST /api/v1/instrument/onboard returns 422 on missing required body fields."""

    def test_missing_ticker_returns_422(self):
        body = {k: v for k, v in _ONBOARD_BODY.items() if k != "ticker"}
        client, _ = _make_client()
        resp = client.post("/api/v1/instrument/onboard", json=body)
        assert resp.status_code == 422

    def test_missing_country_code_returns_422(self):
        body = {k: v for k, v in _ONBOARD_BODY.items() if k != "country_code"}
        client, _ = _make_client()
        resp = client.post("/api/v1/instrument/onboard", json=body)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Gap 1 — ETF filtering in search_tickers() service function
# ---------------------------------------------------------------------------

class TestSearchTickersFiltersNonEquity:
    """search_tickers() service function must return only EQUITY entries."""

    def test_search_tickers_filters_non_equity(self):
        """A mixed yfinance result (EQUITY + ETF) must yield only the EQUITY entry."""
        import importlib

        # Import the real service module bypassing the sys.modules stub so we
        # exercise the actual filter logic.
        import importlib.util, os

        service_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "src", "rita", "services", "instrument_onboard.py",
        )
        spec = importlib.util.spec_from_file_location(
            "_real_instrument_onboard_service", service_path
        )
        real_service = importlib.util.module_from_spec(spec)

        # The service does `import yfinance as yf` inside the function body, so
        # we patch yfinance.Search before the spec is executed.
        mock_search_instance = MagicMock()
        mock_search_instance.quotes = [
            {
                "symbol": "AAPL",
                "longname": "Apple Inc.",
                "exchange": "NMS",
                "currency": "USD",
                "country": "United States",
                "quoteType": "EQUITY",
            },
            {
                "symbol": "SPY",
                "longname": "SPDR S&P 500 ETF Trust",
                "exchange": "PCX",
                "currency": "USD",
                "country": "United States",
                "quoteType": "ETF",
            },
        ]
        mock_yf = MagicMock()
        mock_yf.Search.return_value = mock_search_instance

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            spec.loader.exec_module(real_service)
            results = real_service.search_tickers("apple")

        assert len(results) == 1, f"Expected 1 result (EQUITY only), got {len(results)}: {results}"
        assert results[0]["ticker"] == "AAPL"
        assert results[0]["quote_type"] == "EQUITY"


# ---------------------------------------------------------------------------
# Gap 2 — Search endpoint returns 502 when yfinance is unreachable
# ---------------------------------------------------------------------------

class TestSearchEndpoint502OnYfinanceFailure:
    """GET /api/v1/instrument/search returns 502 when the underlying yfinance call fails."""

    def test_search_endpoint_returns_502_on_yfinance_failure(self):
        from fastapi import HTTPException as _HTTPException

        with patch(
            "rita.api.v1.workflow.instrument_onboard.search_tickers",
            side_effect=_HTTPException(
                status_code=502,
                detail="Yahoo Finance is currently unreachable.",
            ),
        ):
            client, _ = _make_client()
            resp = client.get("/api/v1/instrument/search", params={"q": "test"})

        assert resp.status_code == 502
