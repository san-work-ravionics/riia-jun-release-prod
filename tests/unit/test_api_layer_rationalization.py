"""Unit tests for API Layer Rationalization Run A endpoints.

Covers:
- GET /api/v1/experience/rita/backtest-daily       (happy path + empty runs edge case)
- GET /api/v1/experience/rita/risk-timeline        (happy path + instrument casing edge case)
- GET /api/v1/experience/rita/training-history     (happy path + None backtest_mdd edge case)
- POST /api/v1/portfolio/adjust-position-action    (happy path + empty date edge case)

All endpoints are tested via FastAPI TestClient with DB dependency overridden
using in-memory SQLite (from conftest db_session fixture) or direct function-
level mocks where repo calls need to be controlled precisely.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Shared test data constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 17, 10, 0, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 5, 17)


# ---------------------------------------------------------------------------
# Helper: build mock BacktestRun ORM-like object
# ---------------------------------------------------------------------------

def _mk_run(run_id: str = "bt-001", status: str = "complete", instrument: str = "NIFTY"):
    r = MagicMock()
    r.run_id = run_id
    r.status = status
    r.instrument = instrument
    r.ended_at = _NOW
    r.recorded_at = _NOW
    return r


def _mk_result(run_id: str = "bt-001", date_val: date = date(2026, 1, 1),
               portfolio_value: float = 1.05, benchmark_value: float = 1.02,
               allocation: float = 0.8, close_price: float = 22500.0):
    r = MagicMock()
    r.run_id = run_id
    r.date = date_val
    r.portfolio_value = portfolio_value
    r.benchmark_value = benchmark_value
    r.allocation = allocation
    r.close_price = close_price
    return r


def _mk_training_run(run_id: str = "tr-001", instrument: str = "NIFTY",
                     status: str = "complete",
                     backtest_sharpe: float | None = 1.5,
                     backtest_mdd: float | None = -0.05,
                     backtest_return: float | None = 0.12):
    r = MagicMock()
    r.run_id = run_id
    r.instrument = instrument
    r.status = status
    r.recorded_at = _NOW
    r.model_version = "v1.0"
    r.algorithm = "DoubleDQN"
    r.timesteps = 200000
    r.train_sharpe = 1.2
    r.train_mdd = -0.04
    r.train_return = 0.10
    r.train_trades = 40
    r.val_sharpe = 1.3
    r.val_mdd = -0.03
    r.val_return = 0.11
    r.val_cagr = 0.11
    r.val_trades = 20
    r.backtest_sharpe = backtest_sharpe
    r.backtest_mdd = backtest_mdd
    r.backtest_return = backtest_return
    r.backtest_trades = 15
    return r


# ---------------------------------------------------------------------------
# Import app once (conftest already patches pandas.read_csv at import time)
# ---------------------------------------------------------------------------

from rita.database import get_db  # noqa: E402
from rita.main import app  # noqa: E402


def _client_with_db(db_override):
    """Return a TestClient with get_db overridden to yield db_override."""
    app.dependency_overrides[get_db] = lambda: db_override
    client = TestClient(app)
    return client


def _cleanup():
    app.dependency_overrides.pop(get_db, None)


# ===========================================================================
# GET /api/v1/experience/rita/backtest-daily
# ===========================================================================

class TestExperienceBacktestDaily:
    """Tests for the experience-tier backtest-daily endpoint."""

    def test_happy_path_returns_list_with_correct_fields(self, db_session):
        """Happy path: completed runs + results → list of dicts with correct fields."""
        mock_run = _mk_run()
        mock_result_1 = _mk_result(date_val=date(2026, 1, 1))
        mock_result_2 = _mk_result(date_val=date(2026, 1, 2), portfolio_value=1.06)

        with patch(
            "rita.repositories.backtest.BacktestRunsRepository.read_all",
            return_value=[mock_run],
        ), patch(
            "rita.repositories.backtest.BacktestResultsRepository.read_all",
            return_value=[mock_result_1, mock_result_2],
        ), patch(
            "rita.repositories.config_overrides.ConfigOverridesRepository.find_by_id",
            return_value=None,
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/backtest-daily")
            finally:
                _cleanup()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

        first = data[0]
        assert "date" in first
        assert "portfolio_value" in first
        assert "benchmark_value" in first
        assert "allocation" in first
        assert "close_price" in first

    def test_no_completed_runs_returns_empty_list(self, db_session):
        """Edge case: no completed runs → returns [] without exception."""
        with patch(
            "rita.repositories.backtest.BacktestRunsRepository.read_all",
            return_value=[],
        ), patch(
            "rita.repositories.config_overrides.ConfigOverridesRepository.find_by_id",
            return_value=None,
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/backtest-daily")
            finally:
                _cleanup()

        assert resp.status_code == 200
        assert resp.json() == []

    def test_only_non_complete_runs_returns_empty_list(self, db_session):
        """Edge case: runs exist but status is 'pending' → filtered out → []."""
        mock_run = _mk_run(status="pending")

        with patch(
            "rita.repositories.backtest.BacktestRunsRepository.read_all",
            return_value=[mock_run],
        ), patch(
            "rita.repositories.config_overrides.ConfigOverridesRepository.find_by_id",
            return_value=None,
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/backtest-daily")
            finally:
                _cleanup()

        assert resp.status_code == 200
        assert resp.json() == []

    def test_response_field_values_match_repo_data(self, db_session):
        """Verify field values in response exactly match the mock result data."""
        mock_run = _mk_run()
        mock_result = _mk_result(
            date_val=date(2026, 3, 15),
            portfolio_value=1.08,
            benchmark_value=1.04,
            allocation=0.75,
            close_price=23100.0,
        )

        with patch(
            "rita.repositories.backtest.BacktestRunsRepository.read_all",
            return_value=[mock_run],
        ), patch(
            "rita.repositories.backtest.BacktestResultsRepository.read_all",
            return_value=[mock_result],
        ), patch(
            "rita.repositories.config_overrides.ConfigOverridesRepository.find_by_id",
            return_value=None,
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/backtest-daily")
            finally:
                _cleanup()

        assert resp.status_code == 200
        row = resp.json()[0]
        assert row["date"] == "2026-03-15"
        assert row["portfolio_value"] == pytest.approx(1.08)
        assert row["benchmark_value"] == pytest.approx(1.04)
        assert row["allocation"] == pytest.approx(0.75)
        assert row["close_price"] == pytest.approx(23100.0)


# ===========================================================================
# GET /api/v1/experience/rita/risk-timeline
# ===========================================================================

class TestExperienceRiskTimeline:
    """Tests for the experience-tier risk-timeline endpoint."""

    def _two_results(self):
        r1 = _mk_result(date_val=date(2026, 1, 1), portfolio_value=1.0, benchmark_value=1.0)
        r2 = _mk_result(date_val=date(2026, 1, 2), portfolio_value=1.05, benchmark_value=1.02)
        return [r1, r2]

    def test_happy_path_returns_list_with_all_required_fields(self, db_session):
        """Happy path: returns list with all 14 required fields per row."""
        required_fields = {
            "date", "portfolio_value", "portfolio_value_norm", "benchmark_value",
            "allocation", "close_price", "current_drawdown_pct", "drawdown_budget_pct",
            "rolling_vol_20d", "market_var_95", "portfolio_var_95",
            "regime", "trend_score", "phase", "run_id",
        }
        with patch(
            "rita.repositories.backtest.BacktestRunsRepository.read_all",
            return_value=[_mk_run()],
        ), patch(
            "rita.repositories.backtest.BacktestResultsRepository.read_all",
            return_value=self._two_results(),
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/risk-timeline")
            finally:
                _cleanup()

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        for row in data:
            assert required_fields.issubset(set(row.keys())), (
                f"Missing fields: {required_fields - set(row.keys())}"
            )

    def test_no_runs_returns_empty_list(self, db_session):
        """Edge case: no matching runs → []."""
        with patch(
            "rita.repositories.backtest.BacktestRunsRepository.read_all",
            return_value=[],
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/risk-timeline")
            finally:
                _cleanup()

        assert resp.status_code == 200
        assert resp.json() == []

    def test_instrument_casing_normalised_to_upper(self, db_session):
        """Edge case: lowercase instrument param → normalised to NIFTY → finds run."""
        run = _mk_run(instrument="NIFTY")
        results = self._two_results()

        with patch(
            "rita.repositories.backtest.BacktestRunsRepository.read_all",
            return_value=[run],
        ), patch(
            "rita.repositories.backtest.BacktestResultsRepository.read_all",
            return_value=results,
        ):
            client = _client_with_db(db_session)
            try:
                # Pass lowercase 'nifty' — endpoint does instrument.upper()
                resp = client.get("/api/v1/experience/rita/risk-timeline?instrument=nifty")
            finally:
                _cleanup()

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_phase_param_accepted_but_not_used_for_filtering(self, db_session):
        """phase=train must be accepted (forward-compat stub) — returns same data."""
        with patch(
            "rita.repositories.backtest.BacktestRunsRepository.read_all",
            return_value=[_mk_run()],
        ), patch(
            "rita.repositories.backtest.BacktestResultsRepository.read_all",
            return_value=self._two_results(),
        ):
            client = _client_with_db(db_session)
            try:
                resp_all   = client.get("/api/v1/experience/rita/risk-timeline?phase=all")
                resp_train = client.get("/api/v1/experience/rita/risk-timeline?phase=train")
            finally:
                _cleanup()

        assert resp_all.status_code == 200
        assert resp_train.status_code == 200
        # Both should return same number of rows (phase not yet used for filtering)
        assert len(resp_all.json()) == len(resp_train.json())

    def test_single_data_point_rolling_vol_is_none(self, db_session):
        """Edge case: single result row → rolling_vol_20d is None (< 2 data points)."""
        single_result = _mk_result(date_val=date(2026, 1, 1))
        with patch(
            "rita.repositories.backtest.BacktestRunsRepository.read_all",
            return_value=[_mk_run()],
        ), patch(
            "rita.repositories.backtest.BacktestResultsRepository.read_all",
            return_value=[single_result],
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/risk-timeline")
            finally:
                _cleanup()

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        # With only 1 point, rolling_vol_20d requires >= 2 returns — must be None
        assert data[0]["rolling_vol_20d"] is None


# ===========================================================================
# GET /api/v1/experience/rita/training-history
# ===========================================================================

class TestExperienceTrainingHistory:
    """Tests for the experience-tier training-history endpoint."""

    def test_happy_path_returns_list_with_required_fields(self, db_session):
        """Happy path: two training runs → list newest-first, required fields present."""
        required_fields = {
            "round", "run_id", "instrument", "timestamp", "model_version",
            "algorithm", "status", "timesteps", "source",
            "train_sharpe", "train_mdd_pct", "train_return_pct", "train_trades",
            "val_sharpe", "val_mdd_pct", "val_return_pct", "val_cagr_pct", "val_trades",
            "backtest_sharpe", "backtest_mdd_pct", "backtest_return_pct",
            "backtest_cagr_pct", "backtest_trades", "backtest_constraints_met", "notes",
        }
        run1 = _mk_training_run(run_id="tr-001")
        run2 = _mk_training_run(run_id="tr-002")

        with patch(
            "rita.repositories.training.TrainingRunsRepository.read_all",
            return_value=[run1, run2],
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/training-history")
            finally:
                _cleanup()

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        for row in data:
            assert required_fields.issubset(set(row.keys())), (
                f"Missing fields: {required_fields - set(row.keys())}"
            )

    def test_no_runs_returns_empty_list(self, db_session):
        """Edge case: no training runs for requested instrument → []."""
        with patch(
            "rita.repositories.training.TrainingRunsRepository.read_all",
            return_value=[],
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/training-history?instrument=NIFTY")
            finally:
                _cleanup()

        assert resp.status_code == 200
        assert resp.json() == []

    def test_backtest_mdd_none_guard_preserved(self, db_session):
        """Edge case: backtest_mdd=None → backtest_constraints_met is None, no crash."""
        run = _mk_training_run(backtest_mdd=None, backtest_sharpe=None)

        with patch(
            "rita.repositories.training.TrainingRunsRepository.read_all",
            return_value=[run],
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/training-history")
            finally:
                _cleanup()

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        # When both sharpe and mdd are None, bt_constraints must be None not a bool
        assert data[0]["backtest_constraints_met"] is None

    def test_instrument_filter_excludes_other_instruments(self, db_session):
        """Only runs for the requested instrument are returned."""
        run_nifty = _mk_training_run(run_id="tr-nifty", instrument="NIFTY")
        run_bnf   = _mk_training_run(run_id="tr-bnf", instrument="BANKNIFTY")

        with patch(
            "rita.repositories.training.TrainingRunsRepository.read_all",
            return_value=[run_nifty, run_bnf],
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/training-history?instrument=NIFTY")
            finally:
                _cleanup()

        assert resp.status_code == 200
        data = resp.json()
        assert all(row["instrument"] == "NIFTY" for row in data)

    def test_results_are_newest_first(self, db_session):
        """Verify response is in descending chronological order (newest run first)."""
        run1 = _mk_training_run(run_id="tr-001")
        run1.recorded_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        run2 = _mk_training_run(run_id="tr-002")
        run2.recorded_at = datetime(2026, 3, 1, tzinfo=timezone.utc)

        with patch(
            "rita.repositories.training.TrainingRunsRepository.read_all",
            return_value=[run1, run2],
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/training-history")
            finally:
                _cleanup()

        assert resp.status_code == 200
        data = resp.json()
        # After sort by recorded_at asc then reverse: newest first
        assert data[0]["run_id"] == "tr-002"
        assert data[1]["run_id"] == "tr-001"


# ===========================================================================
# POST /api/v1/portfolio/adjust-position-action
# ===========================================================================

class TestAdjustPositionAction:
    """Tests for the new portfolio POST endpoint."""

    def _mock_manoeuvre_result(self, manoeuvre_id: str = "man-abc123"):
        result = MagicMock()
        result.manoeuvre_id = manoeuvre_id
        return result

    def test_happy_path_returns_status_ok_with_manoeuvre_id(self, db_session):
        """Happy path: valid payload → {status: ok, manoeuvre_id: <str>}."""
        payload = {
            "date": "2026-05-17",
            "month": "MAY",
            "action": "add",
            "lot_key": "NIFTY26MAY22700CE_L1",
            "from_group": "",
            "to_group": "anchor",
            "nifty_spot": 22700.0,
            "banknifty_spot": None,
        }
        mock_result = self._mock_manoeuvre_result("man-abc123")

        with patch(
            "rita.services.manoeuvre_service.ManoeuvreService.record",
            return_value=mock_result,
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.post("/api/v1/portfolio/adjust-position-action", json=payload)
            finally:
                _cleanup()

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "manoeuvre_id" in data
        assert data["manoeuvre_id"] == "man-abc123"

    def test_empty_date_field_defaults_to_today(self, db_session):
        """Edge case: date="" in payload → endpoint defaults to today(), no 422 error."""
        payload = {
            "date": "",          # empty date string
            "month": "MAY",
            "action": "remove",
            "lot_key": "NIFTY26MAY22700CE_L1",
            "from_group": "anchor",
            "to_group": "",
            "nifty_spot": None,
            "banknifty_spot": None,
        }
        mock_result = self._mock_manoeuvre_result("man-xyz456")

        with patch(
            "rita.services.manoeuvre_service.ManoeuvreService.record",
            return_value=mock_result,
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.post("/api/v1/portfolio/adjust-position-action", json=payload)
            finally:
                _cleanup()

        # Must not be 422 — endpoint handles empty date gracefully
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_timestamp_not_required_in_payload(self, db_session):
        """Verify endpoint does not require 'timestamp' in the JSON body (injected server-side)."""
        payload = {
            "date": "2026-05-17",
            "month": "MAY",
            "action": "roll",
            "lot_key": "NIFTY26MAY22700PE_L1",
            "from_group": "hedge",
            "to_group": "hedge",
            # No 'timestamp' key at all
        }
        mock_result = self._mock_manoeuvre_result("man-ts-test")

        with patch(
            "rita.services.manoeuvre_service.ManoeuvreService.record",
            return_value=mock_result,
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.post("/api/v1/portfolio/adjust-position-action", json=payload)
            finally:
                _cleanup()

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_service_raises_returns_error_shape(self, db_session):
        """Edge case: ManoeuvreService.record() raises → returns {status: error, detail: ...}."""
        payload = {
            "date": "2026-05-17",
            "month": "MAY",
            "action": "adjust",
            "lot_key": "NIFTY26MAY22700CE_L1",
        }

        with patch(
            "rita.services.manoeuvre_service.ManoeuvreService.record",
            side_effect=RuntimeError("DB write failed"),
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.post("/api/v1/portfolio/adjust-position-action", json=payload)
            finally:
                _cleanup()

        # Endpoint catches exception and returns error shape (not a 500 raise)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "detail" in data

    def test_minimal_payload_accepted(self, db_session):
        """All fields have defaults — minimal payload with only required semantics accepted."""
        # The Pydantic model has all fields with defaults, so empty body is fine
        mock_result = self._mock_manoeuvre_result("man-min")

        with patch(
            "rita.services.manoeuvre_service.ManoeuvreService.record",
            return_value=mock_result,
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.post("/api/v1/portfolio/adjust-position-action", json={})
            finally:
                _cleanup()

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ===========================================================================
# API-Frontend contract verification (inline assertions)
# ===========================================================================

class TestAPIFrontendContract:
    """Verify that endpoint response field names match JS consumer expectations.

    The brief states: 'Field name changes: None. Response shapes are identical
    to existing system routes.'  These tests confirm the fields each JS module
    reads are present in the endpoint responses.
    """

    def test_backtest_daily_has_fields_consumed_by_performance_scenarios_diagnostics_js(self, db_session):
        """performance.js, scenarios.js, diagnostics.js read: date, portfolio_value, benchmark_value, allocation, close_price."""
        with patch(
            "rita.repositories.backtest.BacktestRunsRepository.read_all",
            return_value=[_mk_run()],
        ), patch(
            "rita.repositories.backtest.BacktestResultsRepository.read_all",
            return_value=[_mk_result()],
        ), patch(
            "rita.repositories.config_overrides.ConfigOverridesRepository.find_by_id",
            return_value=None,
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/backtest-daily")
            finally:
                _cleanup()

        assert resp.status_code == 200
        row = resp.json()[0]
        # JS reads these exact keys:
        for key in ("date", "portfolio_value", "benchmark_value", "allocation", "close_price"):
            assert key in row, f"Field '{key}' expected by JS consumers is missing from response"

    def test_risk_timeline_has_fields_consumed_by_risk_trades_js(self, db_session):
        """risk.js and trades.js read: date, portfolio_value, allocation, current_drawdown_pct, regime, phase."""
        r1 = _mk_result(date_val=date(2026, 1, 1))
        r2 = _mk_result(date_val=date(2026, 1, 2))
        with patch(
            "rita.repositories.backtest.BacktestRunsRepository.read_all",
            return_value=[_mk_run()],
        ), patch(
            "rita.repositories.backtest.BacktestResultsRepository.read_all",
            return_value=[r1, r2],
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/risk-timeline")
            finally:
                _cleanup()

        assert resp.status_code == 200
        row = resp.json()[0]
        for key in ("date", "portfolio_value", "allocation", "current_drawdown_pct", "regime", "phase"):
            assert key in row, f"Field '{key}' expected by JS consumers is missing from response"

    def test_training_history_has_fields_consumed_by_training_audit_js(self, db_session):
        """training.js and audit.js read: round, run_id, status, backtest_sharpe, backtest_mdd_pct, backtest_constraints_met."""
        with patch(
            "rita.repositories.training.TrainingRunsRepository.read_all",
            return_value=[_mk_training_run()],
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.get("/api/v1/experience/rita/training-history")
            finally:
                _cleanup()

        assert resp.status_code == 200
        row = resp.json()[0]
        for key in ("round", "run_id", "status", "backtest_sharpe", "backtest_mdd_pct", "backtest_constraints_met"):
            assert key in row, f"Field '{key}' expected by JS consumers is missing from response"

    def test_adjust_position_action_returns_status_and_manoeuvre_id(self, db_session):
        """manoeuvre.js reads: status, manoeuvre_id from POST response."""
        mock_result = MagicMock()
        mock_result.manoeuvre_id = "man-contract-check"

        with patch(
            "rita.services.manoeuvre_service.ManoeuvreService.record",
            return_value=mock_result,
        ):
            client = _client_with_db(db_session)
            try:
                resp = client.post(
                    "/api/v1/portfolio/adjust-position-action",
                    json={"date": "2026-05-17", "month": "MAY", "action": "add", "lot_key": "X_L1"},
                )
            finally:
                _cleanup()

        assert resp.status_code == 200
        data = resp.json()
        # Both fields must be present for the JS consumer
        assert "status" in data
        assert "manoeuvre_id" in data
        assert data["status"] == "ok"
