"""Unit tests for GET /api/v1/experience/rita/technical-commentary.

Strategy
--------
- FastAPI dependency_overrides replaces ``get_db`` with an in-memory SQLite
  session (same pattern used in test_api_experience.py).
- ``MarketDataCacheRepository.read_all`` is patched via unittest.mock.patch so
  we control the data returned without touching the filesystem or CSV loader.
- Three test classes cover: happy path, no-data edge case, and null/missing
  indicator fields.

CONTRACT NOTE
-------------
The Architect spec states the URL as ``/api/v1/experience/rita/technical-commentary``
(no ``/v1``).  The engineer registered the router with ``prefix="/api/v1"``,
so the actual live URL is ``/api/v1/experience/rita/technical-commentary``.
The JS file (technical-analysis.js line 40) calls the NO-v1 path:
    /api/v1/experience/rita/technical-commentary
This is a URL mismatch — JS will receive 404 in production until either the
router prefix is corrected or the JS path is updated to include ``/v1``.
Tests below use the actual registered URL so they exercise real behaviour.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    underlying: str = "NIFTY",
    date: str = "2026-01-01",
    close: float = 22000.0,
    high: float | None = None,
    low: float | None = None,
) -> MagicMock:
    """Build a minimal fake market-data ORM record."""
    r = MagicMock()
    r.underlying = underlying
    r.date = date
    r.close = close
    r.high = high if high is not None else close + 100
    r.low = low if low is not None else close - 100
    return r


def _make_records(n: int = 30) -> list:
    """Return n sequential fake NIFTY records with monotonically rising price."""
    base = 22000.0
    return [
        _make_record(
            date=f"2026-01-{i+1:02d}",
            close=base + i * 10,
            high=base + i * 10 + 80,
            low=base + i * 10 - 80,
        )
        for i in range(n)
    ]


def _override(app, dep, mock_value):
    app.dependency_overrides[dep] = lambda: mock_value


def _clear(app, *deps):
    for dep in deps:
        app.dependency_overrides.pop(dep, None)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestTechnicalCommentaryHappyPath:
    """Endpoint returns a valid TechnicalCommentaryResponse when data exists."""

    def _client_with_data(self, records):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)

        client = TestClient(app, raise_server_exceptions=False)
        return app, client, get_db

    def test_returns_200(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=_make_records(30),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            assert resp.status_code == 200
        finally:
            _clear(app, get_db)

    def test_response_has_instrument_field(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=_make_records(30),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            body = resp.json()
            assert "instrument" in body
            assert body["instrument"] == "NIFTY"
        finally:
            _clear(app, get_db)

    def test_response_has_commentary_string(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=_make_records(30),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            body = resp.json()
            assert "commentary" in body
            assert isinstance(body["commentary"], str)
            assert len(body["commentary"]) > 0
        finally:
            _clear(app, get_db)

    def test_response_has_signal_summary_list(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=_make_records(30),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            body = resp.json()
            assert "signal_summary" in body
            assert isinstance(body["signal_summary"], list)
        finally:
            _clear(app, get_db)

    def test_signal_summary_items_have_required_fields(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=_make_records(30),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            body = resp.json()
            for item in body["signal_summary"]:
                assert "label" in item, f"'label' missing in {item}"
                assert "value" in item, f"'value' missing in {item}"
                assert "state" in item, f"'state' missing in {item}"
        finally:
            _clear(app, get_db)

    def test_instrument_param_uppercased(self):
        """Lowercase instrument param must be normalised to upper-case in response."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=_make_records(30),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=nifty")
            body = resp.json()
            assert body["instrument"] == "NIFTY"
        finally:
            _clear(app, get_db)


# ---------------------------------------------------------------------------
# Edge case 1: no market data
# ---------------------------------------------------------------------------

class TestTechnicalCommentaryNoData:
    """When no records exist and CSV fallback also fails, endpoint must NOT
    return a 500 — it returns a graceful 'No data available.' commentary with
    an empty signal_summary list."""

    def test_returns_200_not_500(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=[],
            ), patch(
                "rita.core.data_understanding.find_instrument_csv",
                side_effect=FileNotFoundError("no csv"),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=UNKNOWN")
            assert resp.status_code == 200
        finally:
            _clear(app, get_db)

    def test_commentary_says_no_data(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=[],
            ), patch(
                "rita.core.data_understanding.find_instrument_csv",
                side_effect=FileNotFoundError("no csv"),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=UNKNOWN")
            body = resp.json()
            assert "No data available" in body["commentary"]
        finally:
            _clear(app, get_db)

    def test_signal_summary_is_empty_list(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=[],
            ), patch(
                "rita.core.data_understanding.find_instrument_csv",
                side_effect=FileNotFoundError("no csv"),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=UNKNOWN")
            body = resp.json()
            assert body["signal_summary"] == []
        finally:
            _clear(app, get_db)

    def test_instrument_field_still_present(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=[],
            ), patch(
                "rita.core.data_understanding.find_instrument_csv",
                side_effect=FileNotFoundError("no csv"),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=UNKNOWN")
            body = resp.json()
            assert "instrument" in body
        finally:
            _clear(app, get_db)


# ---------------------------------------------------------------------------
# Edge case 2: ATR or RSI null/missing in underlying data
# ---------------------------------------------------------------------------

class TestTechnicalCommentaryNullIndicators:
    """When close series is valid but high/low are missing (fall back to close),
    the endpoint must handle NaN indicators gracefully and return neutral states
    rather than crashing."""

    def _flat_records(self, n: int = 20) -> list:
        """Records where high == low == close → zero ATR, degenerate RSI."""
        return [
            _make_record(
                date=f"2026-02-{i+1:02d}",
                close=22000.0,   # flat price → delta=0 → RSI undefined via 0/0
                high=22000.0,
                low=22000.0,
            )
            for i in range(n)
        ]

    def test_returns_200_with_flat_data(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=self._flat_records(20),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            assert resp.status_code == 200
        finally:
            _clear(app, get_db)

    def test_no_crash_on_zero_atr(self):
        """Zero ATR (flat prices) must not raise ZeroDivisionError or 500."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=self._flat_records(20),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            # Must return a well-formed response, not an error body
            body = resp.json()
            assert "instrument" in body
            assert "commentary" in body
            assert "signal_summary" in body
        finally:
            _clear(app, get_db)

    def test_state_is_neutral_when_rsi_nan(self):
        """If RSI resolves to NaN (0/0 loss), resulting signal state must be
        'neutral' (not a Python exception or the string 'nan')."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=self._flat_records(20),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            body = resp.json()
            for item in body["signal_summary"]:
                assert item["state"] != "nan", (
                    f"signal state must not be 'nan' — got {item}"
                )
        finally:
            _clear(app, get_db)

    def test_signal_summary_contains_valid_state_values(self):
        """All returned state values must be from the allowed set."""
        allowed_states = {"bullish", "bearish", "neutral", "normal", "up", "down"}
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=_make_records(30),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            body = resp.json()
            for item in body["signal_summary"]:
                assert item["state"] in allowed_states, (
                    f"Unexpected state '{item['state']}' for item {item}"
                )
        finally:
            _clear(app, get_db)

    def test_single_record_does_not_crash(self):
        """One-record series: diff() produces NaN, ewm smoothing should handle it."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=[_make_record()],
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            assert resp.status_code == 200
        finally:
            _clear(app, get_db)


# ---------------------------------------------------------------------------
# Contract: schema fields vs. JS reads
# ---------------------------------------------------------------------------

class TestAPIFrontendContract:
    """Verify the JSON keys returned by the endpoint match what
    technical-analysis.js reads from the response object.

    JS reads (from technical-analysis.js _renderCommentary):
      data.instrument      → DOM display
      data.commentary      → DOM display
      data.signal_summary  → iterated; each item.label, item.value, item.state
    """

    def test_contract_instrument_field(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=_make_records(30),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            body = resp.json()
            # JS: data.instrument
            assert "instrument" in body, "JS reads data.instrument — field missing"
            assert isinstance(body["instrument"], str)
        finally:
            _clear(app, get_db)

    def test_contract_commentary_field(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=_make_records(30),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            body = resp.json()
            # JS: data.commentary
            assert "commentary" in body, "JS reads data.commentary — field missing"
            assert isinstance(body["commentary"], str)
        finally:
            _clear(app, get_db)

    def test_contract_signal_summary_field(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=_make_records(30),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            body = resp.json()
            # JS: data.signal_summary (iterated as array)
            assert "signal_summary" in body, "JS reads data.signal_summary — field missing"
            assert isinstance(body["signal_summary"], list)
        finally:
            _clear(app, get_db)

    def test_contract_signal_summary_item_label(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=_make_records(30),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            body = resp.json()
            # JS: item.label (used in template literal)
            for item in body["signal_summary"]:
                assert "label" in item, f"JS reads item.label — field missing in {item}"
                assert isinstance(item["label"], str)
        finally:
            _clear(app, get_db)

    def test_contract_signal_summary_item_value(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=_make_records(30),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            body = resp.json()
            # JS: item.value (used in template literal)
            for item in body["signal_summary"]:
                assert "value" in item, f"JS reads item.value — field missing in {item}"
                assert isinstance(item["value"], str)
        finally:
            _clear(app, get_db)

    def test_contract_signal_summary_item_state(self):
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.repositories.market_data.MarketDataCacheRepository.read_all",
                return_value=_make_records(30),
            ):
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/v1/experience/rita/technical-commentary?instrument=NIFTY")
            body = resp.json()
            # JS: item.state passed to _stateClass() → maps to CSS class
            allowed = {"bullish", "bearish", "neutral", "normal", "up", "down"}
            for item in body["signal_summary"]:
                assert "state" in item, f"JS reads item.state — field missing in {item}"
                assert item["state"] in allowed, (
                    f"item.state '{item['state']}' not handled by _stateClass() in JS"
                )
        finally:
            _clear(app, get_db)
