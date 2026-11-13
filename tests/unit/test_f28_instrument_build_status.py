"""Unit tests for F28 — instrument model build status endpoint.

Endpoint: GET /api/experience/ds/instrument-build-status
Handler:  rita.api.experience.ds.get_instrument_build_status
Schema:   rita.schemas.ds_instrument_status.{InstrumentBuildStatusItem,DsInstrumentBuildStatusResponse}

Patch targets (all resolved from handler source):
  - rita.repositories.instrument.InstrumentRepository  (lazy import inside handler)
  - rita.repositories.training.TrainingRunsRepository   (lazy import inside handler)
  - rita.api.experience.ds.get_settings                 (module-level import)
  - rita.api.experience.ds.Path                         (module-level import)

Tests
-----
1. test_happy_path
   Instruments NIFTY (complete) and BANKNIFTY (failed) are returned with
   correct build_status values and model_file_exists reflecting the glob result.

2. test_never_trained_edge_case
   An instrument with no training run gets build_status "never_trained",
   last_trained=None, model_version=None, model_file_exists=False.
   An OSError raised by glob() must NOT produce a 500 — the endpoint must
   return 200 with model_file_exists=False and a valid response body.
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
    notes: str | None = None,
):
    """Return a minimal TrainingRun schema instance."""
    from rita.schemas.training import TrainingRun

    return TrainingRun(
        run_id=run_id,
        instrument=instrument,
        model_version=model_version,
        algorithm="DoubleDQN",
        timesteps=200_000,
        learning_rate=1e-4,
        buffer_size=50_000,
        net_arch="[128, 128]",
        exploration_pct=0.1,
        notes=notes,
        status=status,
        recorded_at=_NOW,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInstrumentBuildStatus:
    """Unit tests for GET /api/experience/ds/instrument-build-status."""

    def test_happy_path(self, client):
        """Happy path: two instruments, one success and one failed.

        NIFTY  → status "complete"  → build_status "success", model_file_exists True
        BANKNIFTY → status "failed" → build_status "failed",  model_file_exists False
        """
        instruments = [
            _make_instrument("NIFTY", "Nifty 50"),
            _make_instrument("BANKNIFTY", "Bank Nifty"),
        ]
        runs = [
            _make_training_run("run-001", "NIFTY",     "complete", "v3"),
            _make_training_run("run-002", "BANKNIFTY", "failed",   "v2", notes="CUDA OOM"),
        ]

        # Repository mocks
        mock_inst_repo = MagicMock()
        mock_inst_repo.return_value.read_all.return_value = instruments

        mock_train_repo = MagicMock()
        mock_train_repo.return_value.get_latest_per_instrument.return_value = runs

        # Settings mock — model.path is a string consumed by Path(...)
        mock_settings = MagicMock()
        mock_settings.model.path = "/mock/models"

        # Path mock: Path("/mock/models") / "NIFTY" → dir with zip
        #            Path("/mock/models") / "BANKNIFTY" → empty dir
        nifty_dir = MagicMock()
        nifty_dir.glob.return_value = iter(["nifty_v3.zip"])

        banknifty_dir = MagicMock()
        banknifty_dir.glob.return_value = iter([])

        model_base = MagicMock()
        model_base.__truediv__ = MagicMock(
            side_effect=lambda sym: nifty_dir if sym == "NIFTY" else banknifty_dir
        )

        mock_path_cls = MagicMock(return_value=model_base)

        with (
            patch("rita.repositories.instrument.InstrumentRepository", mock_inst_repo),
            patch("rita.repositories.training.TrainingRunsRepository", mock_train_repo),
            patch("rita.api.experience.ds.get_settings", return_value=mock_settings),
            patch("rita.api.experience.ds.Path", mock_path_cls),
        ):
            resp = client.get("/api/experience/ds/instrument-build-status")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

        # Top-level response shape
        assert "instruments" in data
        assert "total" in data
        assert "as_of" in data
        assert data["total"] == 2
        assert len(data["instruments"]) == 2

        by_symbol = {item["symbol"]: item for item in data["instruments"]}

        # NIFTY — complete run → success
        nifty = by_symbol["NIFTY"]
        assert nifty["build_status"] == "success"
        assert nifty["model_file_exists"] is True
        assert nifty["model_version"] == "v3"
        assert nifty["error_message"] is None
        assert nifty["last_trained"] is not None  # ISO-8601 from recorded_at

        # BANKNIFTY — failed run
        banknifty = by_symbol["BANKNIFTY"]
        assert banknifty["build_status"] == "failed"
        assert banknifty["model_file_exists"] is False
        assert banknifty["error_message"] == "CUDA OOM"
        assert banknifty["model_version"] == "v2"

    def test_never_trained_edge_case(self, client):
        """Edge case: instrument with no training run.

        Expected:
          - build_status == "never_trained"
          - last_trained is None
          - model_version is None
          - error_message is None
          - model_file_exists == False even when glob() raises OSError
          - Response status is 200 (no 500 from the OSError)
        """
        instruments = [
            _make_instrument("JIOFIN", "Jio Financial Services"),
        ]

        mock_inst_repo = MagicMock()
        mock_inst_repo.return_value.read_all.return_value = instruments

        mock_train_repo = MagicMock()
        # No training runs for this instrument
        mock_train_repo.return_value.get_latest_per_instrument.return_value = []

        mock_settings = MagicMock()
        mock_settings.model.path = "/nonexistent/models"

        # Simulate OSError when glob is called (PermissionError / missing dir)
        jiofin_dir = MagicMock()
        jiofin_dir.glob.side_effect = OSError("Permission denied")

        model_base = MagicMock()
        model_base.__truediv__ = MagicMock(return_value=jiofin_dir)

        mock_path_cls = MagicMock(return_value=model_base)

        with (
            patch("rita.repositories.instrument.InstrumentRepository", mock_inst_repo),
            patch("rita.repositories.training.TrainingRunsRepository", mock_train_repo),
            patch("rita.api.experience.ds.get_settings", return_value=mock_settings),
            patch("rita.api.experience.ds.Path", mock_path_cls),
        ):
            resp = client.get("/api/experience/ds/instrument-build-status")

        # OSError on glob must NOT propagate as a 500
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

        assert data["total"] == 1
        item = data["instruments"][0]

        assert item["symbol"] == "JIOFIN"
        assert item["build_status"] == "never_trained"
        assert item["model_file_exists"] is False
        assert item["last_trained"] is None
        assert item["model_version"] is None
        assert item["error_message"] is None
