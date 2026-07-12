"""Unit tests for the F34 Optimal Allocation endpoint — Phase 2 QA.

Verifies the GET /api/v1/experience/rita/optimal-allocation endpoint returns
the correct response shape that the frontend JS (portfolio-builder.js) expects.

Tests cover:
- Happy path: OPTIMAL solver_status with valid allocations
- Edge case: INFEASIBLE solver_status
- Edge case: NO_INSTRUMENTS solver_status
- Edge case: SINGLE_INSTRUMENT solver_status
- Edge case: ERROR fallback (handler exception)
- API-frontend contract verification (schema fields vs JS field accesses)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rita.schemas.portfolio_optimizer import AllocationItem, OptimalAllocationResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_instrument(inst_id, name, yf_ticker=None, is_available=True):
    """Build a mock InstrumentModel row."""
    inst = MagicMock()
    inst.instrument_id = inst_id
    inst.name = name
    inst.yf_ticker = yf_ticker or inst_id
    inst.is_available = is_available
    return inst


def _optimal_response():
    """Build a happy-path OPTIMAL response with 3 instruments."""
    return OptimalAllocationResponse(
        horizon="short_term",
        instrument_count=3,
        solver_status="OPTIMAL",
        estimated_sharpe=1.85,
        estimated_mdd_pct=-6.2,
        allocations=[
            AllocationItem(
                instrument_name="Reliance Industries",
                ticker="RELIANCE",
                allocation_pct=40,
                sharpe=2.1,
                mdd_pct=-5.0,
                metric_source="model",
            ),
            AllocationItem(
                instrument_name="Tata Motors",
                ticker="TATAMOTOR",
                allocation_pct=35,
                sharpe=1.8,
                mdd_pct=-7.0,
                metric_source="proxy",
            ),
            AllocationItem(
                instrument_name="Nvidia",
                ticker="NVIDIA",
                allocation_pct=25,
                sharpe=1.6,
                mdd_pct=-6.5,
                metric_source="proxy",
            ),
        ],
    )


def _infeasible_response():
    """Build an INFEASIBLE response (solver cannot find valid allocation)."""
    return OptimalAllocationResponse(
        horizon="short_term",
        instrument_count=3,
        solver_status="INFEASIBLE",
        estimated_sharpe=0.0,
        estimated_mdd_pct=0.0,
        allocations=[],
    )


def _no_instruments_response():
    """Build a NO_INSTRUMENTS response (no instruments available)."""
    return OptimalAllocationResponse(
        horizon="long_term",
        instrument_count=0,
        solver_status="NO_INSTRUMENTS",
        estimated_sharpe=0.0,
        estimated_mdd_pct=0.0,
        allocations=[],
    )


def _single_instrument_response():
    """Build a SINGLE_INSTRUMENT response."""
    return OptimalAllocationResponse(
        horizon="medium_term",
        instrument_count=1,
        solver_status="SINGLE_INSTRUMENT",
        estimated_sharpe=2.5,
        estimated_mdd_pct=-3.0,
        allocations=[
            AllocationItem(
                instrument_name="Nifty 50",
                ticker="NIFTY",
                allocation_pct=100,
                sharpe=2.5,
                mdd_pct=-3.0,
                metric_source="model",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Test: happy path — OPTIMAL with valid allocations
# ---------------------------------------------------------------------------

class TestOptimalHappyPath:
    """Endpoint returns OPTIMAL solver_status with valid allocations."""

    @patch("rita.api.experience.optimal_allocation.optimize_allocation")
    @patch("rita.api.experience.optimal_allocation.InstrumentRepository")
    def test_optimal_response_shape(self, mock_repo_cls, mock_optimize, client):
        """200 response has all top-level and per-allocation fields the JS expects."""
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = [
            _make_db_instrument("RELIANCE", "Reliance Industries", "RELIANCE.NS"),
            _make_db_instrument("TATAMOTOR", "Tata Motors", "TATAMOTORS.NS"),
            _make_db_instrument("NVIDIA", "Nvidia", "NVDA"),
        ]
        mock_repo_cls.return_value = mock_repo

        mock_optimize.return_value = _optimal_response()

        resp = client.get("/api/v1/experience/rita/optimal-allocation?horizon=short_term")

        assert resp.status_code == 200
        body = resp.json()

        # Top-level fields
        assert body["horizon"] == "short_term"
        assert body["instrument_count"] == 3
        assert body["solver_status"] == "OPTIMAL"
        assert isinstance(body["estimated_sharpe"], float)
        assert isinstance(body["estimated_mdd_pct"], float)
        assert isinstance(body["allocations"], list)
        assert len(body["allocations"]) == 3

    @patch("rita.api.experience.optimal_allocation.optimize_allocation")
    @patch("rita.api.experience.optimal_allocation.InstrumentRepository")
    def test_allocation_item_fields(self, mock_repo_cls, mock_optimize, client):
        """Each allocation item has all 6 fields the JS reads."""
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = [
            _make_db_instrument("RELIANCE", "Reliance Industries"),
        ]
        mock_repo_cls.return_value = mock_repo
        mock_optimize.return_value = _optimal_response()

        resp = client.get("/api/v1/experience/rita/optimal-allocation?horizon=short_term")
        body = resp.json()

        for alloc in body["allocations"]:
            assert "instrument_name" in alloc
            assert "ticker" in alloc
            assert "allocation_pct" in alloc
            assert "sharpe" in alloc
            assert "mdd_pct" in alloc
            assert "metric_source" in alloc

            assert isinstance(alloc["instrument_name"], str)
            assert isinstance(alloc["ticker"], str)
            assert isinstance(alloc["allocation_pct"], int)
            assert isinstance(alloc["sharpe"], (int, float))
            assert isinstance(alloc["mdd_pct"], (int, float))
            assert alloc["metric_source"] in ("model", "proxy")

    @patch("rita.api.experience.optimal_allocation.optimize_allocation")
    @patch("rita.api.experience.optimal_allocation.InstrumentRepository")
    def test_allocations_sum_to_100(self, mock_repo_cls, mock_optimize, client):
        """Optimal allocations sum to exactly 100%."""
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = [_make_db_instrument("X", "X")]
        mock_repo_cls.return_value = mock_repo
        mock_optimize.return_value = _optimal_response()

        resp = client.get("/api/v1/experience/rita/optimal-allocation?horizon=short_term")
        body = resp.json()

        total = sum(a["allocation_pct"] for a in body["allocations"])
        assert total == 100


# ---------------------------------------------------------------------------
# Test: INFEASIBLE solver_status
# ---------------------------------------------------------------------------

class TestInfeasibleStatus:
    """Endpoint returns INFEASIBLE when solver cannot find a valid allocation."""

    @patch("rita.api.experience.optimal_allocation.optimize_allocation")
    @patch("rita.api.experience.optimal_allocation.InstrumentRepository")
    def test_infeasible_response(self, mock_repo_cls, mock_optimize, client):
        """INFEASIBLE: valid 200 response with empty allocations array."""
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = [
            _make_db_instrument("BAD1", "Bad 1"),
            _make_db_instrument("BAD2", "Bad 2"),
        ]
        mock_repo_cls.return_value = mock_repo
        mock_optimize.return_value = _infeasible_response()

        resp = client.get("/api/v1/experience/rita/optimal-allocation?horizon=short_term")

        assert resp.status_code == 200
        body = resp.json()
        assert body["solver_status"] == "INFEASIBLE"
        assert body["allocations"] == []
        assert body["instrument_count"] == 3  # from the mock
        assert isinstance(body["estimated_sharpe"], float)
        assert isinstance(body["estimated_mdd_pct"], float)


# ---------------------------------------------------------------------------
# Test: NO_INSTRUMENTS solver_status
# ---------------------------------------------------------------------------

class TestNoInstrumentsStatus:
    """Endpoint returns NO_INSTRUMENTS when no instruments are available."""

    @patch("rita.api.experience.optimal_allocation.optimize_allocation")
    @patch("rita.api.experience.optimal_allocation.InstrumentRepository")
    def test_no_instruments_response(self, mock_repo_cls, mock_optimize, client):
        """NO_INSTRUMENTS: valid 200 with zero instrument_count and empty allocations."""
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = []
        mock_repo_cls.return_value = mock_repo
        mock_optimize.return_value = _no_instruments_response()

        resp = client.get("/api/v1/experience/rita/optimal-allocation?horizon=long_term")

        assert resp.status_code == 200
        body = resp.json()
        assert body["solver_status"] == "NO_INSTRUMENTS"
        assert body["instrument_count"] == 0
        assert body["allocations"] == []
        assert body["estimated_sharpe"] == 0.0
        assert body["estimated_mdd_pct"] == 0.0

    @patch("rita.api.experience.optimal_allocation.optimize_allocation")
    @patch("rita.api.experience.optimal_allocation.InstrumentRepository")
    def test_no_instruments_all_unavailable(self, mock_repo_cls, mock_optimize, client):
        """All instruments have is_available=False -> filtered out -> NO_INSTRUMENTS."""
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = [
            _make_db_instrument("X", "X", is_available=False),
            _make_db_instrument("Y", "Y", is_available=False),
        ]
        mock_repo_cls.return_value = mock_repo
        mock_optimize.return_value = _no_instruments_response()

        resp = client.get("/api/v1/experience/rita/optimal-allocation?horizon=long_term")

        assert resp.status_code == 200
        body = resp.json()
        assert body["solver_status"] == "NO_INSTRUMENTS"
        # Verify optimize_allocation was called with empty instruments list
        args = mock_optimize.call_args
        assert len(args.kwargs.get("instruments", args[1] if len(args) > 1 else args[0][0])) == 0


# ---------------------------------------------------------------------------
# Test: SINGLE_INSTRUMENT solver_status
# ---------------------------------------------------------------------------

class TestSingleInstrumentStatus:
    """Endpoint returns SINGLE_INSTRUMENT when only one instrument qualifies."""

    @patch("rita.api.experience.optimal_allocation.optimize_allocation")
    @patch("rita.api.experience.optimal_allocation.InstrumentRepository")
    def test_single_instrument_response(self, mock_repo_cls, mock_optimize, client):
        """SINGLE_INSTRUMENT: valid 200 with one allocation at 100%."""
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = [
            _make_db_instrument("NIFTY", "Nifty 50", "^NSEI"),
        ]
        mock_repo_cls.return_value = mock_repo
        mock_optimize.return_value = _single_instrument_response()

        resp = client.get(
            "/api/v1/experience/rita/optimal-allocation?horizon=medium_term"
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["solver_status"] == "SINGLE_INSTRUMENT"
        assert body["instrument_count"] == 1
        assert len(body["allocations"]) == 1
        assert body["allocations"][0]["allocation_pct"] == 100
        assert body["allocations"][0]["ticker"] == "NIFTY"


# ---------------------------------------------------------------------------
# Test: ERROR fallback (handler catches exception)
# ---------------------------------------------------------------------------

class TestErrorFallback:
    """Endpoint returns ERROR when an unhandled exception occurs in the handler."""

    @patch("rita.api.experience.optimal_allocation.optimize_allocation")
    @patch("rita.api.experience.optimal_allocation.InstrumentRepository")
    def test_error_on_exception(self, mock_repo_cls, mock_optimize, client):
        """Exception in optimize_allocation -> 200 with solver_status ERROR."""
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = [_make_db_instrument("X", "X")]
        mock_repo_cls.return_value = mock_repo
        mock_optimize.side_effect = RuntimeError("solver crashed")

        resp = client.get("/api/v1/experience/rita/optimal-allocation?horizon=short_term")

        assert resp.status_code == 200
        body = resp.json()
        assert body["solver_status"] == "ERROR"
        assert body["instrument_count"] == 0
        assert body["allocations"] == []

    @patch("rita.api.experience.optimal_allocation.InstrumentRepository")
    def test_error_on_repo_exception(self, mock_repo_cls, client):
        """Exception in InstrumentRepository -> 200 with solver_status ERROR."""
        mock_repo_cls.side_effect = RuntimeError("DB connection failed")

        resp = client.get("/api/v1/experience/rita/optimal-allocation?horizon=short_term")

        assert resp.status_code == 200
        body = resp.json()
        assert body["solver_status"] == "ERROR"
        assert body["allocations"] == []


# ---------------------------------------------------------------------------
# Test: API-Frontend contract — every field the JS reads must exist in schema
# ---------------------------------------------------------------------------

class TestApiFrontendContract:
    """Verify every field portfolio-builder.js reads is present in the response."""

    @patch("rita.api.experience.optimal_allocation.optimize_allocation")
    @patch("rita.api.experience.optimal_allocation.InstrumentRepository")
    def test_js_top_level_field_access(self, mock_repo_cls, mock_optimize, client):
        """JS reads: solver_status, estimated_sharpe, estimated_mdd_pct, allocations."""
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = [_make_db_instrument("X", "X")]
        mock_repo_cls.return_value = mock_repo
        mock_optimize.return_value = _optimal_response()

        resp = client.get("/api/v1/experience/rita/optimal-allocation?horizon=short_term")
        body = resp.json()

        # Fields the JS reads at the top level
        js_top_level_fields = [
            "solver_status",
            "estimated_sharpe",
            "estimated_mdd_pct",
            "allocations",
        ]
        for field in js_top_level_fields:
            assert field in body, f"JS reads '{field}' but it is missing from the response"

    @patch("rita.api.experience.optimal_allocation.optimize_allocation")
    @patch("rita.api.experience.optimal_allocation.InstrumentRepository")
    def test_js_allocation_item_field_access(self, mock_repo_cls, mock_optimize, client):
        """JS reads: ticker, allocation_pct, sharpe, mdd_pct, metric_source per allocation."""
        mock_repo = MagicMock()
        mock_repo.read_all.return_value = [_make_db_instrument("X", "X")]
        mock_repo_cls.return_value = mock_repo
        mock_optimize.return_value = _optimal_response()

        resp = client.get("/api/v1/experience/rita/optimal-allocation?horizon=short_term")
        body = resp.json()

        # Fields the JS reads per allocation item
        js_allocation_fields = [
            "ticker",
            "allocation_pct",
            "sharpe",
            "mdd_pct",
            "metric_source",
        ]
        for alloc in body["allocations"]:
            for field in js_allocation_fields:
                assert field in alloc, (
                    f"JS reads 'allocations[].{field}' but it is missing from allocation item"
                )

    def test_schema_field_names_match_js(self):
        """Verify Pydantic model field names exactly match what JS code accesses.

        This is a static contract check — no HTTP call needed.
        """
        # OptimalAllocationResponse top-level fields
        response_fields = set(OptimalAllocationResponse.model_fields.keys())
        js_top_reads = {"solver_status", "estimated_sharpe", "estimated_mdd_pct", "allocations"}
        missing = js_top_reads - response_fields
        assert not missing, f"JS reads fields missing from schema: {missing}"

        # AllocationItem fields
        item_fields = set(AllocationItem.model_fields.keys())
        js_item_reads = {"ticker", "allocation_pct", "sharpe", "mdd_pct", "metric_source"}
        missing_item = js_item_reads - item_fields
        assert not missing_item, f"JS reads allocation fields missing from schema: {missing_item}"

    def test_allocation_pct_is_integer(self):
        """JS uses allocation_pct directly as a number — verify it is int, not float."""
        item = AllocationItem(
            instrument_name="Test",
            ticker="TEST",
            allocation_pct=40,
            sharpe=1.5,
            mdd_pct=-5.0,
            metric_source="proxy",
        )
        assert isinstance(item.allocation_pct, int)
        # Also verify JSON serialization preserves int type
        json_data = item.model_dump()
        assert isinstance(json_data["allocation_pct"], int)
