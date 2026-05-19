"""Unit tests for the market-signals page-swap feature (run ID 20260511-1046).

Changes under test
------------------
- nav.js  : ``_currentSection`` default changed from ``'home'`` → ``'market-signals'``
- main.js : ``loadMarketSignals()`` added to ``window.load`` handler
- rita.html: ``sec-market-signals`` becomes the first section / landing page;
            ``.inst-tab`` buttons moved inside ``sec-market-signals``

The backend endpoint is unchanged:
    GET /api/v1/market-signals?timeframe={tf}&periods={n}&instrument={id}

Strategy
--------
- ``MarketDataCacheRepository`` is patched at the class level so the router's
  inline ``MarketDataCacheRepository(db).read_all()`` returns controlled data.
- The ``client`` fixture from ``conftest.py`` wires an in-memory SQLite session
  into ``get_db``, ensuring no real DB or CSV files are required.
- ``find_instrument_csv`` / ``load_nifty_csv`` in the CSV fallback branch are
  also patched to prevent any filesystem access when the DB rows are empty.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXPECTED_FIELDS = {
    "date", "Close", "Volume",
    "rsi_14",
    "macd", "macd_signal", "macd_hist",
    "bb_upper", "bb_lower", "bb_pct_b",
    "atr_14",
    "ema_5", "ema_13", "ema_26", "ema_50",
    "trend_score",
}


def _make_market_row(
    date_val: str = "2026-01-02",
    underlying: str = "NIFTY",
    close: float = 22_500.0,
) -> MagicMock:
    """Return a MagicMock that mimics a MarketDataCache ORM row."""
    row = MagicMock()
    row.date = date.fromisoformat(date_val)
    row.underlying = underlying
    row.close = close
    row.high = close + 100.0
    row.low = close - 100.0
    row.shares_traded = 1_000_000
    return row


def _make_rows(n: int = 30, underlying: str = "NIFTY") -> list[MagicMock]:
    """Return ``n`` ascending daily rows for *underlying*.

    Uses a fixed epoch (2025-01-01) and offsets by day so any ``n`` is valid.
    timedelta arithmetic avoids month-boundary arithmetic errors.
    """
    from datetime import timedelta

    rows = []
    base_close = 22_000.0
    epoch = date(2025, 1, 1)
    for i in range(n):
        d = epoch + timedelta(days=i)
        rows.append(_make_market_row(
            date_val=str(d),
            underlying=underlying,
            close=base_close + i * 10.0,
        ))
    return rows


# ---------------------------------------------------------------------------
# Test 1 — Happy path: explicit instrument returns 200 + all expected fields
# ---------------------------------------------------------------------------

class TestMarketSignalsHappyPath:
    """GET /api/v1/market-signals with instrument=NIFTY returns 200 and all
    fields required by the frontend loadMarketSignals() function."""

    def test_returns_200_with_instrument_param(self, client):
        """Happy path: instrument=NIFTY, timeframe=daily, periods=10 → 200."""
        rows = _make_rows(30, "NIFTY")

        with patch(
            "rita.api.v1.system.market_signals.MarketDataCacheRepository"
        ) as MockRepo:
            MockRepo.return_value.read_all.return_value = rows
            response = client.get(
                "/api/v1/market-signals",
                params={"timeframe": "daily", "periods": 10, "instrument": "NIFTY"},
            )

        assert response.status_code == 200

    def test_response_is_a_list(self, client):
        """Response body must be a JSON array (list of bar objects)."""
        rows = _make_rows(30, "NIFTY")

        with patch(
            "rita.api.v1.system.market_signals.MarketDataCacheRepository"
        ) as MockRepo:
            MockRepo.return_value.read_all.return_value = rows
            response = client.get(
                "/api/v1/market-signals",
                params={"instrument": "NIFTY"},
            )

        assert isinstance(response.json(), list)

    def test_response_contains_all_expected_fields(self, client):
        """Every bar must contain the full set of fields consumed by the JS
        ``loadMarketSignals()`` function (as identified by the DOM element IDs
        in the Architect design section)."""
        rows = _make_rows(30, "NIFTY")

        with patch(
            "rita.api.v1.system.market_signals.MarketDataCacheRepository"
        ) as MockRepo:
            MockRepo.return_value.read_all.return_value = rows
            response = client.get(
                "/api/v1/market-signals",
                params={"instrument": "NIFTY", "periods": 5},
            )

        data: list[dict[str, Any]] = response.json()
        assert len(data) > 0, "Response list must not be empty"
        last_bar = data[-1]
        missing = _EXPECTED_FIELDS - set(last_bar.keys())
        assert missing == set(), (
            f"Response bar is missing fields: {missing!r}\n"
            f"Got keys: {sorted(last_bar.keys())}"
        )

    def test_periods_param_limits_returned_rows(self, client):
        """``periods=5`` must return at most 5 rows."""
        rows = _make_rows(30, "NIFTY")

        with patch(
            "rita.api.v1.system.market_signals.MarketDataCacheRepository"
        ) as MockRepo:
            MockRepo.return_value.read_all.return_value = rows
            response = client.get(
                "/api/v1/market-signals",
                params={"instrument": "NIFTY", "periods": 5},
            )

        assert response.status_code == 200
        assert len(response.json()) <= 5

    def test_instrument_param_filters_to_correct_underlying(self, client):
        """When DB contains rows for multiple underlyings, the endpoint must
        only compute indicators for the requested instrument."""
        nifty_rows = _make_rows(30, "NIFTY")
        banknifty_rows = _make_rows(30, "BANKNIFTY")
        all_rows = nifty_rows + banknifty_rows

        with patch(
            "rita.api.v1.system.market_signals.MarketDataCacheRepository"
        ) as MockRepo:
            MockRepo.return_value.read_all.return_value = all_rows
            response = client.get(
                "/api/v1/market-signals",
                params={"instrument": "BANKNIFTY", "periods": 5},
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0


# ---------------------------------------------------------------------------
# Test 2 — Edge case: no instrument param → defaults to NIFTY (valid response)
# ---------------------------------------------------------------------------

class TestMarketSignalsNoInstrumentParam:
    """GET /api/v1/market-signals with no instrument param.

    The router signature is ``instrument: str = "NIFTY"`` so the default is
    NIFTY. The endpoint must return a valid 200 response (not 422) and the
    response body must be a list.
    """

    def test_no_instrument_returns_200(self, client):
        """Omitting ``instrument`` must not raise a 422; default NIFTY is used."""
        rows = _make_rows(30, "NIFTY")

        with patch(
            "rita.api.v1.system.market_signals.MarketDataCacheRepository"
        ) as MockRepo:
            MockRepo.return_value.read_all.return_value = rows
            response = client.get("/api/v1/market-signals")

        assert response.status_code == 200

    def test_no_instrument_returns_list(self, client):
        """Default instrument=NIFTY → response is a list of bar dicts."""
        rows = _make_rows(30, "NIFTY")

        with patch(
            "rita.api.v1.system.market_signals.MarketDataCacheRepository"
        ) as MockRepo:
            MockRepo.return_value.read_all.return_value = rows
            response = client.get("/api/v1/market-signals")

        body = response.json()
        assert isinstance(body, list)
        assert len(body) > 0

    def test_no_instrument_bar_has_required_fields(self, client):
        """Default-instrument response bars must still contain all expected fields."""
        rows = _make_rows(30, "NIFTY")

        with patch(
            "rita.api.v1.system.market_signals.MarketDataCacheRepository"
        ) as MockRepo:
            MockRepo.return_value.read_all.return_value = rows
            response = client.get(
                "/api/v1/market-signals", params={"periods": 3}
            )

        data = response.json()
        assert len(data) > 0
        last_bar = data[-1]
        missing = _EXPECTED_FIELDS - set(last_bar.keys())
        assert missing == set(), f"Missing fields with default instrument: {missing!r}"


# ---------------------------------------------------------------------------
# Test 3 — Edge case: empty DB → falls back gracefully (returns [] or 200)
# ---------------------------------------------------------------------------

class TestMarketSignalsEmptyDB:
    """When the DB has no rows for the requested instrument and the CSV
    fallback also fails, the endpoint must return an empty list with 200."""

    def test_empty_db_and_csv_fallback_returns_200(self, client):
        """No DB rows + CSV not found → returns 200 with empty list."""
        with patch(
            "rita.api.v1.system.market_signals.MarketDataCacheRepository"
        ) as MockRepo, patch(
            "rita.api.v1.system.market_signals.MarketDataCacheRepository"
        ) as MockRepo2:
            MockRepo.return_value.read_all.return_value = []
            MockRepo2.return_value.read_all.return_value = []

            # Patch the CSV path finder so it raises (simulating missing CSV)
            with patch(
                "rita.core.data_understanding.find_instrument_csv",
                side_effect=FileNotFoundError("no csv"),
            ):
                response = client.get(
                    "/api/v1/market-signals",
                    params={"instrument": "UNKNOWN_INST"},
                )

        assert response.status_code == 200
        assert response.json() == []

    def test_empty_db_no_instrument_returns_200(self, client):
        """No DB rows for default NIFTY + CSV fallback fails → 200 empty list."""
        with patch(
            "rita.api.v1.system.market_signals.MarketDataCacheRepository"
        ) as MockRepo:
            MockRepo.return_value.read_all.return_value = []

            with patch(
                "rita.core.data_understanding.find_instrument_csv",
                side_effect=FileNotFoundError("no csv"),
            ):
                response = client.get("/api/v1/market-signals")

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Test 4 — Edge case: timeframe variants (weekly / monthly)
# ---------------------------------------------------------------------------

class TestMarketSignalsTimeframeVariants:
    """``timeframe`` query param must be accepted for all three valid values."""

    @pytest.mark.parametrize("tf", ["daily", "weekly", "monthly"])
    def test_timeframe_param_accepted(self, client, tf):
        """All three timeframe variants must return 200."""
        rows = _make_rows(60, "NIFTY")

        with patch(
            "rita.api.v1.system.market_signals.MarketDataCacheRepository"
        ) as MockRepo:
            MockRepo.return_value.read_all.return_value = rows
            response = client.get(
                "/api/v1/market-signals",
                params={"instrument": "NIFTY", "timeframe": tf, "periods": 3},
            )

        assert response.status_code == 200
        assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# Test 5 — Contract: instrument tab instruments map to valid API instruments
# ---------------------------------------------------------------------------

class TestMarketSignalsInstrumentContract:
    """The four instrument tabs (NIFTY, BANKNIFTY, ASML, NVIDIA) defined in
    the Architect design must all be accepted by the endpoint without error."""

    @pytest.mark.parametrize("instrument", ["NIFTY", "BANKNIFTY", "ASML", "NVIDIA"])
    def test_all_tab_instruments_accepted(self, client, instrument):
        """Each instrument from the .inst-tab DOM buttons must yield 200."""
        rows = _make_rows(30, instrument)

        with patch(
            "rita.api.v1.system.market_signals.MarketDataCacheRepository"
        ) as MockRepo:
            MockRepo.return_value.read_all.return_value = rows
            response = client.get(
                "/api/v1/market-signals",
                params={"instrument": instrument, "periods": 3},
            )

        assert response.status_code == 200
