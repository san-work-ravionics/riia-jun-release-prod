"""Pydantic schemas for the model evaluation summary table (Feature 34, Phase 2.5).

Read-only Experience-tier response contract for
GET /api/v1/experience/rita/model-eval-summary.
One row per instrument in config/instruments/, populated from the latest
round of each models/<INSTRUMENT>/training_history.csv via
``rita.core.training_tracker.load_latest_round()``.
"""
from __future__ import annotations

from pydantic import BaseModel


class ModelEvalSummaryRow(BaseModel):
    """Latest training-round metrics for one instrument.

    ``gate_pass`` is ``None`` when the instrument has no training history
    (``has_history`` is false / metrics are null) — the frontend renders a
    neutral "NO DATA" badge for that state, never "BELOW GATE".
    """

    instrument:          str
    last_trained:        str | None = None
    timesteps:           int | None = None
    val_sharpe:          float | None = None
    val_mdd_pct:         float | None = None
    val_cagr_pct:        float | None = None
    backtest_sharpe:     float | None = None
    backtest_mdd_pct:    float | None = None
    backtest_return_pct: float | None = None
    trade_count:         int | None = None
    gate_pass:           bool | None = None
    source:              str | None = None  # "trained" | "loaded_existing"
    round:               int | None = None
    has_history:         bool = False

    model_config = {"from_attributes": True}


class ModelEvalSummaryResponse(BaseModel):
    """Summary table payload — rows sorted by backtest_sharpe desc, nulls last."""

    val_window:      str = "2023-2024"
    backtest_window: str = "2025-01 to present"
    gate_rule:       str = "backtest_sharpe >= 1.0 and |backtest_mdd_pct| <= 10"
    rows:            list[ModelEvalSummaryRow] = []

    model_config = {"from_attributes": True}
