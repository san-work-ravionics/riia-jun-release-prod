"""Unit tests for the Guided Basket Optimal Allocation feature (F34 Phase 1).

Tests cover:
- Core optimizer logic (optimize_allocation, _solve_allocation)
- Proxy metric computation helpers
- Edge cases: no instruments, single instrument, all negative Sharpe, infeasible
- Endpoint contract via TestClient (200 + 422)
- API-schema field contract verification
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from rita.config import settings
from rita.core.portfolio_optimizer import (
    MAX_ALLOC,
    MAX_INSTRUMENTS,
    MIN_ALLOC,
    _proxy_mdd_from_prices,
    _proxy_sharpe_from_prices,
    _solve_allocation,
    optimize_allocation,
)
from rita.schemas.portfolio_optimizer import AllocationItem, OptimalAllocationResponse

SHARPE_FLOOR = settings.optimizer.sharpe_floor
MDD_CEILING = settings.optimizer.mdd_ceiling


# ---------------------------------------------------------------------------
# Helpers — synthetic instrument data
# ---------------------------------------------------------------------------

def _make_instrument(
    inst_id: str,
    name: str,
    sharpe: float,
    mdd_pct: float,
    metric_source: str = "model",
) -> dict:
    """Build an instrument metrics dict matching _get_instrument_metrics output."""
    return {
        "instrument_id": inst_id,
        "instrument_name": name,
        "ticker": inst_id,
        "sharpe": sharpe,
        "mdd_pct": mdd_pct,
        "metric_source": metric_source,
    }


def _make_db_instrument(
    inst_id: str, name: str, yf_ticker: str | None = None, is_available: bool = True
) -> MagicMock:
    """Build a mock InstrumentModel row."""
    inst = MagicMock()
    inst.instrument_id = inst_id
    inst.name = name
    inst.yf_ticker = yf_ticker or inst_id
    inst.is_available = is_available
    return inst


def _make_instruments_input(count: int, base_sharpe: float = 2.0, base_mdd: float = -5.0):
    """Build a list of instrument input dicts for optimize_allocation."""
    return [
        {
            "instrument_id": f"INST{i}",
            "name": f"Instrument {i}",
            "ticker": f"INST{i}",
            "yf_ticker": f"INST{i}",
        }
        for i in range(count)
    ]


def _make_metrics_list(count: int, base_sharpe: float = 2.0, base_mdd: float = -5.0):
    """Build a list of instrument metrics dicts for _solve_allocation."""
    return [
        _make_instrument(
            f"INST{i}",
            f"Instrument {i}",
            sharpe=base_sharpe - i * 0.1,
            mdd_pct=base_mdd - i * 0.5,
        )
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Test: happy path — multiple instruments with good Sharpe/MDD
# ---------------------------------------------------------------------------

class TestHappyPath:
    """Multiple instruments with good Sharpe and low MDD should yield OPTIMAL."""

    def test_happy_path(self):
        """Allocations sum to 100, each in [MIN_ALLOC, MAX_ALLOC], solver_status OPTIMAL."""
        instruments = _make_metrics_list(4, base_sharpe=2.5, base_mdd=-4.0)

        status, allocations = _solve_allocation(instruments, SHARPE_FLOOR, MDD_CEILING)

        assert status == "OPTIMAL"
        assert len(allocations) == 4

        total = sum(alloc_pct for _, alloc_pct in allocations)
        assert total == 100

        for _, alloc_pct in allocations:
            assert MIN_ALLOC <= alloc_pct <= MAX_ALLOC


# ---------------------------------------------------------------------------
# Test: single instrument
# ---------------------------------------------------------------------------

class TestSingleInstrument:
    """Single qualifying instrument skips the solver."""

    @patch("rita.core.portfolio_optimizer._get_instrument_metrics")
    @patch("rita.core.portfolio_optimizer.INVESTMENT_HORIZONS", {
        "short_term": {"lookback_td": 253},
    })
    def test_single_instrument(self, mock_metrics):
        metrics = _make_instrument("NIFTY", "Nifty 50", sharpe=2.5, mdd_pct=-3.0)
        mock_metrics.return_value = metrics

        result = optimize_allocation(
            instruments=[{"instrument_id": "NIFTY", "name": "Nifty 50", "ticker": "NIFTY", "yf_ticker": "^NSEI"}],
            horizon="short_term",
        )

        assert result.solver_status == "SINGLE_INSTRUMENT"
        assert result.instrument_count == 1
        assert len(result.allocations) == 1
        assert result.allocations[0].allocation_pct == 100
        assert result.allocations[0].instrument_name == "Nifty 50"


# ---------------------------------------------------------------------------
# Test: no instruments
# ---------------------------------------------------------------------------

class TestNoInstruments:
    """Zero instruments after metric gathering."""

    @patch("rita.core.portfolio_optimizer._get_instrument_metrics")
    @patch("rita.core.portfolio_optimizer.INVESTMENT_HORIZONS", {
        "short_term": {"lookback_td": 253},
    })
    def test_no_instruments(self, mock_metrics):
        mock_metrics.return_value = None  # all instruments fail metric gathering

        result = optimize_allocation(
            instruments=[{"instrument_id": "X", "name": "X", "ticker": "X", "yf_ticker": "X"}],
            horizon="short_term",
        )

        assert result.solver_status == "NO_INSTRUMENTS"
        assert result.instrument_count == 0
        assert result.allocations == []

    @patch("rita.core.portfolio_optimizer.INVESTMENT_HORIZONS", {
        "short_term": {"lookback_td": 253},
    })
    def test_empty_instruments_list(self):
        result = optimize_allocation(instruments=[], horizon="short_term")

        assert result.solver_status == "NO_INSTRUMENTS"
        assert result.instrument_count == 0
        assert result.allocations == []


# ---------------------------------------------------------------------------
# Test: all negative Sharpe -> INFEASIBLE
# ---------------------------------------------------------------------------

class TestAllNegativeSharpe:
    """All instruments with negative Sharpe cannot meet the Sharpe floor."""

    def test_all_negative_sharpe(self):
        instruments = [
            _make_instrument(f"BAD{i}", f"Bad {i}", sharpe=-1.0 - i, mdd_pct=-3.0)
            for i in range(3)
        ]

        status, allocations = _solve_allocation(instruments, SHARPE_FLOOR, MDD_CEILING)

        assert status == "INFEASIBLE"
        assert allocations == []


# ---------------------------------------------------------------------------
# Test: proxy metrics (no training history)
# ---------------------------------------------------------------------------

class TestProxyMetrics:
    """All instruments using proxy metrics from price data."""

    @patch("rita.core.portfolio_optimizer._get_instrument_metrics")
    @patch("rita.core.portfolio_optimizer.INVESTMENT_HORIZONS", {
        "short_term": {"lookback_td": 253},
    })
    def test_proxy_metrics(self, mock_metrics):
        proxy_instruments = [
            _make_instrument(f"P{i}", f"Proxy {i}", sharpe=2.0 + i * 0.2, mdd_pct=-4.0, metric_source="proxy")
            for i in range(3)
        ]
        mock_metrics.side_effect = proxy_instruments

        inputs = [
            {"instrument_id": f"P{i}", "name": f"Proxy {i}", "ticker": f"P{i}", "yf_ticker": f"P{i}"}
            for i in range(3)
        ]

        result = optimize_allocation(instruments=inputs, horizon="short_term")

        assert result.solver_status in ("OPTIMAL", "FEASIBLE", "SINGLE_INSTRUMENT")
        for alloc in result.allocations:
            assert alloc.metric_source == "proxy"


# ---------------------------------------------------------------------------
# Test: allocations sum to 100 (budget constraint)
# ---------------------------------------------------------------------------

class TestAllocationsSumTo100:
    """Budget constraint: allocations must sum to exactly 100 for various instrument counts."""

    @pytest.mark.parametrize("count", [2, 3, 4, 5, 6, 7])
    def test_allocations_sum_to_100(self, count):
        instruments = _make_metrics_list(count, base_sharpe=2.5, base_mdd=-4.0)

        status, allocations = _solve_allocation(instruments, SHARPE_FLOOR, MDD_CEILING)

        if status in ("OPTIMAL", "FEASIBLE"):
            total = sum(alloc_pct for _, alloc_pct in allocations)
            assert total == 100, f"Expected sum=100, got {total} for {count} instruments"


# ---------------------------------------------------------------------------
# Test: MDD constraint
# ---------------------------------------------------------------------------

class TestMddConstraint:
    """Weighted portfolio MDD must not exceed the MDD ceiling."""

    def test_mdd_constraint(self):
        """Instruments with varying MDD — solver should keep weighted MDD <= ceiling."""
        instruments = [
            _make_instrument("A", "A", sharpe=3.0, mdd_pct=-8.0),
            _make_instrument("B", "B", sharpe=2.5, mdd_pct=-12.0),
            _make_instrument("C", "C", sharpe=2.0, mdd_pct=-5.0),
            _make_instrument("D", "D", sharpe=1.8, mdd_pct=-3.0),
        ]

        status, allocations = _solve_allocation(instruments, SHARPE_FLOOR, MDD_CEILING)

        if status in ("OPTIMAL", "FEASIBLE"):
            weighted_abs_mdd = sum(
                (alloc_pct / 100.0) * abs(instruments[idx]["mdd_pct"])
                for idx, alloc_pct in allocations
            )
            assert weighted_abs_mdd <= MDD_CEILING + 0.01, (
                f"Weighted |MDD| {weighted_abs_mdd:.2f}% exceeds ceiling {MDD_CEILING}%"
            )

    def test_high_mdd_infeasible(self):
        """All instruments with very high MDD and needing Sharpe floor -> likely INFEASIBLE."""
        instruments = [
            _make_instrument("X", "X", sharpe=1.5, mdd_pct=-25.0),
            _make_instrument("Y", "Y", sharpe=1.2, mdd_pct=-30.0),
        ]

        # Use production thresholds (1.0/10.0) to ensure this remains infeasible
        status, allocations = _solve_allocation(instruments, 1.0, 10.0)

        assert status == "INFEASIBLE"
        assert allocations == []


# ---------------------------------------------------------------------------
# Test: endpoint 200 via TestClient
# ---------------------------------------------------------------------------

class TestEndpoint200:
    """GET /api/v1/experience/rita/optimal-allocation with valid horizon returns 200."""

    @patch("rita.api.experience.optimal_allocation.optimize_allocation")
    @patch("rita.api.experience.optimal_allocation.InstrumentRepository")
    def test_endpoint_200(self, mock_repo_cls, mock_optimize, client):
        """Valid request -> 200 with correct response structure."""
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = [
            _make_db_instrument("NIFTY", "Nifty 50", "^NSEI"),
        ]
        mock_repo_cls.return_value = mock_repo

        mock_optimize.return_value = OptimalAllocationResponse(
            horizon="short_term",
            instrument_count=1,
            solver_status="SINGLE_INSTRUMENT",
            estimated_sharpe=2.5,
            estimated_mdd_pct=-3.0,
            allocations=[
                AllocationItem(
                    instrument_name="Nifty 50",
                    ticker="^NSEI",
                    allocation_pct=100,
                    sharpe=2.5,
                    mdd_pct=-3.0,
                    metric_source="model",
                )
            ],
        )

        resp = client.get("/api/v1/experience/rita/optimal-allocation?horizon=short_term")

        assert resp.status_code == 200
        body = resp.json()
        assert body["horizon"] == "short_term"
        assert body["solver_status"] == "SINGLE_INSTRUMENT"
        assert body["instrument_count"] == 1
        assert len(body["allocations"]) == 1
        assert body["allocations"][0]["instrument_name"] == "Nifty 50"
        assert body["allocations"][0]["allocation_pct"] == 100


# ---------------------------------------------------------------------------
# Test: endpoint 422 via TestClient (invalid horizon)
# ---------------------------------------------------------------------------

class TestEndpoint422:
    """GET /api/v1/experience/rita/optimal-allocation with invalid horizon returns 422."""

    def test_endpoint_422_invalid_horizon(self, client):
        resp = client.get("/api/v1/experience/rita/optimal-allocation?horizon=invalid")
        assert resp.status_code == 422

    def test_endpoint_422_missing_horizon(self, client):
        resp = client.get("/api/v1/experience/rita/optimal-allocation")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test: proxy metric helpers
# ---------------------------------------------------------------------------

class TestProxyHelpers:
    """Unit tests for _proxy_sharpe_from_prices and _proxy_mdd_from_prices."""

    def test_proxy_sharpe_positive_trend(self):
        """Steadily rising prices should yield a positive Sharpe."""
        prices = [100 + i * 0.5 for i in range(60)]
        df = pd.DataFrame({"Close": prices})
        sharpe = _proxy_sharpe_from_prices(df, lookback_td=50)
        assert sharpe > 0

    def test_proxy_sharpe_insufficient_data(self):
        """Fewer than 10 daily returns should yield 0.0."""
        df = pd.DataFrame({"Close": [100, 101, 102]})
        sharpe = _proxy_sharpe_from_prices(df, lookback_td=50)
        assert sharpe == 0.0

    def test_proxy_mdd_flat(self):
        """Flat prices have zero drawdown."""
        df = pd.DataFrame({"Close": [100.0] * 30})
        mdd = _proxy_mdd_from_prices(df, lookback_td=25)
        assert mdd == 0.0

    def test_proxy_mdd_drawdown(self):
        """A peak followed by a drop should produce negative MDD."""
        prices = list(range(100, 120)) + list(range(120, 100, -1))
        df = pd.DataFrame({"Close": [float(p) for p in prices]})
        mdd = _proxy_mdd_from_prices(df, lookback_td=40)
        assert mdd < 0


# ---------------------------------------------------------------------------
# Test: optimize_allocation integration (with mocked _get_instrument_metrics)
# ---------------------------------------------------------------------------

class TestOptimizeAllocation:
    """Integration-style tests for the optimize_allocation entry point."""

    @patch("rita.core.portfolio_optimizer._get_instrument_metrics")
    @patch("rita.core.portfolio_optimizer.INVESTMENT_HORIZONS", {
        "short_term": {"lookback_td": 253},
    })
    def test_invalid_horizon_returns_error(self, mock_metrics):
        """An unrecognized horizon returns solver_status ERROR."""
        result = optimize_allocation(instruments=[], horizon="ultra_term")
        assert result.solver_status == "ERROR"

    @patch("rita.core.portfolio_optimizer._get_instrument_metrics")
    @patch("rita.core.portfolio_optimizer.INVESTMENT_HORIZONS", {
        "short_term": {"lookback_td": 253},
    })
    def test_max_instruments_cap(self, mock_metrics):
        """More than MAX_INSTRUMENTS qualifying -> only top 7 by Sharpe used."""
        metrics = [
            _make_instrument(f"I{i}", f"Inst {i}", sharpe=3.0 - i * 0.1, mdd_pct=-3.0)
            for i in range(10)
        ]
        mock_metrics.side_effect = metrics

        inputs = [
            {"instrument_id": f"I{i}", "name": f"Inst {i}", "ticker": f"I{i}", "yf_ticker": f"I{i}"}
            for i in range(10)
        ]

        result = optimize_allocation(instruments=inputs, horizon="short_term")

        # Should have at most MAX_INSTRUMENTS (7) allocations
        assert result.instrument_count <= MAX_INSTRUMENTS

    @patch("rita.core.portfolio_optimizer._get_instrument_metrics")
    @patch("rita.core.portfolio_optimizer.INVESTMENT_HORIZONS", {
        "short_term": {"lookback_td": 253},
    })
    def test_optimal_response_fields(self, mock_metrics):
        """Response contains all required schema fields with correct types."""
        metrics = [
            _make_instrument(f"I{i}", f"Inst {i}", sharpe=2.5 - i * 0.1, mdd_pct=-4.0)
            for i in range(4)
        ]
        mock_metrics.side_effect = metrics

        inputs = [
            {"instrument_id": f"I{i}", "name": f"Inst {i}", "ticker": f"I{i}", "yf_ticker": f"I{i}"}
            for i in range(4)
        ]

        result = optimize_allocation(instruments=inputs, horizon="short_term")

        # Verify top-level fields exist and have correct types
        assert isinstance(result.horizon, str)
        assert isinstance(result.instrument_count, int)
        assert isinstance(result.solver_status, str)
        assert isinstance(result.estimated_sharpe, float)
        assert isinstance(result.estimated_mdd_pct, float)
        assert isinstance(result.allocations, list)

        if result.allocations:
            alloc = result.allocations[0]
            assert isinstance(alloc.instrument_name, str)
            assert isinstance(alloc.ticker, str)
            assert isinstance(alloc.allocation_pct, int)
            assert isinstance(alloc.sharpe, float)
            assert isinstance(alloc.mdd_pct, float)
            assert isinstance(alloc.metric_source, str)
