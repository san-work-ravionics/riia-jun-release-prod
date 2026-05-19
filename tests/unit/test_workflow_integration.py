"""Integration tests for WorkflowService.

Most tests use the ``db_session`` fixture (in-memory SQLite, function-scoped).
The background-thread completion test uses the real on-disk engine via
``SessionLocal`` because the daemon thread opens its own session and writes
to whichever DB the engine points at — not the test fixture's in-memory DB.

All rita.* imports are deferred to inside test functions per project constraints.
"""

from __future__ import annotations

import time

import pytest


# ---------------------------------------------------------------------------
# Helper: build a minimal TrainingRunCreate
# ---------------------------------------------------------------------------


def _make_run_create(*, model_version: str = "v-test", timesteps: int = 1000):
    from rita.schemas.training import TrainingRunCreate

    return TrainingRunCreate(
        model_version=model_version,
        algorithm="DoubleDQN",
        timesteps=timesteps,
        learning_rate=1e-4,
        buffer_size=10000,
        net_arch="[64, 64]",
        exploration_pct=0.1,
    )


# ---------------------------------------------------------------------------
# Tests using in-memory db_session fixture
# ---------------------------------------------------------------------------


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_start_training_returns_pending(db_session) -> None:
    """start_training() immediately returns a TrainingRun with status='pending'."""
    from rita.services.workflow_service import WorkflowService

    svc = WorkflowService(db_session)
    body = _make_run_create()
    run = svc.start_training(body)

    assert run.status == "pending"
    assert run.run_id is not None
    assert len(run.run_id) == 36


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_start_training_persists_run(db_session) -> None:
    """After start_training(), get_run(run_id) finds the record."""
    from rita.services.workflow_service import WorkflowService

    svc = WorkflowService(db_session)
    body = _make_run_create()
    run = svc.start_training(body)

    found = svc.get_run(run.run_id)
    assert found is not None
    assert found.run_id == run.run_id


def test_list_runs_empty_initially(db_session) -> None:
    """list_runs() returns [] on fresh DB."""
    from rita.services.workflow_service import WorkflowService

    svc = WorkflowService(db_session)
    assert svc.list_runs() == []


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_list_runs_after_start(db_session) -> None:
    """list_runs() contains the new run after start_training()."""
    from rita.services.workflow_service import WorkflowService

    svc = WorkflowService(db_session)
    body = _make_run_create(model_version="v-list-test")
    run = svc.start_training(body)

    runs = svc.list_runs()
    assert len(runs) == 1
    assert runs[0].run_id == run.run_id


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_list_metrics_empty_before_completion(db_session) -> None:
    """list_metrics() returns [] for a run that hasn't completed yet.

    The background thread uses a *different* DB (SessionLocal → on-disk),
    so the in-memory fixture's metrics table stays empty throughout the test.
    """
    from rita.services.workflow_service import WorkflowService

    svc = WorkflowService(db_session)
    body = _make_run_create()
    run = svc.start_training(body)

    # Metrics are written by the background thread to the real DB, not the
    # in-memory session, so this should always be empty here.
    metrics = svc.list_metrics(run.run_id)
    assert metrics == []


# ---------------------------------------------------------------------------
# End-to-end background thread test (uses real on-disk engine)
# ---------------------------------------------------------------------------


def test_background_thread_completes() -> None:
    """Background thread updates status from pending → complete within 2 s.

    Uses SessionLocal (real on-disk engine) so the thread's writes are visible
    to the querying session.  Ensures all tables exist before the test, then
    cleans up the test run on teardown.

    The real train() function invokes stable-baselines3 which takes too long
    for a unit test, so we patch it with a fast stub that returns a valid
    TrainingOutcome immediately.
    """
    from unittest.mock import patch, MagicMock
    from rita.database import Base, SessionLocal, engine
    from rita.services.workflow_service import WorkflowService
    from rita.schemas.training import TrainingRunCreate
    from rita.core.ml_dispatch import TrainingOutcome
    import rita.models  # noqa: F401 — ensure ORM models are registered with Base.metadata

    # Ensure the on-disk DB has all tables (idempotent — create_all is safe to re-run)
    Base.metadata.create_all(engine)

    _fast_outcome = TrainingOutcome(
        model_path="/tmp/v-thread-test_stub.zip",
        sharpe=1.42,
        max_drawdown=-0.12,
        total_return=0.28,
        episode_metrics=[
            {"episode": 1, "timestep": 1000, "reward": 0.0, "loss": 0.5,
             "epsilon": 0.05, "portfolio_value": 1.0}
        ],
    )

    db = SessionLocal()
    run_id: str | None = None
    try:
        # Patch train() for the duration of both start + polling so the
        # background thread (which runs concurrently) also uses the fast stub.
        with patch("rita.services.workflow_service.train", return_value=_fast_outcome):
            svc = WorkflowService(db)
            body = TrainingRunCreate(
                model_version="v-thread-test",
                algorithm="DoubleDQN",
                timesteps=1000,
                learning_rate=1e-4,
                buffer_size=10000,
                net_arch="[64, 64]",
                exploration_pct=0.1,
            )
            run = svc.start_training(body)
            run_id = run.run_id
            assert run.status == "pending"

            # Poll until status != "pending" or timeout after 2 s
            deadline = time.monotonic() + 2.0
            final_status = "pending"
            while time.monotonic() < deadline:
                time.sleep(0.1)
                db.expire_all()  # refresh from DB
                found = svc.get_run(run_id)
                if found and found.status != "pending":
                    final_status = found.status
                    break

        assert final_status == "complete", (
            f"Expected status='complete' within 2 s, got '{final_status}'"
        )
    finally:
        # Teardown: delete test run and its metrics
        if run_id is not None:
            from rita.models import TrainingMetricModel, TrainingRunModel

            db.query(TrainingMetricModel).filter(
                TrainingMetricModel.run_id == run_id
            ).delete()
            db.query(TrainingRunModel).filter(
                TrainingRunModel.run_id == run_id
            ).delete()
            db.commit()
        db.close()
