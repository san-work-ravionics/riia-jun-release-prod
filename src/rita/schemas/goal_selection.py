"""Pydantic contracts for F44 P3 goal-driven selection (MCP tool outputs; no REST route).

Rates are fractions; dates are ISO.  Every selection output carries ``method`` — which part is a
model (the DDQN sleeves) and which is not (the min-variance weights solver, the lineage windows).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Tolerance = Literal["low", "medium", "high"]
ModelAction = Literal["cash", "half", "full", "hedged"]
ExclusionReason = Literal[
    "no_model", "load_failed", "feature_mismatch", "bad_data", "stale_data", "no_data",
    "data_integrity", "retrain_needed",
]


# ── whatineed.get_goal ─────────────────────────────────────────────────────────

class AssetRateOut(BaseModel):
    asset_class: Literal["idx", "eq", "com", "alt"]
    monthly: float | None = None
    rate: float | None = None


class GoalOut(BaseModel):
    """The user's saved goal. No saved plan → ``saved=false`` and nulls (presets are never
    treated as the user's goal)."""

    location: str
    currency: str
    saved: bool
    plan_updated_at: datetime | None = None
    goal_return: float | None = None       # Σ(monthly·rate)/Σmonthly
    horizon_years: float | None = None     # retire age − current age
    goal_value: float | None = None        # portfolio needed at retirement
    assets: list[AssetRateOut] = []


# ── shared pieces ──────────────────────────────────────────────────────────────

class ExcludedOut(BaseModel):
    instrument_id: str
    reason: ExclusionReason
    detail: str | None = None


class WindowOut(BaseModel):
    start: date
    end: date


class MethodOut(BaseModel):
    """Exact disclosure strings (design rev 3 N4)."""

    sleeves: str = "ddqn_v2 replay"
    weights: str = "min-variance solver over model sleeves, μ ≥ target (not a model)"
    window: str = "lineage fit/test"


class HoldingOut(BaseModel):
    """One holding. SL = the sleeve's drawdown from its peak since the later of entry and the
    current model-episode start, at ``sl_drawdown_limit`` (the lineage's training constraint
    ``hard_mdd_limit``, a config input — not a model output). The peak resets at each
    model-episode boundary, as in training; ``episode_start`` + ``episode_length`` give the next
    reset date. ``model_exit`` (action cash) / ``model_derisk`` (half or hedged) are the model's
    own signals, shown next to the SL."""

    instrument_id: str
    allocation_pct: int
    tolerance: Tolerance
    tolerance_mdd: float
    model_action: ModelAction
    model_exit: bool
    model_derisk: bool
    invested_pct: float                    # allocation_pct × the model's allocation today
    sl_drawdown_limit: float
    sl_basis: Literal["sleeve_drawdown_from_episode_peak"] = "sleeve_drawdown_from_episode_peak"
    episode_start: date
    episode_day: int
    episode_length: int
    model_sha12: str


class YearOut(BaseModel):
    year: int
    split: Literal["fit", "test"]
    year_return: float
    partial: bool
    met: bool


class MixOut(BaseModel):
    """A mix that is not the proposal (``closest``): fit and test figures + the test gap."""

    tolerance: Tolerance
    tolerance_mdd: float
    holdings: list[HoldingOut]
    fit_return: float
    fit_vol: float
    fit_mdd: float
    test_return: float
    test_vol: float
    test_mdd: float
    gap: float                              # target − test_return


class LadderOut(BaseModel):
    tolerance: Tolerance
    tolerance_mdd: float
    feasible: bool                          # a fit-feasible integer mix exists at this τ
    cap_fit: float
    cap_test: float
    fit_vol: float | None = None


class GradedOut(BaseModel):
    sharpe_gt_1: bool
    mdd_within_10: bool


# ── portfolio.select_for_goal ──────────────────────────────────────────────────

class GoalSelectionOut(BaseModel):
    location: str
    currency: str
    target_return: float
    meets_goal: bool                        # fit-feasible AND test return ≥ target
    engine: Literal["rita_ddqn_v2"] = "rita_ddqn_v2"
    lineage: str
    tolerance: Tolerance | None = None
    tolerance_mdd: float | None = None
    fit_window: WindowOut
    test_window: WindowOut
    fit_return: float | None = None         # in-sample for the solver — optimistic
    fit_vol: float | None = None
    fit_mdd: float | None = None
    test_return: float | None = None        # honest: never seen by the solve
    test_vol: float | None = None
    test_mdd: float | None = None
    test_sharpe: float | None = None
    rf_annual: float | None = None
    gap: float | None = None                # target − test_return when fit-feasible but short
    years: list[YearOut] = []
    holdings: list[HoldingOut] = []
    closest: MixOut | None = None
    cap_fit: float
    cap_test: float
    ladder: list[LadderOut] = []
    tolerance_sensitive: bool
    graded: GradedOut | None = None
    solver: Literal["slsqp", "fallback_segment"] | None = None
    fallback_checked: bool = False
    method: MethodOut = Field(default_factory=MethodOut)
    excluded: list[ExcludedOut] = []
    as_of: date
    window_start: date


# ── portfolio.required_return ──────────────────────────────────────────────────

class RequiredReturnOut(BaseModel):
    location: str
    goal_return: float
    ytd_return: float
    year_fraction: float
    remaining_fraction: float
    rest_of_year_return: float
    required_return: float | None = None
    effective_return: float | None = None
    cap_fit: float | None = None
    cap_test: float | None = None
    status: Literal["on_track", "reselect_proposed", "back_to_plan"]
    reason: Literal["ok", "year_end", "on_track", "count", "cap", "test_shortfall"]
    reselections_used: int
    reselections_next: int
    max_reselections: int
    proposal: GoalSelectionOut | None = None
    closest: MixOut | None = None
    method: MethodOut = Field(default_factory=MethodOut)


# ── portfolio.model_runs ───────────────────────────────────────────────────────

class RunMetricsOut(BaseModel):
    ann_return: float
    ann_vol: float
    mdd: float
    sharpe: float
    bars: int


class ModelRunOut(BaseModel):
    tolerance: Tolerance
    tolerance_mdd: float
    fit: RunMetricsOut
    test: RunMetricsOut
    oob_bars: int
    today_action: ModelAction


class InstrumentRunsOut(BaseModel):
    instrument_id: str
    lineage: str
    model_sha12: str
    rf_annual: float
    episode_length: int
    runs: list[ModelRunOut]


class ModelRunsOut(BaseModel):
    location: str
    lineage: str
    as_of: date
    window_start: date
    fit_window: WindowOut
    test_window: WindowOut
    instruments: list[InstrumentRunsOut]
    excluded: list[ExcludedOut] = []
    method: MethodOut = Field(default_factory=MethodOut)
