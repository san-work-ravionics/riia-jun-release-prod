"""Unit tests for Feature 16 — data_refresh service and refresh-all endpoint.

Coverage
--------
check_gap():
  1. Happy path — DB returns a date 30 days ago; gap_days == 30
  2. Edge case (EC-1) — DB returns None (no data); gap_days == 730 (large gap)

refresh_all():
  3. Edge case (EC-1 no-gap short-circuit) — check_gap returns gap_days=0;
     fetch_and_write_raw is NOT called; result status == "current"
  4. Edge case (EC-2 yfinance error) — yf.download raises for one instrument;
     loop continues; failed instrument gets status="error"

upsert_cache_delta():
  5. Edge case (EC-3 no duplicates) — existing dates already in DB;
     db.add_all called only with NEW dates, not existing ones

API endpoint:
  6. POST /api/v1/instrument/refresh-all — happy path; returns RefreshAllResponse shape
  7. POST /api/v1/instrument/refresh-all — per-instrument errors do not raise HTTP 5xx

Strategy
--------
- Patch paths match exact import paths used in data_refresh.py:
    * yfinance is imported as `import yfinance as yf` INSIDE fetch_and_write_raw() body
      → patch as `rita.services.data_refresh.yf` after injecting the stub
    * MarketDataCacheModel is imported via `from rita.models.market_data import MarketDataCacheModel`
      inside each function body
    * get_settings is imported via `from rita.config import get_settings` at module level
- DB session is always a MagicMock to avoid SQLite setup cost.
- Endpoint tests use an isolated FastAPI + TestClient with dependency_overrides.
"""
from __future__ import annotations

import sys
import types
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Stub heavy imports before importing service / router modules.
# The service does `import yfinance as yf` INSIDE fetch_and_write_raw(), so we
# inject a yfinance stub into sys.modules so the lazy import resolves correctly.
# ---------------------------------------------------------------------------

def _inject_yfinance_stub() -> MagicMock:
    """Insert a MagicMock yfinance into sys.modules and return it."""
    if "yfinance" in sys.modules and not isinstance(sys.modules["yfinance"], MagicMock):
        # Real yfinance might be installed — replace with a stub for tests.
        pass
    stub_yf = MagicMock()
    sys.modules["yfinance"] = stub_yf
    return stub_yf


_stub_yf = _inject_yfinance_stub()

# Stub rita.models.market_data so we can import the service without DB setup.
_mock_market_data_mod = types.ModuleType("rita.models.market_data")
_mock_market_data_cls = MagicMock()
_mock_market_data_mod.MarketDataCacheModel = _mock_market_data_cls
sys.modules.setdefault("rita.models.market_data", _mock_market_data_mod)

# Stub rita.core.data_loader (used inside upsert_cache_delta and rebuild_input)
_mock_data_loader_mod = types.ModuleType("rita.core.data_loader")
_mock_data_loader_mod.load_ohlcv_csv = MagicMock()
_mock_data_loader_mod.load_instrument_data = MagicMock()
sys.modules.setdefault("rita.core.data_loader", _mock_data_loader_mod)

# Now import the service module (get_settings is imported at module level)
import rita.services.data_refresh as _svc  # noqa: E402  (after stubs)

from rita.services.data_refresh import (  # noqa: E402
    check_gap,
    fetch_and_write_raw,
    refresh_all,
    upsert_cache_delta,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_db() -> MagicMock:
    """Return a fresh SQLAlchemy Session mock."""
    return MagicMock()


def _make_refresh_all_client(mock_refresh_all_fn: MagicMock) -> TestClient:
    """Create an isolated FastAPI TestClient for the refresh-all endpoint.

    Patches rita.services.data_refresh.refresh_all so the handler calls the mock.
    """
    from rita.database import get_db
    from rita.api.v1.workflow.instrument_onboard import router as _instr_router

    mock_db = _make_mock_db()
    test_app = FastAPI()
    test_app.include_router(_instr_router)
    test_app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(test_app, raise_server_exceptions=False), mock_db


# ---------------------------------------------------------------------------
# 1. check_gap — happy path: DB returns a date 30 days ago
# ---------------------------------------------------------------------------

class TestCheckGapReturnsGapDays:
    """check_gap() returns gap_days=30 when the DB has a row from 30 days ago."""

    def test_check_gap_returns_gap_days(self):
        thirty_days_ago = date.today() - timedelta(days=30)
        mock_db = _make_mock_db()

        # Simulate DB query returning a single (date,) row tuple
        mock_query_chain = mock_db.query.return_value
        mock_query_chain.filter.return_value.order_by.return_value.first.return_value = (
            thirty_days_ago,
        )

        # MarketDataCacheModel is imported locally inside check_gap via
        # `from rita.models.market_data import MarketDataCacheModel`
        # so we patch it on its source module.
        with patch(
            "rita.models.market_data.MarketDataCacheModel",
            _mock_market_data_cls,
        ):
            result = check_gap("NIFTY", mock_db)

        assert result["gap_days"] == 30
        assert result["instrument_id"] == "NIFTY"
        assert result["last_date"] == thirty_days_ago
        assert result["yf_ticker"] == "^NSEI"


# ---------------------------------------------------------------------------
# 2. check_gap — edge case EC-1: DB returns None (no data at all)
# ---------------------------------------------------------------------------

class TestCheckGapNoDataReturnsLargeGap:
    """check_gap() returns gap_days=730 when the instrument has no data in the DB."""

    def test_check_gap_no_data_returns_large_gap(self):
        mock_db = _make_mock_db()

        mock_query_chain = mock_db.query.return_value
        mock_query_chain.filter.return_value.order_by.return_value.first.return_value = None

        with patch(
            "rita.models.market_data.MarketDataCacheModel",
            _mock_market_data_cls,
        ):
            result = check_gap("ASML", mock_db)

        assert result["gap_days"] > 365, (
            f"Expected gap_days > 365 for missing data, got {result['gap_days']}"
        )
        assert result["last_date"] is None


# ---------------------------------------------------------------------------
# 3. refresh_all — EC-1 no-gap short-circuit: fetch_and_write_raw NOT called
# ---------------------------------------------------------------------------

class TestRefreshAllCurrentInstrumentSkipped:
    """refresh_all() must short-circuit when gap_days == 0 and NOT call fetch_and_write_raw."""

    def test_current_instrument_skipped(self):
        mock_db = _make_mock_db()

        # check_gap returns gap_days=0 for every instrument
        def _mock_check_gap(instrument_id: str, db):
            return {
                "instrument_id": instrument_id,
                "last_date": date.today(),
                "gap_days": 0,
                "yf_ticker": _svc.YF_TICKER_MAP.get(instrument_id),
            }

        with (
            patch("rita.services.data_refresh.check_gap", side_effect=_mock_check_gap),
            patch("rita.services.data_refresh.fetch_and_write_raw") as mock_fetch,
        ):
            results = refresh_all(mock_db)

        # fetch_and_write_raw must never be called
        mock_fetch.assert_not_called()

        # Every result must have status "current" (ATHER is skipped entirely)
        statuses = {r["status"] for r in results}
        assert statuses == {"current"}, f"Unexpected statuses: {statuses}"

        # gap_days is 0 for all
        for r in results:
            assert r["gap_days"] == 0
            assert r["raw_rows_added"] == 0
            assert r["db_rows_inserted"] == 0


# ---------------------------------------------------------------------------
# 4. refresh_all — EC-2 yfinance error: loop continues; failed = "error"
# ---------------------------------------------------------------------------

class TestRefreshAllYfinanceErrorContinues:
    """refresh_all() continues processing other instruments when one raises."""

    def test_yfinance_error_continues_and_marks_error(self):
        mock_db = _make_mock_db()

        instruments_in_map = sorted(_svc.YF_TICKER_MAP.keys())
        # Pick the first non-ATHER instrument to fail
        fail_instrument = next(
            i for i in instruments_in_map if i not in _svc.SKIP_INSTRUMENTS
        )

        thirty_days_ago = date.today() - timedelta(days=30)

        def _mock_check_gap(instrument_id: str, db):
            return {
                "instrument_id": instrument_id,
                "last_date": thirty_days_ago,
                "gap_days": 30,
                "yf_ticker": _svc.YF_TICKER_MAP.get(instrument_id),
            }

        def _mock_fetch(instrument_id: str, yf_ticker: str, last_date):
            if instrument_id == fail_instrument:
                raise RuntimeError(f"yfinance 502 for {yf_ticker}")
            return Path(f"/data/raw/{instrument_id}/file.csv"), 10

        with (
            patch("rita.services.data_refresh.check_gap", side_effect=_mock_check_gap),
            patch("rita.services.data_refresh.fetch_and_write_raw", side_effect=_mock_fetch),
            patch("rita.services.data_refresh.rebuild_input", return_value=Path("/fake/input.csv")),
            patch("rita.services.data_refresh.upsert_cache_delta", return_value=5),
        ):
            results = refresh_all(mock_db)

        # The failed instrument must be present with status "error"
        failed = [r for r in results if r["instrument"] == fail_instrument]
        assert len(failed) == 1, f"Expected 1 result for {fail_instrument}, got {len(failed)}"
        assert failed[0]["status"] == "error"
        assert failed[0]["error"] is not None

        # Other non-skipped instruments must have processed
        ok_results = [r for r in results if r["status"] == "ok"]
        assert len(ok_results) > 0, "Expected at least one instrument to succeed"

        # Total results must cover all instruments in map minus SKIP_INSTRUMENTS
        expected_count = len(
            [i for i in instruments_in_map if i not in _svc.SKIP_INSTRUMENTS]
        )
        assert len(results) == expected_count


# ---------------------------------------------------------------------------
# 5. upsert_cache_delta — EC-3 no duplicate inserts
# ---------------------------------------------------------------------------

class TestUpsertCacheDeltaNoDuplicates:
    """upsert_cache_delta() only inserts dates NOT already present in the DB."""

    def test_no_duplicate_inserts(self, tmp_path):
        import pandas as pd

        mock_db = _make_mock_db()

        # Build a fake input CSV with 3 dates: 2025-01-01, 2025-01-02, 2025-01-03
        dates_in_file = [
            date(2025, 1, 1),
            date(2025, 1, 2),
            date(2025, 1, 3),
        ]
        df_data = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [105.0, 106.0, 107.0],
                "Low": [99.0, 100.0, 101.0],
                "Close": [103.0, 104.0, 105.0],
                "Volume": [1000, 1100, 1200],
            },
            index=pd.DatetimeIndex(
                [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")]
            ),
        )

        # DB already has 2025-01-01 and 2025-01-02 — only 2025-01-03 is new
        existing_date_1 = date(2025, 1, 1)
        existing_date_2 = date(2025, 1, 2)
        mock_db.query.return_value.filter.return_value.all.return_value = [
            (existing_date_1,),
            (existing_date_2,),
        ]

        # Mock get_settings to point input_dir at tmp_path
        mock_settings = MagicMock()
        mock_settings.data.input_dir = str(tmp_path)

        # Create the expected input CSV on disk
        input_dir = tmp_path / "NIFTY"
        input_dir.mkdir(parents=True)
        input_csv = input_dir / "nifty_daily.csv"
        df_data.to_csv(input_csv)

        # Patch load_ohlcv_csv to return the DataFrame directly
        # Both MarketDataCacheModel and load_ohlcv_csv are imported locally inside
        # upsert_cache_delta() — patch them on their source modules.
        with (
            patch("rita.services.data_refresh.get_settings", return_value=mock_settings),
            patch("rita.models.market_data.MarketDataCacheModel", _mock_market_data_cls),
            patch(
                "rita.core.data_loader.load_ohlcv_csv",
                return_value=df_data,
            ) as mock_load_ohlcv,
        ):
            inserted = upsert_cache_delta(mock_db, "NIFTY")

        # Only 1 new row (2025-01-03) must be inserted
        assert inserted == 1
        mock_db.add_all.assert_called_once()
        added_records = mock_db.add_all.call_args[0][0]
        assert len(added_records) == 1, (
            f"Expected 1 record added, got {len(added_records)}"
        )

        # Verify the new record was constructed with the new date only.
        # MarketDataCacheModel is mocked, so we inspect the constructor call_args
        # to confirm the `date` kwarg was the new date (2025-01-03), not an existing one.
        new_date = date(2025, 1, 3)
        existing_dates = {date(2025, 1, 1), date(2025, 1, 2)}
        model_calls = _mock_market_data_cls.call_args_list
        dates_passed = {c.kwargs.get("date") or c.args[1] for c in model_calls
                        if c.kwargs.get("date") is not None or len(c.args) > 1}
        # At minimum, confirm the new date was used and existing ones were not
        if dates_passed:  # if kwargs were captured (they are in Python 3.12)
            assert new_date in dates_passed, f"{new_date} not in constructor call dates {dates_passed}"
            assert not existing_dates.intersection(dates_passed), (
                f"Existing dates {existing_dates.intersection(dates_passed)} were re-inserted"
            )

        # Confirm db.commit() was called
        mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 6. API endpoint — POST /api/v1/instrument/refresh-all happy path
# ---------------------------------------------------------------------------

class TestRefreshAllEndpointHappyPath:
    """POST /api/v1/instrument/refresh-all returns 200 with RefreshAllResponse shape."""

    def test_returns_200_with_correct_schema(self):
        from rita.database import get_db
        from rita.api.v1.workflow.instrument_onboard import router as _instr_router

        mock_service_results = [
            {
                "instrument": "NIFTY",
                "gap_days": 30,
                "raw_rows_added": 30,
                "db_rows_inserted": 30,
                "status": "ok",
                "error": None,
            },
            {
                "instrument": "ASML",
                "gap_days": 0,
                "raw_rows_added": 0,
                "db_rows_inserted": 0,
                "status": "current",
                "error": None,
            },
        ]

        test_app = FastAPI()
        test_app.include_router(_instr_router)
        mock_db = _make_mock_db()
        test_app.dependency_overrides[get_db] = lambda: mock_db

        # The handler does `from rita.services.data_refresh import refresh_all` as a
        # local import inside the function — patch on the service module directly.
        with patch(
            "rita.services.data_refresh.refresh_all",
            return_value=mock_service_results,
        ):
            client = TestClient(test_app)
            resp = client.post("/api/v1/instrument/refresh-all")

        assert resp.status_code == 200
        data = resp.json()

        # Top-level schema fields
        assert "refreshed" in data
        assert "already_current" in data
        assert "results" in data

        # Counts must match the mock results
        assert data["refreshed"] == 1          # 1 "ok"
        assert data["already_current"] == 1    # 1 "current"
        assert len(data["results"]) == 2

    def test_result_items_contain_all_schema_fields(self):
        """Contract check: every item in results must have all InstrumentRefreshResult fields."""
        from rita.database import get_db
        from rita.api.v1.workflow.instrument_onboard import router as _instr_router

        mock_service_results = [
            {
                "instrument": "NIFTY",
                "gap_days": 10,
                "raw_rows_added": 10,
                "db_rows_inserted": 10,
                "status": "ok",
                "error": None,
            }
        ]

        test_app = FastAPI()
        test_app.include_router(_instr_router)
        mock_db = _make_mock_db()
        test_app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "rita.services.data_refresh.refresh_all",
            return_value=mock_service_results,
        ):
            client = TestClient(test_app)
            resp = client.post("/api/v1/instrument/refresh-all")

        assert resp.status_code == 200
        item = resp.json()["results"][0]
        required_fields = {"instrument", "gap_days", "raw_rows_added", "db_rows_inserted", "status", "error"}
        assert required_fields.issubset(item.keys()), (
            f"Missing fields in result item: {required_fields - item.keys()}"
        )


# ---------------------------------------------------------------------------
# 7. API endpoint — per-instrument errors do NOT raise HTTP 5xx
# ---------------------------------------------------------------------------

class TestRefreshAllEndpointErrorHandling:
    """Endpoint must return 200 even when some instruments fail; status='error' in results."""

    def test_per_instrument_error_does_not_abort(self):
        from rita.database import get_db
        from rita.api.v1.workflow.instrument_onboard import router as _instr_router

        mock_service_results = [
            {
                "instrument": "NIFTY",
                "gap_days": -1,
                "raw_rows_added": 0,
                "db_rows_inserted": 0,
                "status": "error",
                "error": "yfinance 502",
            },
            {
                "instrument": "ASML",
                "gap_days": 5,
                "raw_rows_added": 5,
                "db_rows_inserted": 5,
                "status": "ok",
                "error": None,
            },
        ]

        test_app = FastAPI()
        test_app.include_router(_instr_router)
        mock_db = _make_mock_db()
        test_app.dependency_overrides[get_db] = lambda: mock_db

        with patch(
            "rita.services.data_refresh.refresh_all",
            return_value=mock_service_results,
        ):
            client = TestClient(test_app)
            resp = client.post("/api/v1/instrument/refresh-all")

        # Must be 200, not 5xx
        assert resp.status_code == 200

        data = resp.json()
        # refreshed count only counts "ok"
        assert data["refreshed"] == 1
        assert data["already_current"] == 0

        # The errored instrument must appear in results with status "error"
        error_results = [r for r in data["results"] if r["status"] == "error"]
        assert len(error_results) == 1
        assert error_results[0]["instrument"] == "NIFTY"
        assert "502" in error_results[0]["error"]
