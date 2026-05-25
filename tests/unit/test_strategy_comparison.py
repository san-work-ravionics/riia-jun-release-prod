"""Unit tests for GET /api/v1/experience/rita/strategy-comparison.

Test strategy
-------------
- FastAPI dependency_overrides replaces ``get_db`` so no real DB is needed.
- ``rita.core.data_loader.load_instrument_data`` is patched to control OHLCV
  data without touching the filesystem.
- ``_run_strategies_cached`` uses ``functools.lru_cache``; the cache is cleared
  between tests so each test gets a fresh call.
- Four test classes cover: happy-path behaviour, edge cases from the Architect
  section, internal strategy runner helpers, and the API-frontend contract.

ENDPOINT
--------
Router prefix="/api/v1", path="/experience/rita/strategy-comparison"
→ full URL: /api/v1/experience/rita/strategy-comparison

IMPORT PATHS (verified from rita/api/experience/rita.py)
---------------------------------------------------------
Handler:    rita.api.experience.rita.experience_strategy_comparison
Cache fn:   rita.api.experience.rita._run_strategies_cached
Loader:     rita.core.data_loader.load_instrument_data  (used inside _run_strategies_cached)
Schemas:    rita.schemas.strategy_comparison — StrategyResult, StrategySummaryRow,
            StrategyComparisonResponse

JS CONTRACT (strategy-comparison.js)
--------------------------------------
Fields read:
  data.dates                          — array of ISO strings (x-axis labels)
  data.error                          — non-null string on failure
  data.strategies[].name              — strategy label
  data.strategies[].equity            — float array (portfolio value)
  data.strategies[].color             — CSS hex string
  data.summary[].name                 — table row label
  data.summary[].total_return_pct     — float
  data.summary[].sharpe               — float
  data.summary[].max_drawdown_pct     — float
  data.summary[].n_trades             — int
  data.summary[].win_rate_pct         — float
  data.summary[].final_value          — float
"""

from __future__ import annotations

from functools import lru_cache
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Constant / helpers
# ---------------------------------------------------------------------------

_SC_URL = "/api/v1/experience/rita/strategy-comparison"

# 252 + 60 trading-day prices so warmup window is satisfied for all 5 strategies
_N_PRICES = 312
_BASE_PRICE = 100.0
_PRICE_STEP = 0.5  # gentle uptrend so momentum + B&H are profitable

EXPECTED_STRATEGY_NAMES = {
    "Buy and Hold",
    "Value Investing",
    "Momentum Investing",
    "Swing Trading",
    "Support-Resistance",
}


def _make_ohlcv_df(n: int = _N_PRICES, year: int = 2025) -> pd.DataFrame:
    """Return a minimal OHLCV DataFrame with DatetimeIndex spanning two years
    so year-filtering in the endpoint works correctly.

    The index starts 252 trading days before Jan 1 of *year* so the warmup
    slice is always available.
    """
    # Start early enough to cover 252-day warmup + the full target year
    start = pd.Timestamp(f"{year - 1}-01-01")
    dates = pd.bdate_range(start=start, periods=n)
    prices = [_BASE_PRICE + i * _PRICE_STEP for i in range(n)]
    df = pd.DataFrame(
        {
            "Open": prices,
            "High": [p * 1.01 for p in prices],
            "Low": [p * 0.99 for p in prices],
            "Close": prices,
            "Volume": [1_000_000] * n,
        },
        index=dates,
    )
    return df


def _clear_cache() -> None:
    """Clear the LRU cache on _run_strategies_cached so each test is isolated."""
    from rita.api.experience.rita import _run_strategies_cached
    _run_strategies_cached.cache_clear()


def _get_client_and_app():
    """Return (TestClient, app) with raise_server_exceptions=False."""
    from rita.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app, raise_server_exceptions=False)
    return client, app


def _override(app, dep, mock_value):
    app.dependency_overrides[dep] = lambda: mock_value


def _clear_dep(app, *deps):
    for dep in deps:
        app.dependency_overrides.pop(dep, None)


# ---------------------------------------------------------------------------
# Class 1 — Happy-path / core endpoint behaviour
# ---------------------------------------------------------------------------

class TestStrategyComparisonHappyPath:
    """Happy-path tests with a valid OHLCV DataFrame."""

    def setup_method(self):
        _clear_cache()

    def test_returns_200_for_valid_instrument_and_year(self):
        """GET with instrument=NIFTY&year=2025 must return HTTP 200."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                resp = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025")
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_response_contains_required_top_level_keys(self):
        """Response must include instrument, year, dates, strategies, summary."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        for key in ("instrument", "year", "dates", "strategies", "summary"):
            assert key in body, f"Top-level key '{key}' missing from response"

    def test_instrument_echoed_uppercase(self):
        """instrument field in response must be the uppercased query param."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=nifty&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert body["instrument"] == "NIFTY"

    def test_year_echoed_in_response(self):
        """year field in response must match the requested year."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert body["year"] == 2025

    def test_exactly_five_strategies_returned(self):
        """strategies list must always contain exactly 5 entries."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert len(body["strategies"]) == 5, (
            f"Expected 5 strategies, got {len(body['strategies'])}"
        )

    def test_strategy_names_match_expected_set(self):
        """All 5 canonical strategy names must be present in the response."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        names = {s["name"] for s in body["strategies"]}
        assert names == EXPECTED_STRATEGY_NAMES, (
            f"Strategy name mismatch. Got: {names}"
        )

    def test_strategy_has_required_fields(self):
        """Every strategy entry must have name, equity (list), and color."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        for s in body["strategies"]:
            assert "name" in s, f"Strategy missing 'name': {s}"
            assert "equity" in s, f"Strategy {s.get('name')} missing 'equity'"
            assert "color" in s, f"Strategy {s.get('name')} missing 'color'"
            assert isinstance(s["equity"], list), (
                f"Strategy {s['name']}.equity must be a list"
            )

    def test_summary_has_five_rows(self):
        """summary must have exactly 5 rows — one per strategy."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert len(body["summary"]) == 5, (
            f"Expected 5 summary rows, got {len(body['summary'])}"
        )

    def test_summary_row_has_all_metric_fields(self):
        """Each summary row must have all 7 metric fields."""
        required = {"name", "total_return_pct", "sharpe", "max_drawdown_pct",
                    "n_trades", "win_rate_pct", "final_value"}
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        for row in body["summary"]:
            missing = required - set(row.keys())
            assert not missing, (
                f"Summary row '{row.get('name')}' missing fields: {missing}"
            )

    def test_dates_is_list_of_strings(self):
        """dates must be a list of ISO date strings."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert isinstance(body["dates"], list)
        assert len(body["dates"]) > 0
        # Spot-check format: YYYY-MM-DD
        for d in body["dates"][:3]:
            assert len(d) == 10 and d[4] == "-" and d[7] == "-", (
                f"Date '{d}' is not in YYYY-MM-DD format"
            )

    def test_equity_length_matches_dates_length(self):
        """Each strategy's equity array must be the same length as dates."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        n_dates = len(body["dates"])
        for s in body["strategies"]:
            assert len(s["equity"]) == n_dates, (
                f"Strategy '{s['name']}' equity length {len(s['equity'])} "
                f"!= dates length {n_dates}"
            )

    def test_no_error_field_on_success(self):
        """error field must be null (None) on a successful response."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert body.get("error") is None, (
            f"error should be null on success, got: {body['error']}"
        )

    def test_color_is_hex_string(self):
        """Every strategy color must be a CSS hex string starting with '#'."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        for s in body["strategies"]:
            assert isinstance(s["color"], str) and s["color"].startswith("#"), (
                f"Strategy '{s['name']}' color '{s['color']}' is not a hex string"
            )

    def test_no_db_commit_in_route(self):
        """Experience tier must be read-only — db.commit() must never be called."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                client.get(f"{_SC_URL}?instrument=NIFTY&year=2025")
        finally:
            app.dependency_overrides.pop(get_db, None)

        mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Class 2 — Edge cases (from Architect section)
# ---------------------------------------------------------------------------

class TestStrategyComparisonEdgeCases:
    """Architect edge cases 1-5."""

    def setup_method(self):
        _clear_cache()

    # ── Edge case 1: FileNotFoundError → graceful error payload, not 500 ──────

    def test_instrument_not_found_returns_200_with_error(self):
        """Edge case 1 + 5: FileNotFoundError from data_loader must return 200
        with error field set, not a 500."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                side_effect=FileNotFoundError("CSV not found"),
            ):
                client, _ = _get_client_and_app()
                resp = client.get(f"{_SC_URL}?instrument=UNKNOWN&year=2025")
                body = resp.json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200, (
            f"FileNotFoundError must produce 200, got {resp.status_code}"
        )
        assert body.get("error") is not None, (
            "error field must be non-null when instrument CSV is missing"
        )
        assert body["strategies"] == [], "strategies must be empty on error"
        assert body["summary"] == [], "summary must be empty on error"

    # ── Edge case 1 (empty year): year has no data ────────────────────────────

    def test_empty_year_returns_error_payload(self):
        """Edge case 1: if OHLCV has no rows for the requested year, the
        endpoint must return an error payload instead of crashing."""
        # DataFrame only has rows for 2020 — not 2025
        df_old = _make_ohlcv_df(n=200, year=2020)
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=df_old,
            ):
                client, _ = _get_client_and_app()
                resp = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025")
                body = resp.json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        assert body.get("error") is not None, (
            "error field must be non-null when no data exists for the year"
        )

    # ── Edge case 2: NaN/inf sanitized to 0.0 ────────────────────────────────

    def test_sanitize_replaces_nan_with_zero(self):
        """Edge case 2: _sanitize() must replace NaN with 0.0."""
        from rita.api.experience.rita import _sanitize
        import math
        assert _sanitize(float("nan")) == 0.0
        assert _sanitize(float("inf")) == 0.0
        assert _sanitize(float("-inf")) == 0.0
        assert _sanitize(None) == 0.0
        assert _sanitize(3.14159) == pytest.approx(3.1416, abs=1e-3)

    def test_equity_values_are_finite_floats(self):
        """Edge case 2: all equity values returned by the endpoint must be
        finite floats (no NaN or inf)."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        import math
        for s in body["strategies"]:
            for i, v in enumerate(s["equity"]):
                assert math.isfinite(v), (
                    f"Strategy '{s['name']}' equity[{i}]={v} is not finite"
                )

    def test_summary_floats_are_finite(self):
        """Edge case 2: summary metric floats must all be finite."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        import math
        float_fields = ("total_return_pct", "sharpe", "max_drawdown_pct",
                        "win_rate_pct", "final_value")
        for row in body["summary"]:
            for field in float_fields:
                v = row[field]
                assert math.isfinite(v), (
                    f"summary['{row['name']}'].{field}={v} is not finite"
                )

    # ── Edge case 3: invalid year is coerced to 2025 ─────────────────────────

    def test_invalid_year_coerced_to_2025(self):
        """Edge case 3 (guard): year values other than 2025/2026 must be
        silently coerced to 2025 by the endpoint guard."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2024").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        # Year 2024 is not in (2025, 2026) so must be coerced to 2025
        assert body["year"] == 2025, (
            f"year=2024 should be coerced to 2025, got {body['year']}"
        )

    def test_year_2026_is_accepted(self):
        """Edge case 3: year=2026 is a valid value and must not be coerced."""
        df_2026 = _make_ohlcv_df(n=_N_PRICES, year=2026)
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=df_2026,
            ):
                client, _ = _get_client_and_app()
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2026").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert body["year"] == 2026, (
            f"year=2026 should be passed through, got {body['year']}"
        )

    # ── Edge case 4: commentary dispatch key is registered ───────────────────

    def test_commentary_dispatch_key_registered(self):
        """Edge case 4: ('rita', 'strategy-comparison') must be in _DISPATCH
        in commentary.py so the key is always present before the endpoint
        serves any request."""
        from rita.api.v1.workflow.commentary import _DISPATCH
        assert ("rita", "strategy-comparison") in _DISPATCH, (
            "('rita', 'strategy-comparison') missing from commentary._DISPATCH — "
            "would return 400 on every commentary POST"
        )

    # ── Edge case 5: general exception from data_loader → 200 + error ────────

    def test_generic_data_loader_exception_returns_error_payload(self):
        """Edge case 5: any Exception from load_instrument_data must return 200
        with an error message rather than surfacing a 500."""
        from rita.main import app
        from rita.database import get_db

        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                side_effect=RuntimeError("unexpected data error"),
            ):
                client, _ = _get_client_and_app()
                resp = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025")
                body = resp.json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        assert body.get("error") is not None, (
            "RuntimeError from data_loader must produce non-null error field"
        )

    # ── Zero-trade strategies: win_rate_pct must be 0.0 not divide-by-zero ───

    def test_zero_trade_strategy_win_rate_is_zero(self):
        """Edge case 2 (zero trades): _compute_metrics with n_trades=0 must
        return win_rate_pct=0.0 without division-by-zero."""
        from rita.api.experience.rita import _compute_metrics, _INITIAL_CAPITAL

        # Flat equity — no trades, no wins
        equity = [_INITIAL_CAPITAL] * 20
        row = _compute_metrics(equity, n_trades=0, wins=0)
        assert row.win_rate_pct == 0.0, (
            f"win_rate_pct with 0 trades should be 0.0, got {row.win_rate_pct}"
        )
        assert row.n_trades == 0


# ---------------------------------------------------------------------------
# Class 3 — Strategy runner unit tests
# ---------------------------------------------------------------------------

class TestStrategyRunners:
    """Direct tests for the five inline strategy runner functions."""

    def _flat_prices(self, n: int = 50, price: float = 100.0) -> list[float]:
        return [price] * n

    def _trending_up(self, n: int = 50, start: float = 100.0) -> list[float]:
        return [start + i * 0.5 for i in range(n)]

    def test_buy_and_hold_returns_equity_same_length(self):
        from rita.api.experience.rita import _run_buy_and_hold
        close = self._trending_up(n=100)
        equity, n_trades, wins = _run_buy_and_hold(close)
        assert len(equity) == 100
        assert n_trades == 1  # B&H has exactly 1 trade
        assert wins == 1      # uptrend → win

    def test_buy_and_hold_equity_grows_in_uptrend(self):
        from rita.api.experience.rita import _run_buy_and_hold
        close = self._trending_up(n=100)
        equity, _, _ = _run_buy_and_hold(close)
        assert equity[-1] > equity[0], "Buy-and-Hold equity must grow in an uptrend"

    def test_buy_and_hold_flat_market_no_win(self):
        from rita.api.experience.rita import _run_buy_and_hold
        close = self._flat_prices(n=50)
        equity, n_trades, wins = _run_buy_and_hold(close)
        assert n_trades == 1
        # Flat price → final == initial → not profitable → wins == 0
        assert wins == 0

    def test_value_investing_returns_correct_length(self):
        from rita.api.experience.rita import _run_value_investing
        close = self._trending_up(n=60)
        equity, n_trades, wins = _run_value_investing(close)
        assert len(equity) == 60
        assert isinstance(n_trades, int) and n_trades >= 0
        assert isinstance(wins, int) and wins >= 0

    def test_momentum_returns_correct_length(self):
        from rita.api.experience.rita import _run_momentum
        close = self._trending_up(n=60)
        equity, n_trades, wins = _run_momentum(close)
        assert len(equity) == 60

    def test_swing_trading_returns_correct_length(self):
        from rita.api.experience.rita import _run_swing_trading
        close = self._trending_up(n=60)
        equity, n_trades, wins = _run_swing_trading(close)
        assert len(equity) == 60

    def test_support_resistance_returns_correct_length(self):
        from rita.api.experience.rita import _run_support_resistance
        # Must have at least 252 prices for the period window
        close = self._trending_up(n=300)
        equity, n_trades, wins = _run_support_resistance(close)
        assert len(equity) == 300

    def test_wins_never_exceed_n_trades(self):
        """wins <= n_trades must hold for all strategy runners."""
        from rita.api.experience.rita import (
            _run_buy_and_hold,
            _run_value_investing,
            _run_momentum,
            _run_swing_trading,
            _run_support_resistance,
        )
        close = self._trending_up(n=300)
        for runner in (
            _run_buy_and_hold,
            _run_value_investing,
            _run_momentum,
            _run_swing_trading,
            _run_support_resistance,
        ):
            _, n_trades, wins = runner(close)
            assert wins <= n_trades, (
                f"{runner.__name__}: wins({wins}) > n_trades({n_trades})"
            )


# ---------------------------------------------------------------------------
# Class 4 — API-frontend contract check
# ---------------------------------------------------------------------------

class TestStrategyComparisonContractCheck:
    """Verify that every field read by strategy-comparison.js is present in
    the Pydantic schema and returned by the endpoint.

    JS reads (strategy-comparison.js):
        data.instrument                   — not used for rendering but in URL
        data.year                         — not directly rendered by JS
        data.error                        — null-guard + _showError()
        data.dates                        — x-axis labels
        data.strategies[].name            — legend label + _STRATEGY_COLORS key
        data.strategies[].equity          — y-axis data
        data.strategies[].color           — fallback color
        data.summary[].name               — table cell + color lookup
        data.summary[].total_return_pct   — table cell
        data.summary[].sharpe             — table cell
        data.summary[].max_drawdown_pct   — table cell
        data.summary[].n_trades           — table cell
        data.summary[].win_rate_pct       — table cell
        data.summary[].final_value        — table cell
    """

    def test_strategy_comparison_response_schema_fields(self):
        """StrategyComparisonResponse must expose all fields read by JS."""
        from rita.schemas.strategy_comparison import StrategyComparisonResponse

        fields = StrategyComparisonResponse.model_fields
        for field in ("instrument", "year", "dates", "strategies", "summary", "error"):
            assert field in fields, (
                f"StrategyComparisonResponse missing field '{field}'"
            )

    def test_strategy_result_schema_fields(self):
        """StrategyResult must expose name, equity, color."""
        from rita.schemas.strategy_comparison import StrategyResult

        fields = StrategyResult.model_fields
        for field in ("name", "equity", "color"):
            assert field in fields, (
                f"StrategyResult missing field '{field}' (read by JS)"
            )

    def test_strategy_summary_row_schema_fields(self):
        """StrategySummaryRow must expose all 7 metric fields read by JS."""
        from rita.schemas.strategy_comparison import StrategySummaryRow

        fields = StrategySummaryRow.model_fields
        for field in (
            "name", "total_return_pct", "sharpe", "max_drawdown_pct",
            "n_trades", "win_rate_pct", "final_value",
        ):
            assert field in fields, (
                f"StrategySummaryRow missing field '{field}' (read by JS)"
            )

    def test_strategies_is_list_in_response(self):
        """data.strategies is iterated with .map() in JS — must be a JSON array."""
        from rita.main import app
        from rita.database import get_db
        from tests.unit.test_strategy_comparison import _make_ohlcv_df, _clear_cache

        _clear_cache()
        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                from fastapi.testclient import TestClient
                client = TestClient(app, raise_server_exceptions=False)
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert isinstance(body["strategies"], list)
        assert isinstance(body["summary"], list)
        assert isinstance(body["dates"], list)

    def test_summary_total_return_pct_is_float(self):
        """summary[].total_return_pct is called with .toFixed(2) in JS —
        must be a number (float), not a string."""
        from rita.main import app
        from rita.database import get_db
        from tests.unit.test_strategy_comparison import _make_ohlcv_df, _clear_cache

        _clear_cache()
        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                from fastapi.testclient import TestClient
                client = TestClient(app, raise_server_exceptions=False)
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        for row in body["summary"]:
            assert isinstance(row["total_return_pct"], (int, float)), (
                f"summary '{row['name']}' total_return_pct must be numeric"
            )
            assert isinstance(row["sharpe"], (int, float))
            assert isinstance(row["max_drawdown_pct"], (int, float))
            assert isinstance(row["win_rate_pct"], (int, float))
            assert isinstance(row["final_value"], (int, float))

    def test_n_trades_is_integer(self):
        """summary[].n_trades is rendered without .toFixed() in JS — must be int."""
        from rita.main import app
        from rita.database import get_db
        from tests.unit.test_strategy_comparison import _make_ohlcv_df, _clear_cache

        _clear_cache()
        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                from fastapi.testclient import TestClient
                client = TestClient(app, raise_server_exceptions=False)
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        for row in body["summary"]:
            assert isinstance(row["n_trades"], int), (
                f"n_trades must be int, got {type(row['n_trades'])} "
                f"for '{row['name']}'"
            )

    def test_error_field_is_null_or_string(self):
        """data.error is null-guarded in JS — must be null or a string, not
        an unexpected type."""
        from rita.main import app
        from rita.database import get_db
        from tests.unit.test_strategy_comparison import _make_ohlcv_df, _clear_cache

        _clear_cache()
        mock_db = MagicMock()
        _override(app, get_db, mock_db)
        try:
            with patch(
                "rita.core.data_loader.load_instrument_data",
                return_value=_make_ohlcv_df(year=2025),
            ):
                from fastapi.testclient import TestClient
                client = TestClient(app, raise_server_exceptions=False)
                body = client.get(f"{_SC_URL}?instrument=NIFTY&year=2025").json()
        finally:
            app.dependency_overrides.pop(get_db, None)

        err = body.get("error")
        assert err is None or isinstance(err, str), (
            f"error must be null or string, got {type(err)}"
        )
