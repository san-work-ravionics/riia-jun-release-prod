"""Unit tests for F28 Phase 2 — per-instrument metric fields in build-status endpoint.

Endpoint: GET /api/experience/ds/instrument-build-status
Handler:  rita.api.experience.ds.get_instrument_build_status
Schema:   rita.schemas.ds_instrument_status.InstrumentBuildStatusItem  (Phase 2 fields)

New Phase-2 fields under test:
  return_pct, cagr_pct, sharpe_ratio, max_drawdown_pct — derived from training_runs
  win_rate_pct — always None (not stored in training_runs)
  sharpe_constraint_met  — val_sharpe >= 1.0
  drawdown_constraint_met — abs(val_mdd * 100) < 25.0
  constraints_met         — sharpe_constraint_met AND drawdown_constraint_met
  last_run_round, last_run_timestamp, last_run_timesteps — from training_runs

Tests
-----
T1: test_complete_run_metrics_populated
    Instrument NIFTY with a complete training run carrying all metric fields.
    - return_pct  == val_return * 100
    - cagr_pct    == val_cagr   * 100
    - sharpe_ratio == val_sharpe (1.5)
    - max_drawdown_pct == val_mdd * 100 (-15.0)
    - win_rate_pct is always None
    - sharpe_constraint_met True  (1.5 >= 1.0)
    - drawdown_constraint_met True  (abs(-15.0) < 25.0)
    - constraints_met True

T2: test_no_training_run_metrics_all_none
    Instrument with no training run — all Phase-2 metric and constraint fields are None.

T3: test_constraint_edge_cases_both_fail
    Instrument with sharpe < 1.0 and abs(mdd_pct) >= 25.0 → both constraints False,
    constraints_met False.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


_NOW = datetime(2026, 11, 13, 10, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_instrument(instrument_id: str, name: str):
    """Return a minimal Instrument schema instance."""
    from rita.schemas.instrument import Instrument

    return Instrument(
        instrument_id=instrument_id,
        name=name,
        exchange="NSE",
        country_code="IN",
        is_available=True,
        created_at=_NOW,
    )


def _make_training_run(
    run_id: str,
    instrument: str,
    status: str,
    model_version: str,
    *,
    timesteps: int = 200_000,
    notes: str | None = None,
    val_return: float | None = None,
    val_cagr: float | None = None,
    val_sharpe: float | None = None,
    val_mdd: float | None = None,
):
    """Return a TrainingRun schema instance with optional metric fields."""
    from rita.schemas.training import TrainingRun

    return TrainingRun(
        run_id=run_id,
        instrument=instrument,
        model_version=model_version,
        algorithm="DoubleDQN",
        timesteps=timesteps,
        learning_rate=1e-4,
        buffer_size=50_000,
        net_arch="[128, 128]",
        exploration_pct=0.1,
        notes=notes,
        status=status,
        recorded_at=_NOW,
        val_return=val_return,
        val_cagr=val_cagr,
        val_sharpe=val_sharpe,
        val_mdd=val_mdd,
    )


def _mock_path_no_zip():
    """Return a Path mock whose glob yields no ZIP files."""
    model_dir = MagicMock()
    model_dir.glob.return_value = iter([])
    model_base = MagicMock()
    model_base.__truediv__ = MagicMock(return_value=model_dir)
    return MagicMock(return_value=model_base)


def _mock_settings():
    settings = MagicMock()
    settings.model.path = "/mock/models"
    return settings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestF28P2InstrumentMetrics:
    """Unit tests for Phase 2 per-instrument metric fields."""

    def test_complete_run_metrics_populated(self, client):
        """T1: Instrument with complete training run — all metric fields populated.

        val_return=0.25 → return_pct=25.0
        val_cagr=0.18   → cagr_pct=18.0
        val_sharpe=1.5  → sharpe_ratio=1.5, sharpe_constraint_met=True
        val_mdd=-0.15   → max_drawdown_pct=-15.0, drawdown_constraint_met=True (abs(-15)<25)
        win_rate_pct    → always None
        constraints_met → True
        last_run_round  → "run-nifty-001"
        last_run_timesteps → 300000
        """
        instruments = [_make_instrument("NIFTY", "Nifty 50")]
        runs = [
            _make_training_run(
                "run-nifty-001", "NIFTY", "complete", "v5",
                timesteps=300_000,
                val_return=0.25,
                val_cagr=0.18,
                val_sharpe=1.5,
                val_mdd=-0.15,
            )
        ]

        mock_inst_repo = MagicMock()
        mock_inst_repo.return_value.read_all.return_value = instruments

        mock_train_repo = MagicMock()
        mock_train_repo.return_value.get_latest_per_instrument.return_value = runs

        with (
            patch("rita.repositories.instrument.InstrumentRepository", mock_inst_repo),
            patch("rita.repositories.training.TrainingRunsRepository", mock_train_repo),
            patch("rita.api.experience.ds.get_settings", return_value=_mock_settings()),
            patch("rita.api.experience.ds.Path", _mock_path_no_zip()),
        ):
            resp = client.get("/api/experience/ds/instrument-build-status")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

        assert data["total"] == 1
        item = data["instruments"][0]

        # Metric value assertions
        assert abs(item["return_pct"] - 25.0) < 1e-6, f"return_pct: {item['return_pct']}"
        assert abs(item["cagr_pct"] - 18.0) < 1e-6, f"cagr_pct: {item['cagr_pct']}"
        assert abs(item["sharpe_ratio"] - 1.5) < 1e-6, f"sharpe_ratio: {item['sharpe_ratio']}"
        assert abs(item["max_drawdown_pct"] - (-15.0)) < 1e-6, f"max_drawdown_pct: {item['max_drawdown_pct']}"

        # win_rate_pct is always None
        assert item["win_rate_pct"] is None

        # Constraint assertions
        assert item["sharpe_constraint_met"] is True, "sharpe 1.5 >= 1.0 → should be met"
        assert item["drawdown_constraint_met"] is True, "abs(-15) < 25 → should be met"
        assert item["constraints_met"] is True

        # Run metadata fields
        assert item["last_run_round"] == "run-nifty-001"
        assert item["last_run_timesteps"] == 300_000
        assert item["last_run_timestamp"] is not None

    def test_no_training_run_metrics_all_none(self, client):
        """T2: Instrument with no training run — all Phase-2 fields are None.

        When runs_by_symbol has no entry for the instrument, every metric and
        constraint field must come back as None.
        """
        instruments = [_make_instrument("FINNIFTY", "Fin Nifty")]

        mock_inst_repo = MagicMock()
        mock_inst_repo.return_value.read_all.return_value = instruments

        mock_train_repo = MagicMock()
        mock_train_repo.return_value.get_latest_per_instrument.return_value = []  # no runs

        with (
            patch("rita.repositories.instrument.InstrumentRepository", mock_inst_repo),
            patch("rita.repositories.training.TrainingRunsRepository", mock_train_repo),
            patch("rita.api.experience.ds.get_settings", return_value=_mock_settings()),
            patch("rita.api.experience.ds.Path", _mock_path_no_zip()),
        ):
            resp = client.get("/api/experience/ds/instrument-build-status")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

        assert data["total"] == 1
        item = data["instruments"][0]

        # Build status
        assert item["build_status"] == "never_trained"

        # All Phase-2 metric fields must be None
        for field in (
            "return_pct", "cagr_pct", "sharpe_ratio", "max_drawdown_pct",
            "win_rate_pct", "sharpe_constraint_met", "drawdown_constraint_met",
            "constraints_met", "last_run_round", "last_run_timestamp", "last_run_timesteps",
        ):
            assert item[field] is None, f"Expected {field}=None, got {item[field]}"

    def test_constraint_edge_cases_both_fail(self, client):
        """T3: sharpe < 1.0 AND abs(mdd_pct) >= 25.0 → both constraints False.

        val_sharpe=0.8  → sharpe_constraint_met=False  (0.8 < 1.0)
        val_mdd=-0.30   → max_drawdown_pct=-30.0, drawdown_constraint_met=False (abs(-30) >= 25)
        constraints_met → False
        """
        instruments = [_make_instrument("BANKNIFTY", "Bank Nifty")]
        runs = [
            _make_training_run(
                "run-bnk-007", "BANKNIFTY", "complete", "v2",
                val_return=0.05,
                val_cagr=0.03,
                val_sharpe=0.8,
                val_mdd=-0.30,
            )
        ]

        mock_inst_repo = MagicMock()
        mock_inst_repo.return_value.read_all.return_value = instruments

        mock_train_repo = MagicMock()
        mock_train_repo.return_value.get_latest_per_instrument.return_value = runs

        with (
            patch("rita.repositories.instrument.InstrumentRepository", mock_inst_repo),
            patch("rita.repositories.training.TrainingRunsRepository", mock_train_repo),
            patch("rita.api.experience.ds.get_settings", return_value=_mock_settings()),
            patch("rita.api.experience.ds.Path", _mock_path_no_zip()),
        ):
            resp = client.get("/api/experience/ds/instrument-build-status")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

        assert data["total"] == 1
        item = data["instruments"][0]

        # Constraint failures
        assert item["sharpe_constraint_met"] is False, f"sharpe 0.8 < 1.0 → should fail; got {item['sharpe_constraint_met']}"
        assert item["drawdown_constraint_met"] is False, f"abs(-30) >= 25 → should fail; got {item['drawdown_constraint_met']}"
        assert item["constraints_met"] is False

        # Metric values still populated
        assert abs(item["sharpe_ratio"] - 0.8) < 1e-6
        assert abs(item["max_drawdown_pct"] - (-30.0)) < 1e-6
        assert item["win_rate_pct"] is None
