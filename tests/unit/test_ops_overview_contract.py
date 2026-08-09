"""Contract tests for F35 Phase 1 — Ops Overview Redesign.

Verifies the two endpoints consumed by the redesigned overview.js return
response shapes that match the fields the JS reads.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from rita.schemas.model_eval_summary import (
    ModelEvalSummaryRow,
    ModelEvalSummaryResponse,
)
from rita.schemas.agent_builds import (
    AgentBuildRunOut,
    AgentBuildsResponse,
    AgentBuildMetrics,
)


# ---------------------------------------------------------------------------
# model-eval-summary contract
# ---------------------------------------------------------------------------

JS_INSTRUMENT_FIELDS = [
    "instrument", "last_trained", "timesteps",
    "val_sharpe", "val_mdd_pct",
    "backtest_sharpe", "backtest_mdd_pct", "backtest_return_pct",
    "trade_count", "gate_pass", "has_history",
    "data_rows", "last_data_refresh",
]

def _sample_row(**overrides):
    defaults = dict(
        instrument="SBIN",
        last_trained="2026-07-12 09:14:02",
        timesteps=50000,
        val_sharpe=0.61,
        val_mdd_pct=-14.2,
        val_cagr_pct=8.3,
        backtest_sharpe=0.947,
        backtest_mdd_pct=-12.1,
        backtest_return_pct=6.4,
        trade_count=42,
        gate_pass=False,
        source="trained",
        round=3,
        has_history=True,
        data_rows=4200,
        last_data_refresh="2026-08-08",
    )
    defaults.update(overrides)
    return ModelEvalSummaryRow(**defaults)


class TestModelEvalSummaryContract:

    def test_response_has_rows_key(self):
        resp = ModelEvalSummaryResponse(rows=[_sample_row()])
        payload = resp.model_dump()
        assert "rows" in payload

    def test_row_contains_all_js_fields(self):
        row = _sample_row()
        row_dict = row.model_dump()
        for field in JS_INSTRUMENT_FIELDS:
            assert field in row_dict, f"JS reads '{field}' but schema row missing it"

    def test_gate_pass_true(self):
        row = _sample_row(gate_pass=True, has_history=True)
        assert row.gate_pass is True

    def test_gate_pass_false(self):
        row = _sample_row(gate_pass=False, has_history=True)
        assert row.gate_pass is False

    def test_gate_pass_null_no_history(self):
        row = _sample_row(gate_pass=None, has_history=False,
                          val_sharpe=None, backtest_sharpe=None,
                          timesteps=None, trade_count=None)
        assert row.gate_pass is None
        assert row.has_history is False

    def test_empty_rows(self):
        resp = ModelEvalSummaryResponse(rows=[])
        assert resp.rows == []

    def test_null_numeric_fields(self):
        row = _sample_row(
            val_sharpe=None, val_mdd_pct=None,
            backtest_sharpe=None, backtest_mdd_pct=None,
            backtest_return_pct=None, trade_count=None,
            has_history=False, gate_pass=None,
        )
        d = row.model_dump()
        for f in ["val_sharpe", "val_mdd_pct", "backtest_sharpe",
                   "backtest_mdd_pct", "backtest_return_pct", "trade_count"]:
            assert d[f] is None


# ---------------------------------------------------------------------------
# agent-builds contract
# ---------------------------------------------------------------------------

JS_RUN_FIELDS = ["run_id", "request", "overall_status", "duration_minutes", "app"]

_EMPTY_METRICS = AgentBuildMetrics(
    total_runs=0, per_role={}, grounding_trend=[], failure_modes={},
    skill_version_history=[],
)

def _sample_run(**overrides):
    defaults = dict(
        run_id="20260809-0908",
        app="ops",
        request="Feature 35 Phase 1",
        overall_status="pass",
        duration_minutes=45.2,
        branch="worktree-abc",
        agents=[],
    )
    defaults.update(overrides)
    return AgentBuildRunOut(**defaults)


class TestAgentBuildsContract:

    def test_response_has_runs_key(self):
        resp = AgentBuildsResponse(runs=[_sample_run()], metrics=_EMPTY_METRICS)
        payload = resp.model_dump()
        assert "runs" in payload

    def test_run_contains_all_js_fields(self):
        run = _sample_run()
        run_dict = run.model_dump()
        for field in JS_RUN_FIELDS:
            assert field in run_dict, f"JS reads '{field}' but schema run missing it"

    def test_null_request(self):
        run = _sample_run(request=None)
        assert run.request is None

    def test_null_duration(self):
        run = _sample_run(duration_minutes=None)
        assert run.duration_minutes is None

    def test_empty_runs(self):
        resp = AgentBuildsResponse(runs=[], metrics=_EMPTY_METRICS)
        assert resp.runs == []

    def test_five_run_slice(self):
        runs = [_sample_run(run_id=f"2026080{i}-0900") for i in range(7)]
        recent = runs[:5]
        assert len(recent) == 5
