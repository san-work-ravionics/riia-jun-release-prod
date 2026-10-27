"""F44 P4 — pins the P3 / P2 output fields that Jarvis reads (GoalSelectionOut, HoldingOut,
RequiredReturnOut, ModelRunsOut, GoalOut, HedgePlanOut).  A rename in P3 must fail here first."""
from __future__ import annotations

import pytest

from rita.schemas.goal_selection import (
    GoalOut,
    GoalSelectionOut,
    HoldingOut,
    InstrumentRunsOut,
    MixOut,
    ModelRunOut,
    ModelRunsOut,
    RequiredReturnOut,
    RunMetricsOut,
)
from rita.schemas.user_hedge_plan import HedgePlanOut

READS = {
    GoalOut: {"location", "currency", "saved", "plan_updated_at", "goal_return", "horizon_years", "goal_value"},
    GoalSelectionOut: {"location", "currency", "target_return", "meets_goal", "tolerance", "fit_window",
                       "test_window", "fit_return", "test_return", "test_mdd", "gap", "holdings", "closest",
                       "cap_fit", "cap_test", "ladder", "method", "excluded", "as_of"},
    HoldingOut: {"instrument_id", "allocation_pct", "tolerance", "model_action", "sl_drawdown_limit",
                 "episode_start", "episode_length", "model_sha12"},
    MixOut: {"tolerance", "holdings", "fit_return", "test_return", "gap"},
    RequiredReturnOut: {"goal_return", "ytd_return", "required_return", "effective_return", "cap_fit", "status",
                        "reason", "reselections_used", "reselections_next", "max_reselections", "proposal"},
    ModelRunsOut: {"instruments", "excluded"},
    InstrumentRunsOut: {"instrument_id", "runs"},
    ModelRunOut: {"tolerance", "fit", "test", "today_action"},
    RunMetricsOut: {"ann_return", "mdd"},
    HedgePlanOut: {"hedged_ids", "coverage", "updated_at"},
}


@pytest.mark.parametrize("model", list(READS), ids=lambda m: m.__name__)
def test_fields_jarvis_reads_exist(model):
    assert READS[model] <= set(model.model_fields), READS[model] - set(model.model_fields)


def test_required_return_enums_jarvis_branches_on():
    status = RequiredReturnOut.model_fields["status"].annotation.__args__
    reason = RequiredReturnOut.model_fields["reason"].annotation.__args__
    assert set(status) == {"on_track", "reselect_proposed", "back_to_plan"}
    assert {"year_end", "count", "cap", "test_shortfall"} <= set(reason)


def test_method_weights_says_not_a_model():
    assert GoalSelectionOut.model_fields["method"].default_factory().weights.endswith("(not a model)")
